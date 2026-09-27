# -*- coding: utf-8 -*-
"""
OPDS-сервер для раздачи переведённых глав на читалки (iOS/Android).

Архитектура:
- OPDSManager: управляет состоянием раздачи (список глав, метаданные книги),
  потокобезопасно запускает и останавливает HTTP-сервер.
- OPDSRequestHandler: обрабатывает HTTP-запросы — отдаёт OPDS-каталог (Atom XML)
  и динамически собирает ePub из разрешённых глав.
- EpubCreator (из epub_tools) используется для сборки ePub на лету.

Сервер использует stdlib http.server.ThreadingHTTPServer — без внешних зависимостей.
"""

import io
import os
import re
import html as html_lib
import threading
import uuid
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
import json
import socket

# Для динамической сборки ePub
from ..utils.epub_tools import EpubCreator


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
OPDS_MIME = "application/atom+xml;profile=opds-catalog;kind=acquisition; charset=utf-8"
EPUB_MIME = "application/epub+zip"


# ---------------------------------------------------------------------------
# Утилиты нормализации путей
# ---------------------------------------------------------------------------
def normalize_book_id(book_id: str) -> str:
    r"""
    Приводит ID книги (путь к папке проекта) к единому каноническому виду:
    - Абсолютный путь
    - Нормализованные разделители ОС
    - Верхний регистр буквы диска на Windows (C:\ вместо c:\)
    """
    if not book_id:
        return ""
    try:
        norm = os.path.abspath(os.path.normpath(str(book_id).strip()))
        drive, rest = os.path.splitdrive(norm)
        if drive:
            norm = drive.upper() + rest
        return norm
    except Exception:
        return os.path.normpath(str(book_id).strip())


def normalize_filepath(filepath: str) -> str:
    """Приводит путь к файлу главы к нормализованному абсолютному виду."""
    if not filepath:
        return ""
    try:
        norm = os.path.abspath(os.path.normpath(str(filepath).strip()))
        drive, rest = os.path.splitdrive(norm)
        if drive:
            norm = drive.upper() + rest
        return norm
    except Exception:
        return os.path.normpath(str(filepath).strip())


# ---------------------------------------------------------------------------
# Утилиты XML
# ---------------------------------------------------------------------------
def _xml_escape(value: str) -> str:
    """Экранирует строку для безопасной вставки в XML."""
    return html_lib.escape(str(value or ""), quote=True)


