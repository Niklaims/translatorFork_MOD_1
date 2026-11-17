# -*- coding: utf-8 -*-
import sys
import os

# Автоматическое подтягивание библиотек из .venv, если программа запущена системным Python
_base_dir = os.path.dirname(os.path.abspath(__file__))
_venv_site = os.path.join(_base_dir, ".venv", "Lib", "site-packages")
if os.path.exists(_venv_site) and _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

import os_patch
import argparse
import traceback
import asyncio
import sqlite3
import atexit
import base64
import threading
import time
from collections import deque
from PyQt6 import QtWidgets, QtCore, QtGui, sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from gemini_translator.utils.glossary_tools import ContextManager
from gemini_translator.ui.dialogs.setup import InitialSetupDialog  # noqa: F401  (ре-экспорт для точки входа)
from gemini_translator.utils.settings import SettingsManager, configure_settings_scope
from gemini_translator.core.translation_engine import TranslationEngine
from gemini_translator.api import config as api_config
from gemini_translator.core.task_manager import ChapterQueueManager
from gemini_translator.utils.proxy_tool import GlobalProxyController
from gemini_translator.utils.server_manager import ServerManager
from gemini_translator.server.opds_server import OPDSManager
from gemini_translator.version import APP_VERSION
from window_branding import install_window_title_branding
from gemini_translator.ui.themes import (
    DARK_STYLESHEET,
)
from gemini_translator.ui import theme_manager

RESTART_INFO = {}

# Приложение собрано только вокруг переводчика EPUB.
TRANSLATOR_ONLY_DISABLED_PROVIDER_IDS = (
    "workascii_chatgpt",
    "web_chatgpt_free",
    "web_perplexity",
)

os.environ["GT_TRANSLATOR_ONLY_MODE"] = "1"
_disabled_ids = {
    item.strip()
    for item in os.environ.get("GT_DISABLED_PROVIDER_IDS", "").split(",")
    if item.strip()
}
_disabled_ids.update(TRANSLATOR_ONLY_DISABLED_PROVIDER_IDS)
os.environ["GT_DISABLED_PROVIDER_IDS"] = ",".join(sorted(_disabled_ids))

# ---------------------------------------------------------------------------
# Gemini EPUB Translator - Точка входа в приложение

# ---------------------------------------------------------------------------
# Этот файл отвечает за запуск приложения, обработку аргументов командной
# строки и выбор режима работы (автоматический, параллельный, гибридный).
# Вся основная логика, классы окон и утилиты импортируются из пакета
# 'gemini_translator'.
# ---------------------------------------------------------------------------


# --- БЛОК: АВАРИЙНЫЙ ПРОСМОТРЩИК ОШИБОК ---


