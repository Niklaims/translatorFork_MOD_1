import os
import pytest
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
import io
import time

from gemini_translator.server.opds_server import OPDSManager, DEFAULT_PORT


@pytest.fixture
def temp_chapter_file(tmp_path):
    """Создает временный HTML-файл для тестов."""
    filepath = tmp_path / "chapter_test.html"
    filepath.write_text("<html><body><h1>Test Chapter</h1><p>Content here.</p></body></html>", encoding="utf-8")
    return str(filepath)


@pytest.fixture
def opds_manager(tmp_path):
    """Возвращает чистый экземпляр менеджера, использующий временный файл."""
    manager = OPDSManager()
    manager._state_file = str(tmp_path / "test_opds_state.json")
    manager._books = {} # Начинаем с чистого листа
    yield manager
    if manager.is_running():
        manager.stop()


def test_opds_manager_add_book(opds_manager, temp_chapter_file):
    """Проверяем, что менеджер корректно хранит книги и главы."""
    book_id = "test_project_1"
    chapters = [{"title": "Chapter 1", "filepath": temp_chapter_file}]
    
    opds_manager.add_or_update_book(book_id, "Test Book", "Test Author", chapters)
    
    book = opds_manager.get_book(book_id)
    assert book is not None
    assert book["title"] == "Test Book"
    assert book["author"] == "Test Author"
    assert len(book["chapters"]) == 1
    
    # Проверяем счетчик всех глав
    assert opds_manager.chapter_count() == 1
    
    # Добавляем вторую книгу
    opds_manager.add_or_update_book("test_project_2", "Book 2", "Author 2", [])
    assert opds_manager.chapter_count() == 1 # Во второй книге нет глав
    assert opds_manager.get_book("test_project_2") is not None


def test_opds_manager_xml_generation(opds_manager, temp_chapter_file):
    """Проверяем, что генерируется валидный XML каталог."""
    book_id = "test_project_xml"
    chapters = [{"title": "Chapter XML", "filepath": temp_chapter_file}]
    
    opds_manager.add_or_update_book(book_id, "XML Book", "XML Author", chapters)
    xml_data = opds_manager.build_opds_catalog()
    
    assert "XML Book" in xml_data
    assert "XML Author" in xml_data
    assert "1 глав в раздаче" in xml_data
    
    # Пытаемся распарсить как XML
    root = ET.fromstring(xml_data)
    
    # Проверяем, что есть тэг entry
    # (namespace учитываем через findall, или просто проверяем тег по имени)
    entries = [elem for elem in root.iter() if "entry" in elem.tag]
    assert len(entries) == 1


def test_opds_server_http_catalog(opds_manager, temp_chapter_file):
    """Запускает сервер на случайном порту и проверяет HTTP ответ каталога."""
    opds_manager.add_or_update_book("book_http", "HTTP Book", "HTTP Author", [{"title": "Ch1", "filepath": temp_chapter_file}])
    
    # Используем порт 0 для автоматического выбора свободного порта ОС
    opds_manager.start(host="127.0.0.1", port=0)
    
    # После запуска server_thread порт может быть известен через серверный сокет
    # Но так как наш OPDSManager хранит .port из настроек, а не фактический, 
    # мы должны забирать актуальный порт напрямую из сервера, если он был 0
    actual_port = opds_manager._server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/opds"
    
    try:
        response = urllib.request.urlopen(url, timeout=5)
        assert response.status == 200
        assert "application/atom+xml" in response.getheader("Content-Type")
        
        data = response.read().decode("utf-8")
        assert "HTTP Book" in data
    finally:
        opds_manager.stop()


def test_opds_server_http_download(opds_manager, temp_chapter_file):
    """Проверяет скачивание сгенерированного ePub через HTTP."""
    book_id = "test_download"
    opds_manager.add_or_update_book(book_id, "Download Book", "Download Author", [{"title": "Ch1", "filepath": temp_chapter_file}])
    
    opds_manager.start(host="127.0.0.1", port=0)
    actual_port = opds_manager._server.server_address[1]
    
    safe_id = urllib.parse.quote(book_id)
    url = f"http://127.0.0.1:{actual_port}/download.epub?book_id={safe_id}"
    
    try:
        response = urllib.request.urlopen(url, timeout=5)
        assert response.status == 200
        assert "application/epub+zip" in response.getheader("Content-Type")
        
        epub_data = response.read()
        assert len(epub_data) > 0
        
        # Проверяем, что это валидный ZIP (ePub)
        with zipfile.ZipFile(io.BytesIO(epub_data)) as zf:
            files = zf.namelist()
            assert "mimetype" in files
            assert "META-INF/container.xml" in files
            
            # Читаем mimetype
            mimetype_content = zf.read("mimetype").decode("utf-8")
            assert mimetype_content.strip() == "application/epub+zip"
    finally:
        opds_manager.stop()

def test_opds_server_not_found(opds_manager):
    """Проверка возврата 404 при неверном book_id."""
    opds_manager.start(host="127.0.0.1", port=0)
    actual_port = opds_manager._server.server_address[1]
    
    url = f"http://127.0.0.1:{actual_port}/download.epub?book_id=invalid_id"
    
    try:
        # urllib кидает HTTPError для 404
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url, timeout=5)
        
        assert exc_info.value.code == 404
    finally:
        opds_manager.stop()