def _utc_now_iso() -> str:
    """Возвращает текущее время в ISO-8601 UTC (нужно для Atom updated)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# OPDSManager — ядро раздачи
# ---------------------------------------------------------------------------
class OPDSManager:
    """
    Потокобезопасный менеджер OPDS-сервера.

    Хранит:
    - Список глав, разрешённых к раздаче (пары: заголовок, путь_к_файлу).
    - Метаданные книги (title, author).
    - Параметры сети (host, port).

    Умеет:
    - Запускать/останавливать фоновый ThreadingHTTPServer.
    - Отдавать OPDS XML каталог.
    - Собирать ePub на лету из разрешённых глав.
    """

    def __init__(self):
        self._lock = threading.RLock()

        # Файл для сохранения состояния OPDS
        self._state_file = os.path.join(os.path.expanduser("~"), ".gemini_translator_opds.json")

        # Словарь раздаваемых книг
        # Формат: { canonical_book_id: {"title": str, "author": str, "uuid": str, "chapters": list, "updated": str} }
        self._books: dict = self._load_state()

        # Сервер
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None

        # Настройки (значения по умолчанию)
        self.host: str = DEFAULT_HOST
        self.port: int = DEFAULT_PORT

        # Галочка «автоматическая загрузка готовых глав»
        self.auto_publish: bool = False

    # ─── Сохранение и загрузка состояния ────────────────────────────────
    def _load_state(self) -> dict:
        loaded = {}
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
        except Exception as e:
            print(f"[OPDS] Ошибка загрузки состояния: {e}")
            return {}

        if not isinstance(loaded, dict):
            return {}

        # Дедупликация и миграция ключей к каноническому виду
        cleaned = {}
        dirty = False

        for raw_id, book_data in loaded.items():
            if not isinstance(book_data, dict):
                continue
            canonical_id = normalize_book_id(raw_id)
            if raw_id != canonical_id:
                dirty = True

            # Нормализуем пути глав
            norm_chapters = []
            for ch in book_data.get("chapters", []):
                if isinstance(ch, dict):
                    fp = ch.get("filepath", "")
                    nfp = normalize_filepath(fp)
                    if fp != nfp:
                        dirty = True
                    norm_chapters.append({
                        "title": ch.get("title", ""),
                        "filepath": nfp
                    })

            if canonical_id in cleaned:
                # Уже есть книга с таким нормализованным ID (дубликат из-за разных слешей!)
                dirty = True
                existing = cleaned[canonical_id]
                # Сохраняем первичный UUID
                chosen_uuid = existing.get("uuid") or book_data.get("uuid") or str(uuid.uuid4())

                # Объединяем главы (если в одном из дубликатов больше глав, берем более полный набор)
                if len(norm_chapters) >= len(existing.get("chapters", [])):
                    chosen_chapters = norm_chapters
                    chosen_title = book_data.get("title") or existing.get("title", "")
                    chosen_author = book_data.get("author") or existing.get("author", "")
                else:
                    chosen_chapters = existing.get("chapters", [])
                    chosen_title = existing.get("title") or book_data.get("title", "")
                    chosen_author = existing.get("author") or book_data.get("author", "")

                cleaned[canonical_id] = {
                    "title": chosen_title,
                    "author": chosen_author,
                    "uuid": chosen_uuid,
                    "chapters": chosen_chapters,
                    "updated": max(existing.get("updated", ""), book_data.get("updated", ""), _utc_now_iso())
                }
            else:
                cleaned[canonical_id] = {
                    "title": book_data.get("title", "Unknown Book"),
                    "author": book_data.get("author", "Unknown Author"),
                    "uuid": book_data.get("uuid") or str(uuid.uuid4()),
                    "chapters": norm_chapters,
                    "updated": book_data.get("updated", _utc_now_iso())
                }

        # Если была миграция или дедупликация, сохраняем очищенный файл
        if dirty:
            try:
                with open(self._state_file, 'w', encoding='utf-8') as f:
                    json.dump(cleaned, f, ensure_ascii=False, indent=2)
                print(f"[OPDS] Выполнена дедупликация и миграция состояния ({len(loaded)} -> {len(cleaned)} книг)")
            except Exception as e:
                print(f"[OPDS] Не удалось сохранить очищенное состояние: {e}")

        return cleaned

    def _save_state(self):
        try:
            with open(self._state_file, 'w', encoding='utf-8') as f:
                json.dump(self._books, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[OPDS] Ошибка сохранения состояния: {e}")

    # ─── Управление списком глав ────────────────────────────────────────
    def add_or_update_book(self, book_id: str, title: str, author: str, chapters: list[dict]):
        """Добавляет новую книгу или обновляет существующую с сохранением UUID."""
        canonical_id = normalize_book_id(book_id)
        with self._lock:
            # Ищем существующую книгу: по каноническому ID, либо по совпадению нормализованных путей,
            # либо по title, если папка указывает на ту же директорию
            existing_key = None
            book_uuid = None
            for k, b in self._books.items():
                if normalize_book_id(k) == canonical_id:
                    existing_key = k
                    book_uuid = b.get("uuid")
                    break

            if not book_uuid:
                # Проверим совпадение по title и директории
                for k, b in self._books.items():
                    if b.get("title") == title:
                        try:
                            if os.path.exists(k) and os.path.exists(canonical_id) and os.path.samefile(k, canonical_id):
                                existing_key = k
                                book_uuid = b.get("uuid")
                                break
                        except Exception:
                            pass

            if not book_uuid:
                book_uuid = str(uuid.uuid4())

            # Удаляем старый ключ, если он отличался по написанию (например со слешами /)
            if existing_key and existing_key != canonical_id:
                self._books.pop(existing_key, None)

            # Нормализуем пути глав
            norm_chapters = []
            for ch in chapters:
                norm_chapters.append({
                    "title": ch.get("title", ""),
                    "filepath": normalize_filepath(ch.get("filepath", ""))
                })

            self._books[canonical_id] = {
                "title": title,
                "author": author,
                "uuid": book_uuid,
                "chapters": norm_chapters,
                "updated": _utc_now_iso()
            }
            self._save_state()

    def _get_book_unlocked(self, canonical_id: str) -> dict | None:
        """Внутренний поиск книги без повторного захвата блокировки."""
        if canonical_id in self._books:
            return self._books[canonical_id]
        for k, b in self._books.items():
            if normalize_book_id(k) == canonical_id:
                return b
        return None

    def get_book(self, book_id: str) -> dict | None:
        """Возвращает информацию о конкретной книге по ID."""
        canonical_id = normalize_book_id(book_id)
        with self._lock:
            return self._get_book_unlocked(canonical_id)

    def update_chapter_filepath(self, book_id: str, old_filepath: str, new_filepath: str) -> bool:
        """
        Обновляет путь к файлу главы при переименовании/валидации.
        Возвращает True, если путь был найден и обновлён.
        """
        if not old_filepath or not new_filepath:
            return False
        old_norm = normalize_filepath(old_filepath)
        new_norm = normalize_filepath(new_filepath)
        if old_norm == new_norm:
            return False

        canonical_id = normalize_book_id(book_id)
        with self._lock:
            book = self._get_book_unlocked(canonical_id)
            if not book:
                return False
            updated = False
            for ch in book.get("chapters", []):
                if normalize_filepath(ch.get("filepath", "")) == old_norm:
                    ch["filepath"] = new_norm
                    updated = True
            if updated:
                book["updated"] = _utc_now_iso()
                self._save_state()
            return updated

    def update_chapter_filepaths(self, book_id: str, path_mapping: dict[str, str]) -> int:
        """
        Пакетное обновление путей к файлам глав (old_path -> new_path).
        Возвращает количество обновлённых глав.
        """
        if not path_mapping:
            return 0
        norm_map = {}
        for old_p, new_p in path_mapping.items():
            on = normalize_filepath(old_p)
            nn = normalize_filepath(new_p)
            if on and nn and on != nn:
                norm_map[on] = nn

        if not norm_map:
            return 0

        canonical_id = normalize_book_id(book_id)
        with self._lock:
            book = self._get_book_unlocked(canonical_id)
            if not book:
                return 0
            count = 0
            for ch in book.get("chapters", []):
                cur_norm = normalize_filepath(ch.get("filepath", ""))
                if cur_norm in norm_map:
                    ch["filepath"] = norm_map[cur_norm]
                    count += 1
            if count > 0:
                book["updated"] = _utc_now_iso()
                self._save_state()
            return count

    def remove_book(self, book_id: str):
        """Удаляет книгу из раздачи."""
        canonical_id = normalize_book_id(book_id)
        with self._lock:
            keys_to_remove = [k for k in self._books if normalize_book_id(k) == canonical_id]
            for k in keys_to_remove:
                self._books.pop(k, None)
            if keys_to_remove:
                self._save_state()

    def clear_all_books(self):
        """Очищает список всех раздаваемых книг."""
        with self._lock:
            self._books.clear()
            self._save_state()

    def chapter_count(self) -> int:
        """Общее количество глав во всех раздаваемых книгах."""
        with self._lock:
            return sum(len(b["chapters"]) for b in self._books.values())



    # ─── Управление сервером ────────────────────────────────────────────
    def start(self, host: str | None = None, port: int | None = None) -> str:
        """
        Запускает OPDS-сервер в фоновом потоке.
        Возвращает URL для подключения.
        """
        if self.is_running():
            self.stop()

        if host is not None:
            self.host = host
        if port is not None:
            self.port = port

        # partial передаёт ссылку на менеджер в обработчик
        handler = partial(OPDSRequestHandler, opds_manager=self)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.daemon_threads = True

        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="OPDS-Server",
            daemon=True,
        )
        self._server_thread.start()

        url = self.get_url()
        print(f"[OPDS] Сервер запущен: {url}")
        return url

    def stop(self):
        """Грациозно останавливает OPDS-сервер."""
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception as e:
                print(f"[OPDS] Ошибка при остановке сервера: {e}")
            finally:
                self._server = None
                self._server_thread = None
            print("[OPDS] Сервер остановлен.")

    def is_running(self) -> bool:
        """Проверяет, запущен ли сервер."""
        return self._server is not None and self._server_thread is not None and self._server_thread.is_alive()

    def get_url(self) -> str:
        """Возвращает URL каталога."""
        if self.host == "0.0.0.0":
            # Пытаемся автоматически определить локальный IP-адрес ПК в Wi-Fi сети
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(('8.8.8.8', 80))
                display_host = s.getsockname()[0]
                s.close()
            except Exception:
                display_host = "127.0.0.1" # Фолбэк, если сети нет
        else:
            display_host = self.host
            
        return f"http://{display_host}:{self.port}/opds"

    # ─── Генерация OPDS-каталога (Atom XML) ─────────────────────────────
    def build_opds_catalog(self) -> str:
        """
        Генерирует OPDS Acquisition Feed (Atom XML).
        Описывает все книги, добавленные в раздачу.
        """
        now = _utc_now_iso()

        entries = []
        with self._lock:
            books_copy = dict(self._books)

        import urllib.parse
        for book_id, book in books_copy.items():
            b_title = _xml_escape(book["title"])
            b_author = _xml_escape(book["author"])
            b_uuid = _xml_escape(book["uuid"])
            b_updated = book.get("updated", now)
            ch_count = len(book["chapters"])
            summary = f"{ch_count} глав в раздаче" if ch_count else "Нет глав"
            
            # В URL передаем book_id. Делаем путь ОТНОСИТЕЛЬНЫМ (/download.epub), 
            # чтобы читалка сама подставила нужный IP (Wi-Fi или локальный).
            safe_id = urllib.parse.quote(book_id)
            download_url = f"/download.epub?book_id={safe_id}"

            entry = f"""
  <entry>
    <title>{b_title}</title>
    <id>urn:uuid:{b_uuid}</id>
    <updated>{b_updated}</updated>
    <author><name>{b_author}</name></author>
    <summary>{_xml_escape(summary)}</summary>
    <dc:language>ru</dc:language>
    <link rel="http://opds-spec.org/acquisition"
          href="{_xml_escape(download_url)}"
          type="{EPUB_MIME}"/>
  </entry>"""
            entries.append(entry)

        entries_str = "".join(entries)

        catalog = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:dc="http://purl.org/dc/terms/"
      xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>urn:uuid:opds-main-catalog</id>
  <title>OPDS — Мои Переводы</title>
  <updated>{now}</updated>
  <author><name>Gemini EPUB Translator</name></author>

  <link rel="self"
        href="/opds"
        type="{OPDS_MIME}"/>
  <link rel="start"
        href="/opds"
        type="{OPDS_MIME}"/>
{entries_str}
</feed>"""
        return catalog

    # ─── Динамическая сборка ePub ───────────────────────────────────────
    def build_epub_bytes(self, book_id: str) -> bytes | None:
        """
        Собирает ePub «на лету» из текущих глав конкретной раздачи.
        Возвращает байтовое содержимое ePub-файла или None, если глав нет.
        """
        book = self.get_book(book_id)
        if not book or not book.get("chapters"):
            return None

        creator = EpubCreator(
            title=book["title"],
            author=book["author"],
            language="ru",
        )

        state_modified = False

        for i, chapter_info in enumerate(book["chapters"]):
            filepath = chapter_info.get("filepath", "")
            title = chapter_info.get("title", f"Глава {i + 1}")

            # Безопасное имя файла внутри ePub
            safe_name = re.sub(r'[^\w\-.]', '_', os.path.basename(filepath))
            if not safe_name.lower().endswith(('.html', '.xhtml', '.htm')):
                safe_name += ".xhtml"

            actual_path = filepath
            # Если файл не существует по указанному пути, ищем валидированную версию или fallback
            if not os.path.exists(actual_path):
                recovered = self._find_fallback_chapter_file(filepath)
                if recovered and os.path.exists(recovered):
                    actual_path = recovered
                    chapter_info["filepath"] = normalize_filepath(recovered)
                    state_modified = True

            # Читаем содержимое главы
            try:
                with open(actual_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"[OPDS] Не удалось прочитать главу «{actual_path}»: {e}")
                content = f"<html><body><h1>{_xml_escape(title)}</h1><p>Ошибка чтения файла.</p></body></html>"

            creator.add_chapter(safe_name, content, title)

        if state_modified:
            with self._lock:
                self._save_state()

        # Собираем ePub в память (BytesIO)
        buf = io.BytesIO()
        creator.create_epub(buf)
        return buf.getvalue()

    @staticmethod
    def _find_fallback_chapter_file(filepath: str) -> str | None:
        """
        Если исходный файл главы был перемещён/переименован (например, в _validated.html),
        пытается найти актуальный файл главы в той же директории.
        """
        if not filepath:
            return None
        folder = os.path.dirname(filepath)
        if not os.path.isdir(folder):
            return None

        fname = os.path.basename(filepath)
        stem = fname.split("__")[0] if "__" in fname else fname.split("_")[0]
        if not stem:
            return None

        try:
            candidates = []
            for item in os.listdir(folder):
                if item.startswith(stem) and item.lower().endswith(('.html', '.xhtml', '.htm')):
                    full_p = os.path.join(folder, item)
                    is_val = "_validated" in item
                    candidates.append((is_val, full_p))
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                return candidates[0][1]
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# HTTP-обработчик OPDS-запросов
# ---------------------------------------------------------------------------
class OPDSRequestHandler(BaseHTTPRequestHandler):
    """
    Обрабатывает HTTP GET:
      /opds            → OPDS Atom каталог (XML)
      /download.epub   → динамически собранный ePub
      /                → перенаправление на /opds
    """

    def __init__(self, *args, opds_manager: OPDSManager, **kwargs):
        self.opds_manager = opds_manager
        super().__init__(*args, **kwargs)

    # Подавляем логи в stderr — сервер работает в фоне
    def log_message(self, format, *args):
        print(f"[OPDS HTTP] {format % args}")

    def do_GET(self):  # noqa: N802
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("", "/"):
            # Перенаправление корня на /opds
            self.send_response(301)
            self.send_header("Location", "/opds")
            self.end_headers()
            return

        if path == "/opds":
            self._serve_opds_catalog()
            return

        if path == "/download.epub":
            book_id = query.get("book_id", [None])[0]
            self._serve_epub_download(book_id)
            return

        # 404 для остального
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("404 — Страница не найдена.".encode("utf-8"))

    def _serve_opds_catalog(self):
        """Отдаёт OPDS-каталог в формате Atom XML."""
        try:
            xml = self.opds_manager.build_opds_catalog()
            data = xml.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", OPDS_MIME)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_error(500, f"Ошибка генерации каталога: {e}")

    def _serve_epub_download(self, book_id: str | None):
        """Собирает ePub на лету и отдаёт как HTTP-ответ."""
        if not book_id:
            self._send_error(400, "Не указан идентификатор книги (book_id).")
            return

        try:
            epub_data = self.opds_manager.build_epub_bytes(book_id)
            if epub_data is None:
                self._send_error(404, "Книга не найдена или в ней нет глав для скачивания.")
                return

            book = self.opds_manager.get_book(book_id)
            book_title = book["title"] if book else "book"
            
            import urllib.parse
            # Строгие HTTP-клиенты (Node.js/Electron) падают, если в заголовке есть кириллица.
            # Формируем ASCII версию для старых клиентов и UTF-8 для современных (RFC 5987)
            ascii_title = re.sub(r'[^\x00-\x7F]', '', book_title).strip()
            ascii_title = re.sub(r'[^\w\s\-]', '', ascii_title).strip()
            if not ascii_title:
                ascii_title = "book"
                
            encoded_title = urllib.parse.quote(book_title.encode('utf-8'))

            self.send_response(200)
            self.send_header("Content-Type", EPUB_MIME)
            self.send_header("Content-Length", str(len(epub_data)))
            self.send_header("Content-Disposition", f"attachment; filename=\"{ascii_title}.epub\"; filename*=UTF-8''{encoded_title}.epub")
            self.end_headers()
            self.wfile.write(epub_data)
        except ConnectionAbortedError:
            print("[OPDS HTTP] Клиент прервал соединение при скачивании (это нормально для некоторых читалок).")
        except BrokenPipeError:
            print("[OPDS HTTP] Обрыв связи с клиентом (BrokenPipe).")
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self._send_error(500, f"Ошибка сборки ePub: {e}")
            except Exception:
                pass # Если заголовки уже отправлены, _send_error выдаст ошибку, игнорируем ее

    def _send_error(self, code: int, message: str):
        """Отправляет текстовое сообщение об ошибке."""
        data = message.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