def prepare_console_streams():
    """
    Делает stdout/stderr устойчивыми к символам, которых нет в текущей
    кодировке консоли.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass


def configure_settings_scope_from_argv(argv) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--settings-profile")
    group.add_argument("--settings-dir")
    parsed, remaining = parser.parse_known_args(list(argv[1:]))

    if parsed.settings_dir:
        configure_settings_scope(config_dir=parsed.settings_dir)
    elif parsed.settings_profile is not None:
        configure_settings_scope(profile=parsed.settings_profile)

    argv[:] = [argv[0], *remaining]


def apply_saved_app_theme(app, settings_manager=None):
    manager = settings_manager or getattr(app, "settings_manager", None)
    if manager is None:
        app.setStyleSheet(DARK_STYLESHEET)
        return
    mode = theme_manager.load_mode(manager)
    manual = theme_manager._manual_colors(manager)
    theme_manager.apply(app, mode=mode, manual_colors=manual)
    theme_manager.install(app, manager)
    # Liquid Glass needs a shown window for the macOS vibrancy backdrop, so —
    # if the user opted in — re-apply it once the UI is up, avoiding a
    # frost-less transparent flash at startup.
    if theme_manager.glass_enabled(manager):
        QtCore.QTimer.singleShot(
            900,
            lambda: theme_manager.apply(
                app,
                mode=theme_manager.load_mode(manager),
                manual_colors=theme_manager._manual_colors(manager),
                glass=True,
                glass_opacities=theme_manager.load_glass_opacities(manager),
            ),
        )


def run_emergency_viewer():
    """
    Запускает минималистичный, самодостаточный диалог для отображения
    критической ошибки, когда основное приложение не отвечает.
    """
    # Минимальная темная тема, чтобы окно не выглядело чужеродно
    FALLBACK_DARK_QSS = """
        QDialog, QWidget { background-color: #2c313c; color: #f0f0f0; }
        QTextEdit { background-color: #1e222a; border: 1px solid #4d5666; }
        QPushButton { background-color: #4d5666; border: none; padding: 8px; border-radius: 4px; }
        QPushButton:hover { background-color: #5a6475; }
    """

    app = QtWidgets.QApplication(sys.argv)
    install_window_title_branding(app)
    app.setStyleSheet(FALLBACK_DARK_QSS)

    error_text = "Тестовое сообщение об ошибке.\n\nАргументы командной строки не были предоставлены."
    # Ошибка передается как второй аргумент (первый -- --emergency-viewer)
    if len(sys.argv) > 2:
        try:
            encoded_message = sys.argv[2]
            decoded_bytes = base64.b64decode(encoded_message)
            error_text = decoded_bytes.decode('utf-8')
        except Exception as e:
            error_text = f"Не удалось декодировать сообщение об ошибке: {e}\n\nИсходные данные:\n{sys.argv[2]}"

    # Создаем диалог напрямую, без доп. классов
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("Аварийный Отчет об Ошибке")
    dialog.setMinimumSize(700, 500)

    layout = QtWidgets.QVBoxLayout(dialog)

    info_label = QtWidgets.QLabel(
        "Произошла критическая ошибка, которая привела к зависанию основного приложения.\n"
        "Это аварийное окно было запущено для отображения информации о сбое."
    )
    info_label.setWordWrap(True)
    info_label.setStyleSheet(
        "padding: 5px; background-color: #c0392b; color: white; border-radius: 4px;")
    layout.addWidget(info_label)

    details_view = QtWidgets.QTextEdit()
    details_view.setReadOnly(True)
    details_view.setFont(QtGui.QFont("Consolas", 10))
    details_view.setText(error_text)
    layout.addWidget(details_view)

    button_layout = QtWidgets.QHBoxLayout()
    copy_button = QtWidgets.QPushButton("Скопировать ошибку")

    # Общий хелпер (см. os_patch.attach_copy_feedback) — та же логика
    # используется в _patched_qmessagebox_critical.
    os_patch.attach_copy_feedback(copy_button, dialog, lambda: error_text)

    close_button = QtWidgets.QPushButton("Закрыть")
    close_button.clicked.connect(dialog.accept)

    button_layout.addWidget(copy_button)
    button_layout.addStretch()
    button_layout.addWidget(close_button)
    layout.addLayout(button_layout)

    dialog.exec()
    sys.exit(0)  # Завершаем аварийный процесс


class LoadingDialog(QtWidgets.QDialog):
    """Простой диалог-заставка, который показывается во время инициализации."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Убираем рамку окна, делаем его похожим на заставку
        self.setWindowFlags(Qt.WindowType.SplashScreen |
                            Qt.WindowType.FramelessWindowHint)
        self.setModal(True)  # Блокируем другие окна, пока это видимо

        layout = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel("Инициализация приложения…")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("font-size: 12pt; padding: 20px;")
        layout.addWidget(self.label)
        self.setFixedSize(300, 100)


# Сколько ждём подтверждения, что Qt event loop реально доставил
# critical_error_requested (QueuedConnection), прежде чем считать GUI
# зависшим. Сам факт успешного emit() на QueuedConnection ничего не
# доказывает — сигнал лишь ставится в очередь, независимо от того, крутится
# ли цикл событий (см. root-entry/bugs/2-excepthook-emit-not-liveness-c).
EXCEPTHOOK_LIVENESS_TIMEOUT_SEC = 5.0

# Single-flight guard: не даём каждому необработанному исключению плодить
# собственный watchdog-поток. PyQt вызывает sys.excepthook на КАЖДОЕ такое
# исключение — серия однотипных сбоев (например, падающий обработчик
# частого события) иначе породит десятки потоков одновременно, а главное:
# clear() от исключения B затирал бы подтверждение, которого ждёт watchdog
# исключения A (см. review round 2, major). Пока watchdog уже активен,
# новые исключения просто показываются пользователю без повторной проверки
# отзывчивости — активный watchdog и так эскалирует при реальном зависании.
_excepthook_watchdog_guard = threading.Lock()


def _escalate_to_emergency_shutdown(app, error_message: str):
    """Грациозно останавливает фоновые потоки и запускает аварийный просмотрщик.

    Вызывается, только когда GUI не отвечает (или отвечать нечему): либо
    сразу из global_excepthook (нет app/dispatcher, emit упал), либо из
    watchdog-потока, когда доставка critical_error_requested не была
    подтверждена за EXCEPTHOOK_LIVENESS_TIMEOUT_SEC.
    """
    print("[CRITICAL] Приложение Qt не отвечает. Попытка принудительной, но грациозной остановки...")
    if app and hasattr(app, 'engine') and hasattr(app, 'engine_thread'):
        try:
            # Отправляем команду на очистку в поток движка и ждем его завершения
            # с таймаутом, чтобы не зависнуть здесь навсегда.
            print("[CRITICAL] Отправка команды cleanup в движок...")
            app.engine.cancel_translation("Аварийное завершение по ошибке")

            # Ждем завершения потока движка (он должен сам себя остановить)
            if app.engine_thread.wait(5000):  # Ждем до 5 секунд
                print("[CRITICAL] Фоновые потоки успешно завершены.")
            else:
                print(
                    "[CRITICAL] Таймаут ожидания фоновых потоков. Возможны 'зомби'.")
        except Exception as e:
            print(
                f"[CRITICAL] Ошибка во время попытки грациозного завершения: {e}")

    # Сценарий 2: Запускаем "Спасательную шлюпку".
    print("[CRITICAL] Запуск аварийного просмотрщика ошибок...")
    try:
        import subprocess

        encoded_message = base64.b64encode(
            error_message.encode('utf-8')).decode('ascii')

        # Запускаем самих себя со специальным флагом.
        command = [sys.executable, sys.argv[0],
                   '--emergency-viewer', encoded_message]

        # --- ГЛАВНОЕ ИЗМЕНЕНИЕ ---
        # Запускаем дочерний процесс в "чистом" системном окружении,
        # чтобы он не наследовал пути к временной папке умирающего родителя.
        subprocess.Popen(command, env=os.environ.copy())
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---

    except Exception as e:
        print(
            f"[ULTRA-CRITICAL] Не удалось запустить аварийный просмотрщик: {e}")

    # Принудительно завершаем зависший процесс, как и раньше.
    os._exit(1)


def _watch_gui_liveness_and_escalate(app, liveness_event, error_message: str, guard):
    """Ждёт подтверждения, что GUI-поток обработал critical_error_requested.

    liveness_event выставляется ApplicationWithContext._show_critical_error
    в момент, когда Qt реально доставил QueuedConnection-сигнал — то есть
    событийный цикл провернулся. Если этого не произошло за отведённое
    время, GUI считается зависшим и запускается тот же путь, что и раньше
    использовался для "неотвечающего" приложения.

    guard — тот же threading.Lock, что был захвачен вызывающим кодом перед
    стартом этого потока (single-flight). Освобождаем его в любом исходе,
    чтобы следующее исключение снова могло проверить отзывчивость GUI.
    """
    try:
        if not liveness_event.wait(timeout=EXCEPTHOOK_LIVENESS_TIMEOUT_SEC):
            print(
                "[CRITICAL] Qt event loop не подтвердил обработку "
                f"critical_error_requested за {EXCEPTHOOK_LIVENESS_TIMEOUT_SEC:.0f} с "
                "— считаем GUI зависшим."
            )
            _escalate_to_emergency_shutdown(app, error_message)
    finally:
        guard.release()


def global_excepthook(exc_type, exc_value, exc_tb):
    """
    Обрабатывает все неперехваченные исключения.
    Если приложение отвечает, показывает встроенное окно.
    Если приложение зависло, пытается грациозно завершить фоновые потоки
    и только потом запускает аварийный режим.
    """
    tb_list = traceback.format_exception(exc_type, exc_value, exc_tb)
    tb_str = "".join(tb_list)
    error_message = (
        f"Произошла неперехваченная ошибка: {exc_type.__name__}\n\n"
        f"--- Полный Traceback ---\n{tb_str}"
    )
    print(f"КРИТИЧЕСКАЯ ОШИБКА (Unhandled Exception):\n{error_message}")

    app = QtWidgets.QApplication.instance()

    # Сценарий 1: Приложение "живо" и может показать окно само.
    if app:
        try:
            dispatcher = getattr(app, "critical_error_requested", None)
            if dispatcher and hasattr(dispatcher, "emit"):
                # emit() на QueuedConnection лишь кладёт сигнал в очередь и
                # не доказывает, что событийный цикл вообще жив. Если у
                # приложения есть счётчик подтверждения доставки (реальный
                # ApplicationWithContext), проверяем его в фоне и эскалируем
                # только при реальном зависании — не блокируя вызывающий
                # поток (это может быть тот же GUI-поток).
                liveness_event = getattr(app, "_critical_error_delivered", None)
                if liveness_event is not None and _excepthook_watchdog_guard.acquire(blocking=False):
                    # ВАЖНО: clear() обязан выполниться ДО emit(). При очень
                    # быстрой доставке (тот же тик событийного цикла)
                    # _show_critical_error может выставить событие раньше,
                    # чем управление вернётся сюда — если бы clear() шёл
                    # после emit(), он затёр бы уже полученное подтверждение
                    # и watchdog ошибочно эскалировал бы на живом приложении
                    # (см. review round 2, blocker).
                    liveness_event.clear()
                    dispatcher.emit(error_message)
                    watchdog = threading.Thread(
                        target=_watch_gui_liveness_and_escalate,
                        args=(app, liveness_event, error_message, _excepthook_watchdog_guard),
                        daemon=True,
                        name="excepthook-liveness-watchdog",
                    )
                    watchdog.start()
                else:
                    # Либо это не ApplicationWithContext (нет счётчика
                    # доставки — прежнее поведение: просто emit), либо
                    # watchdog уже активен для более раннего исключения —
                    # он и так эскалирует при реальном зависании GUI, второй
                    # проверки отзывчивости параллельно не требуется.
                    dispatcher.emit(error_message)
                return
        except Exception as e:
            print(
                f"[CRITICAL] Не удалось показать QMessageBox, даже при живом app: {e}")
            # Если даже QMessageBox падает, переходим к плану "Б".

    # Это выполняется, только если приложения нет или emit сразу упал.
    _escalate_to_emergency_shutdown(app, error_message)


def tab_wheel_guard_needed(style) -> bool:
    """Нужен ли фильтр, который не даёт колесу листать вкладки.

    Фильтр висит на всём приложении: Qt зовёт Python на каждое событие, и пока
    другой поток держит GIL, каждый вызов ждёт интерпретатор. Родной стиль
    macOS колесом вкладки не листает сам — там фильтр только тормозит.
    """
    hint = QtWidgets.QStyle.StyleHint.SH_TabBar_AllowWheelScrolling
    return bool(style.styleHint(hint))


class ApplicationWithContext(QtWidgets.QApplication):
    """
    Расширенный класс QApplication для управления активным контекстом настроек.
    """
    critical_error_requested = QtCore.pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._true_global_settings_manager = None
        self._active_settings_manager = None
        # Выставляется _show_critical_error в момент, когда QueuedConnection
        # реально доставлен — то есть событийный цикл провернулся. Это
        # единственное реальное доказательство отзывчивости GUI, которого
        # не даёт сам факт успешного emit() (см. global_excepthook).
        self._critical_error_delivered = threading.Event()
        self.critical_error_requested.connect(
            self._show_critical_error,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )
        if tab_wheel_guard_needed(self.style()):
            self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Wheel and isinstance(obj, QtWidgets.QTabBar):
            return True
        return super().eventFilter(obj, event)

    @QtCore.pyqtSlot(str)
    def _show_critical_error(self, error_message: str):
        # Сам факт вызова этого слота доказывает, что Qt доставил
        # QueuedConnection-сигнал, то есть событийный цикл жив.
        self._critical_error_delivered.set()

        def show_and_quit():
            QtWidgets.QMessageBox.critical(
                None, "Критическая Ошибка Приложения", error_message
            )
            QtCore.QTimer.singleShot(0, self.quit)

        QtCore.QTimer.singleShot(100, show_and_quit)

    def initialize_managers(self):
        """Инициализирует менеджеры после создания основного объекта."""
        self._true_global_settings_manager = SettingsManager(
            event_bus=self.event_bus)
        # По умолчанию активный менеджер - это глобальный
        self._active_settings_manager = self._true_global_settings_manager

    def get_settings_manager(self) -> SettingsManager:
        """
        ЕДИНСТВЕННЫЙ правильный способ получить текущий менеджер настроек.
        Все виджеты должны использовать этот метод.
        """
        return self._active_settings_manager

    def get_server_manager(self):
        """Возвращает менеджер сервера Perplexity."""
        return self.server_manager


class _KeysSnapshotDict(dict):
    """dict, чей .keys() всегда возвращает неизменяемый снимок под общим lock.

    EventBus._data_store мутируется из разных потоков через set_data/pop_data
    (см. EventBus.set_data/pop_data/get_data) под self._lock, но несколько
    мест в ядре (worker.py, task_manager.py, translation_engine.py) итерируют
    `bus._data_store.keys()` напрямую, без блокировки. Обычный dict.keys()
    — это "живое" view: конкурентная мутация словаря во время такой итерации
    бросает RuntimeError('dictionary changed size during iteration').
    Переопределяя здесь .keys() (метод, который сегодня действительно
    вызывает внешний код), делаем эти места безопасными, не трогая сами
    внешние файлы: результат — статический tuple-снимок ключей, взятый
    атомарно под тем же lock, что и set_data/pop_data. По той же схеме
    защищены .items() и .values(), и .copy() (все три — на случай будущего
    кода, который вместо .keys() возьмёт одно из них).

    __iter__ НАМЕРЕННО не переопределён (в отличие от предложения ревью) —
    это не упущение. dict.copy()/dict(x) для аргумента-подкласса dict берут
    в CPython быстрый путь (прямой клон внутренней хэш-таблицы, атомарно,
    без единого Python-вызова) только пока `type(x).__iter__` совпадает с
    базовым dict.__iter__; стоит переопределить __iter__ — и dict.copy()/
    dict(x) переключаются на общий protocol для мэппингов: сначала
    `x.keys()`, затем `x[key]` по одному. Для .copy() это гарантированный
    deadlock (тот же self._snapshot_lock захватывается повторно изнутри
    keys(), а Lock не рекурсивный — проверено на практике при первой
    попытке добавить __iter__); для стороннего `dict(x)` — это как раз
    открывает ту самую гонку: keys() под локом успевает вернуть безопасный
    снимок, а вот `x[key]` для каждого ключа уже НЕ под локом и может
    словить KeyError, если ключ выпилили между этими двумя шагами. Поэтому
    `for k in bus._data_store` / `list(bus._data_store)` остаются
    незащищёнными (как и раньше) — но, как отмечено в ревью, реальные
    внешние вызовы (worker.py, task_manager.py, translation_engine.py)
    используют только .keys(), так что описанный failure_scenario этим не
    затронут.
    """

    def __init__(self, lock):
        super().__init__()
        self._snapshot_lock = lock

    def keys(self):
        with self._snapshot_lock:
            return tuple(dict.keys(self))

    def items(self):
        with self._snapshot_lock:
            return tuple(dict.items(self))

    def values(self):
        with self._snapshot_lock:
            return tuple(dict.values(self))

    def copy(self):
        with self._snapshot_lock:
            # dict.copy(self) — метод базового класса: пока __iter__ не
            # переопределён, CPython клонирует внутреннюю таблицу напрямую,
            # не вызывая ни keys(), ни __getitem__ — реентерантности в наш
            # же self._snapshot_lock не возникает.
            return dict.copy(self)


class EventBus(QtCore.QObject):
    import threading
    event_posted = QtCore.pyqtSignal(dict)
    data_changed = QtCore.pyqtSignal(str)
    _queued_log_events_ready = QtCore.pyqtSignal()
    _lock = threading.Lock()
    _data_store = _KeysSnapshotDict(_lock)

    # Worker pools can produce log messages much faster than the GUI event loop
    # can consume individual queued Qt signals.  Keep that traffic bounded and
    # drain it in frame-sized chunks so input and paint events always get a turn.
    LOG_EVENT_BATCH_SIZE = 100
    LOG_EVENT_DRAIN_INTERVAL_MS = 16
    MAX_PENDING_LOG_EVENTS = 5000

    def __init__(self):
        super().__init__()
        self._topic_subscribers = {}
        self._topic_lock = self.threading.Lock()
        # Счётчик повторных сбоев одного и того же подписчика на одном и том
        # же событии — чтобы не заваливать GUI-поток полными traceback'ами
        # на каждый вызов, если подписчик падает стабильно на частом событии
        # (см. EventBus._log_topic_subscriber_error).
        self._topic_error_counts = {}
        self._pending_log_events = deque()
        self._pending_log_lock = self.threading.Lock()
        self._log_drain_scheduled = False
        self._dropped_log_events = 0
        self.event_posted.connect(self._dispatch_to_topics)
        self._queued_log_events_ready.connect(
            self._drain_pending_log_events,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )

    def subscribe(self, event_name: str, callback):
        """Подписывает callback только на конкретный тип события."""
        self._subscribe_impl(event_name, callback)

    def _subscribe_impl(self, event_name: str, callback):
        with self._topic_lock:
            subscribers = self._topic_subscribers.setdefault(event_name, [])
            if any(item == callback for item in subscribers):
                return
            subscribers.append(callback)

    def unsubscribe(self, event_name: str, callback):
        """Убирает callback из конкретной topic-подписки."""
        self._unsubscribe_impl(event_name, callback)

    def _unsubscribe_impl(self, event_name: str, callback):
        with self._topic_lock:
            subscribers = self._topic_subscribers.get(event_name)
            if not subscribers:
                return
            if callback in subscribers:
                subscribers.remove(callback)
            if not subscribers:
                self._topic_subscribers.pop(event_name, None)

    def unsubscribe_all(self, callback):
        """Убирает callback из всех topic-подписок."""
        self._unsubscribe_all_impl(callback)

    def _unsubscribe_all_impl(self, callback):
        with self._topic_lock:
            empty_topics = []
            for event_name, subscribers in self._topic_subscribers.items():
                if callback in subscribers:
                    subscribers.remove(callback)
                if not subscribers:
                    empty_topics.append(event_name)
            for event_name in empty_topics:
                self._topic_subscribers.pop(event_name, None)

    def _dispatch_to_topics(self, event: dict):
        event_name = event.get('event') if isinstance(event, dict) else None
        if not event_name:
            return
        with self._topic_lock:
            entries = list(self._topic_subscribers.get(event_name, []))
        dead_callbacks = None
        for callback in entries:
            # Topic-подписки не чистятся Qt автоматически: bound-методы
            # уничтоженных виджетов (deleteLater при pop страницы/закрытии
            # диалога) остаются в словаре навсегда и держат обёртки живыми.
            if self._is_dead_subscriber(callback):
                if dead_callbacks is None:
                    dead_callbacks = []
                dead_callbacks.append(callback)
                continue
            try:
                self._dispatch_callback(callback, event)
            except Exception as exc:
                # Раньше сбой подписчика исчезал бесследно (bare except: pass),
                # что маскировало реальные проблемы синхронизации UI/очереди
                # (см. историю: "Тупик qa_pending", "Глава-зомби ЧАНК 1/1").
                # Перехват оставляем — иначе PyQt6 роняет процесс через qFatal
                # прямо из слота event_posted, — но теперь пишем след в лог.
                self._log_topic_subscriber_error(event_name, callback, exc)
        if dead_callbacks:
            for callback in dead_callbacks:
                self._unsubscribe_all_impl(callback)

    def _log_topic_subscriber_error(self, event_name: str, callback, exc: Exception):
        """Пишет след сбоя подписчика в консоль/лог с троттлингом.

        Первый сбой конкретного (событие, подписчик, тип исключения) —
        полный traceback. Дальнейшие повторы того же сбоя — короткая строка
        со счётчиком, без traceback: иначе стабильно падающий подписчик на
        частом событии (лог/прогресс главы — сотни событий в минуту) залил
        бы главный поток потоком одинаковых полных трейсбеков.
        """
        receiver = getattr(callback, "__self__", None)
        callback_desc = (
            f"{type(receiver).__name__}.{getattr(callback, '__name__', callback)}"
            if receiver is not None
            else repr(callback)
        )
        error_key = (event_name, callback_desc, type(exc).__name__)
        with self._topic_lock:
            count = self._topic_error_counts.get(error_key, 0) + 1
            self._topic_error_counts[error_key] = count
        if count == 1:
            print(
                f"[EventBus-TOPIC-ERROR] Подписчик {callback_desc} на "
                f"'{event_name}' упал: {type(exc).__name__}: {exc}"
            )
            traceback.print_exc()
        else:
            print(
                f"[EventBus-TOPIC-ERROR] Подписчик {callback_desc} на "
                f"'{event_name}' падает повторно ({count}-й раз подряд с "
                f"начала сессии): {type(exc).__name__}: {exc}"
            )

    @staticmethod
    def _is_dead_subscriber(callback) -> bool:
        receiver = getattr(callback, "__self__", None)
        if not isinstance(receiver, QtCore.QObject):
            return False
        try:
            return sip.isdeleted(receiver)
        except Exception:
            return False

    def _dispatch_callback(self, callback, event: dict):
        receiver = getattr(callback, "__self__", None)
        method_name = getattr(callback, "__name__", "")
        if (
            isinstance(receiver, QtCore.QObject)
            and method_name
            and receiver.thread() is not QtCore.QThread.currentThread()
        ):
            try:
                QtCore.QMetaObject.invokeMethod(
                    receiver,
                    method_name,
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(dict, event),
                )
                return
            except (RuntimeError, TypeError):
                pass

        callback(event)

    STOP_EVENTS = frozenset({'manual_stop_requested', 'stop_session_requested'})

    def emit_event(self, event: dict):
        """Совместимый способ отправки: topics + старый event_posted сигнал."""
        if isinstance(event, dict) and event.get('event') == 'log_message':
            self._stamp_log_event(event)
            if QtCore.QThread.currentThread() is not self.thread():
                self._queue_log_event(event)
                return
        if isinstance(event, dict) and event.get('event') in self.STOP_EVENTS:
            self._cancel_inflight_mcp_requests()
        self.event_posted.emit(event)

    @staticmethod
    def _cancel_inflight_mcp_requests():
        """Снимает висящие MCP-запросы сразу, не дожидаясь движка.

        Заявку, которую не забрал ни один AI-агент, движок отменить не успеет:
        он сам может ждать её результата, и тогда «стоп» не будет обработан.
        Отмена уходит в фоновый поток, поэтому событие не задерживается.
        """
        try:
            from gemini_translator.mcp import inflight
            inflight.cancel_all()
        except Exception as exc:
            print(f"[EventBus WARN] Не удалось снять висящие MCP-запросы: {exc}")

    @staticmethod
    def _stamp_log_event(event: dict):
        """Отметить лог временем события, а не временем его отрисовки.

        Строки из воркеров ждут своей очереди и в шине, и в самом виджете
        (скрытая вкладка вообще ничего не рисует). Без метки, поставленной
        здесь, пользователь увидит время возвращения на экран лога.
        """
        data = event.get('data')
        if isinstance(data, dict):
            data.setdefault('timestamp', time.time())

    def _queue_log_event(self, event: dict):
        """Queue a worker log without adding one Qt event per log line."""
        should_schedule = False
        with self._pending_log_lock:
            if len(self._pending_log_events) >= self.MAX_PENDING_LOG_EVENTS:
                self._pending_log_events.popleft()
                self._dropped_log_events += 1
            self._pending_log_events.append(event)
            if not self._log_drain_scheduled:
                self._log_drain_scheduled = True
                should_schedule = True

        if should_schedule:
            self._queued_log_events_ready.emit()

    @QtCore.pyqtSlot()
    def _drain_pending_log_events(self):
        """Deliver one bounded log batch, then yield back to Qt's event loop."""
        batch = []
        dropped_count = 0
        has_more = False
        with self._pending_log_lock:
            dropped_count = self._dropped_log_events
            self._dropped_log_events = 0
            while self._pending_log_events and len(batch) < self.LOG_EVENT_BATCH_SIZE:
                batch.append(self._pending_log_events.popleft())
            has_more = bool(self._pending_log_events)
            if not has_more:
                self._log_drain_scheduled = False

        if dropped_count:
            self.event_posted.emit({
                'event': 'log_message',
                'source': 'EventBus',
                'data': {
                    'message': (
                        f'[WARN] Пропущено {dropped_count} сообщений лога: '
                        'интерфейс не успевал обрабатывать поток событий.'
                    ),
                    'timestamp': time.time(),
                },
            })

        for pending_event in batch:
            self.event_posted.emit(pending_event)

        if has_more:
            QtCore.QTimer.singleShot(
                self.LOG_EVENT_DRAIN_INTERVAL_MS,
                self._drain_pending_log_events,
            )

    def set_data(self, key: str, value):
        """Потокобезопасно сохраняет данные и испускает сигнал."""
        with self._lock:
            self._data_store[key] = value
        self.data_changed.emit(key)

    def pop_data(self, key: str, default=None):
        """Потокобезопасно извлекает (и удаляет) данные."""
        with self._lock:
            return self._data_store.pop(key, default)

    def get_data(self, key: str, default=None):
        """Потокобезопасно читает данные, не удаляя их."""
        with self._lock:
            return self._data_store.get(key, default)

    def has_managed_session_active(self, prefix: str = "managed_session_active_") -> bool:
        """Есть ли хоть один ключ с данным префиксом и значением True.

        Централизует предикат «активна ли управляемая сессия», который
        раньше был вручную скопирован в ChapterQueueManager.is_finished и
        ChapterQueueManager.has_pending_tasks (task_manager.py), а также в
        TranslationEngine.is_managed_mode/_end_session (translation_engine.py,
        эти два места не переведены на этот метод — вне области правки).
        Не берём self._lock напрямую: .keys() у _data_store уже сам
        атомарен под тем же локом (см. _KeysSnapshotDict), а повторный
        захват self._lock здесь был бы deadlock'ом (Lock нерекурсивный).
        """
        for key in self._data_store.keys():
            if key.startswith(prefix) and self.get_data(key) is True:
                return True
        return False

    def clear_managed_session_flags(self, prefix: str = "managed_session_active_") -> int:
        """Снимает все флаги управляемой сессии (парный мутатор к
        has_managed_session_active), возвращает число удалённых ключей.

        Раньше TranslationEngine._end_session сканировал _data_store по тому
        же литералу префикса сам; теперь литерал живёт только здесь.
        Снимок ключей берём до удаления, чтобы не менять словарь во время
        итерации; сам pop_data — под общим локом.
        """
        removed = 0
        for key in [k for k in self._data_store.keys() if k.startswith(prefix)]:
            self.pop_data(key, None)
            removed += 1
        return removed


def initialize_global_resources(app: QApplication):
    """
    Создает ПУСТЫЕ глобальные ресурсы (БД, диск) и "вешает" их на QApplication.
    Не создает никаких таблиц!
    """
    print("--- Инициализация глобальных ресурсов... ---")
    try:
        # 1. Создаем и удерживаем "якорное" подключение к пустой БД
        # WAL (Write-Ahead Logging) позволяет нескольким потокам читать,
        # пока один поток пишет, что предотвращает deadlock'и.
        main_db_conn = sqlite3.connect(
            api_config.SHARED_DB_URI, uri=True, check_same_thread=False)
        main_db_conn.row_factory = sqlite3.Row

        # --- Включаем WAL на главном соединении ---
        main_db_conn.execute("PRAGMA journal_mode=WAL;")
        # Ждать до 5 секунд
        main_db_conn.execute("PRAGMA busy_timeout = 5000;")

        atexit.register(lambda: main_db_conn.close())
        app.main_db_connection = main_db_conn
        print("--- Общая in-memory база данных активна и удерживается. ---")

    except Exception as e:
        raise RuntimeError(
            f"КРИТИЧЕСКАЯ ОШИБКА при инициализации глобальных ресурсов: {e}")


def bootstrap_application(argv):
    """Инициализация QApplication и основных сервисов переводчика.

    Регистрация главного потока, Qt-локализация, Fusion-стиль на Windows,
    фикс дублирования Dock-иконки на macOS, глобальные ресурсы, менеджеры и
    TranslationEngine в фоновом потоке. Возвращает готовый к показу окна `app`.

    jieba больше не греется на старте безусловно (~18МБ у всех сессий):
    словарь строится при первом CJK-вызове в воркере (незаметно на фоне
    сетевых секунд) либо фоновым прогревом при открытии окна глоссария.
    """
    import threading

    prepare_console_streams()
    configure_settings_scope_from_argv(argv)
    sys.excepthook = global_excepthook
    # --- РЕГИСТРАЦИЯ ГЛАВНОГО ПОТОКА ---
    main_id = threading.get_ident()
    print(f"\n[SYSTEM] MAIN UI THREAD ID: {main_id}\n")
    # Регистрируем его как VIP
    os_patch.PatientLock.register_vip_thread(main_id)

    app = ApplicationWithContext(argv)

    # Health-подтверждение апдейтера в этой сборке не требуется: автообновление
    # запускается не из переводчика, поэтому ack-файл не пишем.

    # --- ЛОКАЛИЗАЦИЯ СТАНДАРТНЫХ ЭЛЕМЕНТОВ QT ---
    # Загружаем русскую локализацию для контекстных меню (ПКМ) и диалогов Qt (QMessageBox, QInputDialog и т.д.)
    from PyQt6.QtCore import QTranslator, QLibraryInfo

    # Локализация базовых компонентов (кнопки, меню)
    qtbase_translator = QTranslator(app)
    qt_translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if qtbase_translator.load("qtbase_ru", qt_translations_path):
        app.installTranslator(qtbase_translator)

    # Локализация остальных компонентов
    qt_translator = QTranslator(app)
    if qt_translator.load("qt_ru", qt_translations_path):
        app.installTranslator(qt_translator)

    # Фикс дублирования иконки в Dock на macOS
    if sys.platform == "darwin":
        app.setDesktopFileName("com.siberianteam.translatorfork")

    # На Windows базовый стиль (windowsvista/windows11) рисует часть
    # элементов нативно, мимо QSS-движка — скругления темы получают
    # пиксельные «лесенки» и артефакты. Fusion рендерит всё растровым
    # QSS-путём со сглаживанием, как на macOS.
    if sys.platform == "win32":
        app.setStyle("Fusion")

    install_window_title_branding(app)
    # Тема (светлая/тёмная/авто) применяется в apply_saved_app_theme ниже,
    # как только доступен settings_manager — без раннего тёмного дефолта,
    # чтобы пользователи светлой/авто-темы не видели тёмной вспышки.

    # Инициализация ресурсов (один раз при старте процесса)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    initialize_global_resources(app)

    # [ARCH] Активация виртуальной файловой системы.
    # С этого момента функции open(), os.path.* и zipfile умеют работать с путями 'mem://'.
    os_patch.apply()
    api_config.initialize_configs()

    print("[INFO] Инициализация основных сервисов приложения…")

    app.event_bus = EventBus()
    app.initialize_managers()
    app.settings_manager = app.get_settings_manager()
    apply_saved_app_theme(app, app.settings_manager)
    app.task_manager = ChapterQueueManager(event_bus=app.event_bus)
    app.global_version = APP_VERSION
    app.proxy_controller = GlobalProxyController(app.event_bus)
    proxy_settings = app.settings_manager.load_proxy_settings()
    app.proxy_controller.apply_settings(proxy_settings)

    temp_folder = os.path.join(
        os.path.expanduser("~"), ".epub_translator_temp")
    os.makedirs(temp_folder, exist_ok=True)
    app.context_manager = ContextManager(temp_folder)
    app.server_manager = ServerManager(app.event_bus)
    app.opds_manager = OPDSManager()
    print("[INFO] Инициализация TranslationEngine…")

    app.engine = TranslationEngine(task_manager=app.task_manager)
    app.engine_thread = QtCore.QThread(app)
    app.engine.moveToThread(app.engine_thread)

    # Убираем автоматическую остановку потока по aboutToQuit,
    # чтобы движок переживал перезагрузку интерфейса (код 2000).
    # Ручная остановка выполняется вызывающей стороной при завершении.

    app.engine_thread.finished.connect(app.engine.deleteLater)

    app.engine_thread.start()

    print("[OK] TranslationEngine запущен в фоновом потоке.")
    QtCore.QMetaObject.invokeMethod(
        app.engine,
        "log_thread_identity",
        QtCore.Qt.ConnectionType.QueuedConnection
    )

    return app


# ============================================================================
# ОСНОВНАЯ ТОЧКА ВХОДА
# ============================================================================
if len(sys.argv) > 1 and sys.argv[1] == '--emergency-viewer':
    run_emergency_viewer()

# Специальный код возврата для перезагрузки приложения (возврат в меню)
EXIT_CODE_REBOOT = 2000

def run_translator_app():
    """Единственный режим приложения — переводчик EPUB.

    Окно настройки сессии перевода открывается напрямую, без главного меню
    и без остальных инструментов.
    """
    app = bootstrap_application(sys.argv)

    try:
        while True:
            main_window_to_run = None
            loading_dialog = LoadingDialog()

            try:
                main_window_to_run = InitialSetupDialog()
            except Exception as error:
                if loading_dialog.isVisible():
                    loading_dialog.close()

                tb_str = "".join(
                    traceback.format_exception(type(error), error, error.__traceback__)
                )
                error_message = (
                    f"Произошла критическая ошибка при инициализации переводчика: "
                    f"{type(error).__name__}\n\n--- Полный Traceback ---\n{tb_str}"
                )
                print(f"[CRITICAL STARTUP ERROR]\n{error_message}")
                QtWidgets.QMessageBox.critical(
                    None, "Ошибка запуска", error_message
                )
                main_window_to_run = None

            if main_window_to_run:
                main_window_to_run.show()
                exit_code = app.exec()
                if exit_code != EXIT_CODE_REBOOT:
                    break
            else:
                break
    finally:
        print("[INFO] Приложение переводчика завершает работу.")
        if hasattr(app, "opds_manager") and app.opds_manager.is_running():
            app.opds_manager.stop()
        if hasattr(app, "proxy_controller"):
            app.proxy_controller.shutdown()
        if hasattr(app, "engine_thread") and app.engine_thread.isRunning():
            if hasattr(app, "engine"):
                try:
                    QtCore.QMetaObject.invokeMethod(
                        app.engine,
                        "cleanup",
                        QtCore.Qt.ConnectionType.BlockingQueuedConnection,
                    )
                except Exception:
                    pass
            app.engine_thread.quit()
            app.engine_thread.wait()

    return 0


if __name__ == "__main__":
    sys.exit(run_translator_app())
