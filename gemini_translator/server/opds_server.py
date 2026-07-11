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
        self._lock = threading.Lock()

        # Словарь раздаваемых книг
        # Формат: { book_id: {"title": str, "author": str, "uuid": str, "chapters": list, "updated": str} }
        self._books: dict = {}

        # Сервер
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None

        # Настройки (значения по умолчанию)
        self.host: str = DEFAULT_HOST
        self.port: int = DEFAULT_PORT

        # Галочка «автоматическая загрузка готовых глав»
        self.auto_publish: bool = False

    # ─── Управление списком глав ────────────────────────────────────────
    def add_or_update_book(self, book_id: str, title: str, author: str, chapters: list[dict]):
        """Добавляет новую книгу или обновляет существующую."""
        with self._lock:
            book_uuid = self._books.get(book_id, {}).get("uuid", str(uuid.uuid4()))
            self._books[book_id] = {
                "title": title,
                "author": author,
                "uuid": book_uuid,
                "chapters": list(chapters),
                "updated": _utc_now_iso()
            }

    def get_book(self, book_id: str) -> dict | None:
        """Возвращает информацию о конкретной книге."""
        with self._lock:
            return self._books.get(book_id)

    def remove_book(self, book_id: str):
        """Удаляет книгу из раздачи."""
        with self._lock:
            self._books.pop(book_id, None)

    def clear_all_books(self):
        """Очищает список всех раздаваемых книг."""
        with self._lock:
            self._books.clear()

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
        """Возвращает URL сервера для подключения."""
        display_host = self.host if self.host != "0.0.0.0" else "127.0.0.1"
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
        if not book or not book["chapters"]:
            return None

        creator = EpubCreator(
            title=book["title"],
            author=book["author"],
            language="ru",
        )

        for i, chapter_info in enumerate(book["chapters"]):
            filepath = chapter_info.get("filepath", "")
            title = chapter_info.get("title", f"Глава {i + 1}")

            # Безопасное имя файла внутри ePub
            safe_name = re.sub(r'[^\w\-.]', '_', os.path.basename(filepath))
            if not safe_name.lower().endswith(('.html', '.xhtml', '.htm')):
                safe_name += ".xhtml"

            # Читаем содержимое главы
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"[OPDS] Не удалось прочитать главу «{filepath}»: {e}")
                content = f"<html><body><h1>{_xml_escape(title)}</h1><p>Ошибка чтения файла.</p></body></html>"

            creator.add_chapter(safe_name, content, title)

        # Собираем ePub в память (BytesIO)
        buf = io.BytesIO()
        creator.create_epub(buf)
        return buf.getvalue()


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
            # Безопасное имя файла для заголовка Content-Disposition
            safe_title = re.sub(r'[^\w\s\-]', '', book_title).strip()
            if not safe_title:
                safe_title = "book"
            filename = f"{safe_title}.epub"

            self.send_response(200)
            self.send_header("Content-Type", EPUB_MIME)
            self.send_header("Content-Length", str(len(epub_data)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
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
