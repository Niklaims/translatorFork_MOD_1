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