def test_opds_path_normalization_and_uuid_preservation(opds_manager, temp_chapter_file):
    """
    Проверяет, что при передаче book_id с прямыми и обратными слешами
    не создается дубликат книги, а UUID сохраняется.
    """
    path_forward = "C:/Users/TestUser/Documents/My Book"
    path_backward = "C:\\Users\\TestUser\\Documents\\My Book"

    # Добавляем книгу по пути со слешами /
    chapters = [{"title": "Ch 1", "filepath": temp_chapter_file}]
    opds_manager.add_or_update_book(path_forward, "My Book", "Author", chapters)

    book1 = opds_manager.get_book(path_forward)
    assert book1 is not None
    orig_uuid = book1["uuid"]
    assert len(book1["chapters"]) == 1

    # Читаем по пути со слешами \
    book_lookup = opds_manager.get_book(path_backward)
    assert book_lookup is not None
    assert book_lookup["uuid"] == orig_uuid

    # Обновляем книгу, передав путь с \ и добавив вторую главу
    chapters2 = [
        {"title": "Ch 1", "filepath": temp_chapter_file},
        {"title": "Ch 2", "filepath": temp_chapter_file},
    ]
    opds_manager.add_or_update_book(path_backward, "My Book", "Author", chapters2)

    # Должна остаться ровно 1 книга, UUID не должен измениться
    assert len(opds_manager._books) == 1
    book2 = opds_manager.get_book(path_forward)
    assert book2 is not None
    assert book2["uuid"] == orig_uuid
    assert len(book2["chapters"]) == 2


def test_opds_load_state_deduplication(tmp_path, temp_chapter_file):
    """
    Проверяет, что при загрузке состояния из JSON дубликаты книг с разными
    слешами объединяются в одну книгу с сохранением глав и UUID.
    """
    import json
    from gemini_translator.server.opds_server import OPDSManager

    state_file = tmp_path / "test_dedup_opds.json"
    dummy_data = {
        "C:/Users/TestUser/Documents/Book1": {
            "title": "Book 1",
            "author": "Author",
            "uuid": "uuid-12345",
            "chapters": [{"title": "Ch 1", "filepath": temp_chapter_file}],
            "updated": "2026-09-20T10:00:00Z"
        },
        "C:\\Users\\TestUser\\Documents\\Book1": {
            "title": "Book 1",
            "author": "Author",
            "uuid": "uuid-67890",
            "chapters": [
                {"title": "Ch 1", "filepath": temp_chapter_file},
                {"title": "Ch 2", "filepath": temp_chapter_file}
            ],
            "updated": "2026-09-23T10:00:00Z"
        }
    }
    state_file.write_text(json.dumps(dummy_data, ensure_ascii=False, indent=2), encoding="utf-8")

    manager = OPDSManager()
    manager._state_file = str(state_file)
    manager._books = manager._load_state()

    # После дедупликации должна остаться ровно 1 книга
    assert len(manager._books) == 1
    book = next(iter(manager._books.values()))
    assert book["title"] == "Book 1"
    # Сохранен UUID первичной записи
    assert book["uuid"] == "uuid-12345"
    # Сохранены обе главы
    assert len(book["chapters"]) == 2


def test_opds_update_chapter_filepath(opds_manager, tmp_path):
    """
    Проверяет обновление пути к файлу главы при переименовании/валидации.
    """
    old_file = tmp_path / "ch1__translated.html"
    new_file = tmp_path / "ch1__validated.html"
    old_file.write_text("<p>old</p>", encoding="utf-8")
    new_file.write_text("<p>new</p>", encoding="utf-8")

    book_id = "test_project_rename"
    opds_manager.add_or_update_book(book_id, "Rename Book", "Author", [
        {"title": "Ch1", "filepath": str(old_file)}
    ])

    from gemini_translator.server.opds_server import normalize_filepath

    # Проверяем старый путь
    book = opds_manager.get_book(book_id)
    assert book["chapters"][0]["filepath"] == normalize_filepath(str(old_file))

    # Обновляем путь
    res = opds_manager.update_chapter_filepath(book_id, str(old_file), str(new_file))
    assert res is True

    # Проверяем, что путь обновился
    book_after = opds_manager.get_book(book_id)
    assert book_after["chapters"][0]["filepath"] == normalize_filepath(str(new_file))


def test_opds_build_epub_fallback_validated_file(opds_manager, tmp_path):
    """
    Проверяет, что build_epub_bytes подхватывает файл _validated.html,
    если исходный файл _translated.html был перемещен/переименован.
    """
    # Создаем сразу валидированный файл (старый файл "исчез")
    validated_file = tmp_path / "0001_ch1__validated.html"
    validated_file.write_text("<html><body><h1>Recovered Chapter</h1><p>Validated content.</p></body></html>", encoding="utf-8")

    # В OPDS регистрируем старый путь, которого нет на диске
    missing_file = tmp_path / "0001_ch1__translated_gemini.html"
    book_id = str(tmp_path)

    opds_manager.add_or_update_book(book_id, "Fallback Book", "Author", [
        {"title": "Ch1", "filepath": str(missing_file)}
    ])

    # Собираем ePub — должно подхватить validated_file без ошибок
    epub_bytes = opds_manager.build_epub_bytes(book_id)
    assert epub_bytes is not None
    assert len(epub_bytes) > 0

    # Проверяем, что файл ePub содержит текст из validated_file, а не заглушку об ошибке
    import zipfile
    import io
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        ch_content = None
        for name in zf.namelist():
            if (name.endswith(".xhtml") or name.endswith(".html")) and "nav" not in name:
                ch_content = zf.read(name).decode("utf-8")
                break
        assert ch_content is not None
        assert "Recovered Chapter" in ch_content
        assert "Ошибка чтения файла" not in ch_content

