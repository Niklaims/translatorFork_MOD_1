from __future__ import annotations

from dataclasses import dataclass

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from gemini_translator.ui import theme_manager


@dataclass(frozen=True)
class McpStatusSnapshot:
    running: bool
    detail: str = "stdio + local daemon"
    error: str | None = None
    connected_clients: int = 0


def _snapshot_from_status_payload(payload) -> McpStatusSnapshot:
    daemon = payload.get("daemon", {}) if isinstance(payload, dict) else {}
    host = daemon.get("host", "127.0.0.1")
    port = daemon.get("port", "")
    clients = payload.get("mcp_clients", {}) if isinstance(payload, dict) else {}
    try:
        connected_clients = int(clients.get("connected") or 0)
    except (TypeError, ValueError, OverflowError):
        connected_clients = 0
    return McpStatusSnapshot(
        running=True,
        detail=f"{host}:{port}",
        connected_clients=max(0, connected_clients),
    )


def _daemon_error_means_not_running(message: str) -> bool:
    text = str(message or "").lower()
    markers = (
        "daemon is not running",
        "connection refused",
        "connection reset",
        "connection aborted",
        "timed out",
        "timeout",
        "failed to establish",
        "actively refused",
        "errno 61",
        "errno 111",
        "winerror 10061",
        "urlopen error",
    )
    return any(marker in text for marker in markers)


class McpControlBackend:
    def status(self) -> McpStatusSnapshot:
        from gemini_translator.mcp.client import DaemonClientError, load_client

        try:
            payload = load_client().status()
        except DaemonClientError as exc:
            if _daemon_error_means_not_running(str(exc)):
                return McpStatusSnapshot(running=False, detail="stdio + local daemon")
            return McpStatusSnapshot(running=False, detail="stdio + local daemon", error=str(exc))
        return _snapshot_from_status_payload(payload)

    def start(self) -> McpStatusSnapshot:
        from gemini_translator.mcp.client import ensure_daemon_process

        client = ensure_daemon_process()
        payload = client.status()
        return _snapshot_from_status_payload(payload)

    def stop(self) -> McpStatusSnapshot:
        from gemini_translator.mcp.client import DaemonClientError, load_client

        try:
            load_client().shutdown()
        except DaemonClientError as exc:
            if _daemon_error_means_not_running(str(exc)):
                return McpStatusSnapshot(running=False, detail="stdio + local daemon")
            return McpStatusSnapshot(running=False, detail="stdio + local daemon", error=str(exc))
        return McpStatusSnapshot(running=False, detail="stdio + local daemon")

    def codex_config(self) -> str:
        from gemini_translator.mcp.client_install import build_config_snippet

        snippet = build_config_snippet("codex")
        return str(snippet.get("text", ""))


class McpActionWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)

    def __init__(self, backend: McpControlBackend, action: str, running: bool):
        super().__init__()
        self.backend = backend
        self.action = action
        self.running = running
        # Дублирует то, что уходит в finished.emit(): если результат нужен
        # синхронно (_wait_for_worker) после того, как воркер уже мог
        # self-удалиться, читать сигнал/эмит небезопасно, а этот атрибут —
        # обычное поле Python-объекта, установленное до эмита.
        self.last_snapshot: McpStatusSnapshot | None = None

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            if self.action == "status":
                snapshot = self.backend.status()
            elif self.action == "toggle" and self.running:
                snapshot = self.backend.stop()
            elif self.action == "toggle":
                snapshot = self.backend.start()
            else:
                snapshot = McpStatusSnapshot(running=False, detail="Неизвестное действие", error=str(self.action))
        except Exception as exc:
            snapshot = McpStatusSnapshot(running=False, detail="ошибка MCP", error=str(exc))
        self.last_snapshot = snapshot
        self.finished.emit(snapshot)


_ACTIVE_THREADS: set[QtCore.QThread] = set()
_ACTIVE_WORKERS: dict[QtCore.QThread, McpActionWorker] = {}


def _forget_mcp_worker(thread: QtCore.QThread) -> None:
    _ACTIVE_THREADS.discard(thread)
    _ACTIVE_WORKERS.pop(thread, None)


class McpControlWidget(QtWidgets.QFrame):
    status_changed = QtCore.pyqtSignal(object)

    def __init__(self, parent=None, *, backend=None):
        super().__init__(parent)
        self.backend = backend or McpControlBackend()
        self._running = False
        self._last_status = McpStatusSnapshot(running=False)
        self._auto_refresh_enabled = False
        self._stop_on_app_quit = False
        self._worker_thread = None
        self._worker = None
        self._worker_action = None
        self._worker_was_running = False
        self._pending_worker_result = None
        self._closing = False
        # Растёт при каждом новом _dispatch_action; позволяет отличить
        # доставку finished от воркера, которого мы уже принудительно
        # разобрали в _wait_for_worker, от актуальной (см. комментарии там
        # и в _on_worker_finished) — без обращения к самому C++-объекту
        # воркера, который к моменту доставки мог уже self-удалиться.
        self._worker_generation = 0
        self.setObjectName("mcpControlCard")
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Minimum)

        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setInterval(2500)
        self._status_timer.timeout.connect(self._poll_status)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(4)

        title_label = QLabel("MCP")
        title_label.setObjectName("keyStatusTitle")
        status_row.addWidget(title_label)

        self.status_value_label = QLabel("Выключен")
        self.status_value_label.setObjectName("keyStatusMetricValue")
        self.status_value_label.setMaximumWidth(78)
        status_row.addWidget(self.status_value_label)
        status_row.addStretch(1)
        text_col.addLayout(status_row)

        self.detail_label = QLabel("stdio + local daemon")
        self.detail_label.setObjectName("mutedLabel")
        self.detail_label.setMaximumWidth(112)
        text_col.addWidget(self.detail_label)
        layout.addLayout(text_col)

        self.action_button = QPushButton("Запустить")
        self.action_button.setObjectName("mcpActionButton")
        self.action_button.setFixedHeight(30)
        self.action_button.setFixedWidth(84)
        layout.addWidget(self.action_button)

        self.config_button = QPushButton("Codex config")
        self.config_button.setObjectName("mcpConfigButton")
        self.config_button.setFixedHeight(30)
        self.config_button.setFixedWidth(90)
        layout.addWidget(self.config_button)

        self.apply_status(McpStatusSnapshot(running=False))
        # Демон мог быть запущен до открытия GUI (или чужим клиентом) —
        # проверяем сразу, не дожидаясь первого тика таймера. Дочерний таймер,
        # а не QTimer.singleShot: он умирает вместе с виджетом и не дёргает
        # слот удалённого объекта.
        boot_probe = QtCore.QTimer(self)
        boot_probe.setSingleShot(True)
        boot_probe.timeout.connect(self._poll_status)
        boot_probe.start(0)
        self.action_button.clicked.connect(lambda: self._dispatch_action("toggle"))
        self.config_button.clicked.connect(self.copy_codex_config)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_app_about_to_quit)

    def sizeHint(self) -> QtCore.QSize:
        hint = super().sizeHint()
        return QtCore.QSize(min(hint.width(), 320), hint.height())

    def minimumSizeHint(self) -> QtCore.QSize:
        hint = super().minimumSizeHint()
        return QtCore.QSize(min(hint.width(), 300), hint.height())

    def apply_status(self, snapshot: McpStatusSnapshot) -> None:
        self._last_status = snapshot
        self._running = bool(snapshot.running) and not snapshot.error
        if snapshot.error:
            self.status_value_label.setText("Ошибка")
            self.setToolTip(snapshot.error)
        elif self._running:
            self.status_value_label.setText("Запущен")
            self.setToolTip("")
        else:
            self.status_value_label.setText("Выключен")
            self.setToolTip("")
        detail_text = snapshot.detail or "stdio + local daemon"
        if self._running and snapshot.connected_clients:
            client_label = "клиент" if snapshot.connected_clients == 1 else "клиентов"
            detail_text = f"{detail_text} · {client_label}: {snapshot.connected_clients}"
        self.detail_label.setText(detail_text)
        self.action_button.setText("Остановить" if self._running else "Запустить")
        self._apply_button_style()
        self._sync_status_timer()
        self.status_changed.emit(snapshot)

    def has_connected_client(self) -> bool:
        return self._running and self._last_status.connected_clients > 0

    def set_auto_refresh_enabled(self, enabled: bool) -> None:
        self._auto_refresh_enabled = bool(enabled)
        self._sync_status_timer()

    def _sync_status_timer(self) -> None:
        # Таймер работает и когда карточка считает демона выключенным:
        # демон автозапускается stdio-клиентами (claude/codex) через
        # ensure_daemon_process, и раньше карточка этого никогда не узнавала —
        # «не видит, что клиент подключился». Холостой тик дёшев: без
        # daemon-info файла HTTP-запрос не делается (только stat).
        should_run = self._auto_refresh_enabled and self._worker_thread is None
        if should_run and not self._status_timer.isActive():
            self._status_timer.start()
        elif not should_run and self._status_timer.isActive():
            self._status_timer.stop()

    def _daemon_info_present(self) -> bool:
        try:
            from ...mcp.paths import daemon_file
            return daemon_file(None).exists()
        except Exception:
            return False

    def _poll_status(self) -> None:
        if self._worker_thread is not None:
            return
        if self._running or self._daemon_info_present():
            self.refresh_status()

    def _update_stop_on_quit_policy(self, action: str, was_running: bool, snapshot: McpStatusSnapshot) -> None:
        if action != "toggle" or snapshot.error:
            return
        if not was_running and snapshot.running:
            self._stop_on_app_quit = True
        elif was_running and not snapshot.running:
            self._stop_on_app_quit = False

    def _dispatch_action(self, action: str) -> None:
        if self._worker_thread is not None:
            return
        self._closing = False
        if action != "status":
            self.action_button.setEnabled(False)
        thread = QtCore.QThread()
        worker = McpActionWorker(self.backend, action, self._running)
        worker.moveToThread(thread)
        self._worker_generation += 1
        generation = self._worker_generation
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(
            lambda snapshot, generation=generation: self._on_worker_finished_if_current(generation, snapshot)
        )
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda thread=thread: self._on_worker_thread_finished(thread))
        thread.finished.connect(thread.deleteLater)
        _ACTIVE_THREADS.add(thread)
        _ACTIVE_WORKERS[thread] = worker
        self._worker_thread = thread
        self._worker = worker
        self._worker_action = action
        self._worker_was_running = self._running
        self._pending_worker_result = None
        self._sync_status_timer()
        thread.start()

    def _on_worker_finished_if_current(self, generation: int, snapshot: McpStatusSnapshot) -> None:
        if generation != self._worker_generation:
            # Запоздалая доставка сигнала от воркера, которого
            # _wait_for_worker уже принудительно дождался и разобрал вручную
            # (см. комментарий там) — применять результат второй раз не
            # нужно, а сам объект воркера к этому моменту мог уже
            # self-удалиться, так что и обращаться к нему не нужно.
            return
        self._on_worker_finished(snapshot)

    def _on_worker_finished(self, snapshot: McpStatusSnapshot) -> None:
        thread = self._worker_thread
        action = self._worker_action
        was_running = self._worker_was_running
        self._pending_worker_result = (action, was_running, snapshot)
        self._worker = None
        if thread is not None:
            thread.quit()
            return
        self._finish_worker_action(None)

    def _on_worker_thread_finished(self, thread) -> None:
        if thread is not self._worker_thread:
            _forget_mcp_worker(thread)
            return
        self._finish_worker_action(thread)

    def _finish_worker_action(self, thread) -> None:
        # Воркер мог пережить виджет (deleteLater без closeEvent): трогать
        # C++-удалённые кнопки нельзя.
        try:
            from PyQt6 import sip
            if sip.isdeleted(self):
                _forget_mcp_worker(thread)
                return
        except ImportError:
            pass
        result = self._pending_worker_result
        self._worker_thread = None
        self._worker = None
        self._worker_action = None
        self._worker_was_running = False
        self._pending_worker_result = None
        if thread is not None:
            _forget_mcp_worker(thread)
        if result is not None and not self._closing:
            action, was_running, snapshot = result
            self.apply_status(snapshot)
            self._update_stop_on_quit_policy(action, was_running, snapshot)
        self.action_button.setEnabled(True)
        self._sync_status_timer()

    def _wait_for_worker(self) -> None:
        thread = self._worker_thread
        worker = self._worker
        if thread is None:
            return
        action = self._worker_action
        was_running = self._worker_was_running
        pending = self._pending_worker_result
        # Инвалидируем поколение ДО принудительного ожидания: если сигнал
        # finished воркера уже стоит в очереди главного потока (или встанет
        # туда, когда поток ниже реально остановится), _on_worker_finished
        # увидит несовпадение и не применит результат повторно — без нужды
        # трогать сам C++-объект воркера (disconnect на нём — источник
        # TOCTOU: воркер мог self-удалиться между проверкой и вызовом).
        self._worker_generation += 1
        if thread.isRunning():
            thread.quit()
            thread.wait()
        _forget_mcp_worker(thread)
        self._worker_thread = None
        self._worker = None
        self._worker_action = None
        self._worker_was_running = False
        self._pending_worker_result = None
        if action == "toggle":
            # thread.wait() выше гарантирует, что реальная работа воркера
            # (например, ensure_daemon_process — реальный запуск демона)
            # уже выполнена, но колбэк finished мог быть отключён (или
            # ещё не доставлен главному потоку) до того, как успел
            # применить _update_stop_on_quit_policy. Без этого демон,
            # поднятый прямо перед закрытием, остаётся сиротой: флаг «мы
            # его подняли — надо погасить» никогда не выставится.
            if pending is not None:
                _, _, snapshot = pending
            else:
                snapshot = None
                if worker is not None:
                    # Воркер сохраняет свой результат в last_snapshot до
                    # эмита — читаем его напрямую вместо лишнего
                    # синхронного backend.status(). Если C++-объект уже
                    # удалён (self-delete в своём потоке), чтение любого
                    # атрибута роняет RuntimeError — тихо уходим в запасной
                    # путь ниже, поведение не меняется.
                    try:
                        snapshot = worker.last_snapshot
                    except (RuntimeError, AttributeError):
                        snapshot = None
                if snapshot is None:
                    try:
                        snapshot = self.backend.status()
                    except Exception as exc:
                        snapshot = McpStatusSnapshot(running=False, detail="ошибка MCP", error=str(exc))
            # apply_status здесь эмитит status_changed независимо от
            # self._closing (в отличие от _finish_worker_action) — это
            # сознательно: нужен побочный эффект на _running/
            # _stop_on_app_quit ниже даже во время закрытия, чтобы демон,
            # поднятый прямо перед выходом, было чем погасить в
            # _on_app_about_to_quit. Расхождение с _finish_worker_action не
            # регрессия: старый _on_app_about_to_quit тоже звал apply_status
            # после backend.stop() при _closing=True.
            self.apply_status(snapshot)
            self._update_stop_on_quit_policy(action, was_running, snapshot)
        self.action_button.setEnabled(True)
        self._sync_status_timer()

    def _on_app_about_to_quit(self) -> None:
        # Дожидаемся и улаживаем (см. _wait_for_worker) именно ту гонку, ради
        # которой это ожидание добавлено: toggle запустил демон и почти
        # сразу пришёл aboutToQuit, ещё до того как _finish_worker_action
        # успел выставить _stop_on_app_quit. Действие "status" (фоновый
        # опрос, тикающий каждые 2.5с, пока карточка видима и есть
        # daemon-файл) к этой гонке отношения не имеет и ждать его не нужно:
        # thread.wait() без таймаута заблокировал бы выход приложения на
        # время сетевого backend.status() (до 5с) без всякой пользы.
        if self._worker_thread is not None and self._worker_action == "toggle":
            self._wait_for_worker()
        if not self._stop_on_app_quit:
            return
        if not self._running:
            self._stop_on_app_quit = False
            return
        try:
            snapshot = self.backend.stop()
        except Exception as exc:
            snapshot = McpStatusSnapshot(running=False, detail="ошибка остановки MCP", error=str(exc))
        self._stop_on_app_quit = False
        self.apply_status(snapshot)

    def closeEvent(self, event) -> None:
        self._closing = True
        self._status_timer.stop()
        self._on_app_about_to_quit()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            try:
                app.aboutToQuit.disconnect(self._on_app_about_to_quit)
            except TypeError:
                pass
        self._wait_for_worker()
        super().closeEvent(event)

    def refresh_status(self) -> None:
        """Запрашивает статус демона в фоновом потоке: синхронный HTTP-запрос
        (таймаут до 5 с) не должен замораживать GUI при переключении на MCP."""
        self._dispatch_action("status")

    def copy_codex_config(self) -> str:
        try:
            text = self.backend.codex_config()
        except Exception as exc:
            self.detail_label.setText("ошибка config")
            self.setToolTip(str(exc))
            self.status_value_label.setText("Запущен" if self._running else "Выключен")
            self.action_button.setText("Остановить" if self._running else "Запустить")
            self._apply_button_style()
            return ""
        QtWidgets.QApplication.clipboard().setText(text)
        self.config_button.setToolTip("Codex config скопирован")
        return text

    def _apply_button_style(self) -> None:
        color = theme_manager.color("danger") if self._running else theme_manager.color("success")
        self.action_button.setStyleSheet(
            "QPushButton { "
            f"background-color: {color}; "
            f"color: {theme_manager.color('accent_text')}; "
            "font-weight: bold; padding: 4px 6px; border-radius: 4px; "
            "}"
        )
