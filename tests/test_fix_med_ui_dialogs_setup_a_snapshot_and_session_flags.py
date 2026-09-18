"""
Регресс для находок группы ui_dialogs_setup_a (gemini_translator/ui/dialogs/setup.py):

- ui-dialogs-setup/runtime/4-final-queue-snapshot-dropped-a: принудительный
  (force=True) финальный снимок очереди терялся, если в момент завершения
  сессии уже шло фоновое автосохранение — is_session_active к этому моменту
  уже False, и старое условие в _on_snapshot_autosave_finished не
  перезапускало сохранение.
- ui-dialogs-setup/logic/5-snapshot-restore-rebuild-wipes: восстановленный
  снимок очереди мог быть немедленно затёрт пересборкой задач через
  settings_changed от translation_options_widget, случайно пришедший во
  время _restore_queue_snapshot.
- ui-dialogs-setup/logic/4-stale-is-session-active-after-: is_session_active
  мог быть ложно взведён синхронизацией с чужой (дочерней) сессией и никогда
  не сбрасывался, если её session_finished был проигнорирован из-за
  is_blocked_by_child_dialog.
"""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gemini_translator.ui.dialogs.setup import InitialSetupPage


def _bare_page():
    """Голый экземпляр InitialSetupPage без __init__ — минимальный харнесс
    для вызова боевых методов, как в остальных test_dedup_* тестах."""
    return InitialSetupPage.__new__(InitialSetupPage)


# ---------------------------------------------------------------------------
# ui-dialogs-setup/runtime/4-final-queue-snapshot-dropped-a
# ---------------------------------------------------------------------------

def test_finalize_forced_snapshot_is_not_dropped_when_autosave_worker_busy():
    """Финальный force-снимок, пришедший, пока воркер автосохранения ещё
    работает, должен быть переигран сразу после его завершения — даже если
    is_session_active уже сброшен в False (как делает _finalize_session_state
    перед вызовом _save_snapshot_async(force=True))."""
    page = _bare_page()
    page._is_queue_autosave_enabled = lambda: True
    page.selected_file = "book.epub"
    page._get_snapshot_path = lambda: "/tmp/queue_snapshot.db"
    page.engine = SimpleNamespace(task_manager=SimpleNamespace())
    page._snapshot_save_requested = False
    page._snapshot_force_save_pending = False
    page._snapshot_restore_in_progress = False
    page._snapshot_autosave_worker = SimpleNamespace(isRunning=lambda: True, result=None)
    page.is_session_active = True  # сессия ещё формально идёт в момент запроса

    # Пока фоновый воркер занят, приходит финальный force-запрос.
    page._save_snapshot_async(force=True)
    assert page._snapshot_save_requested is True
    assert page._snapshot_force_save_pending is True

    # Сессия завершается раньше, чем воркер освобождается (реальный порядок
    # в _finalize_session_state: is_session_active=False выставляется до
    # вызова _save_snapshot_async).
    page.is_session_active = False

    # Воркер освобождается — приходит сигнал finished.
    page._snapshot_autosave_worker = SimpleNamespace(isRunning=lambda: False, result=True)
    page._snapshot_save_timer = SimpleNamespace(start=MagicMock())
    page._write_snapshot_ui_settings = lambda *a, **k: None
    page._get_full_ui_settings = lambda: {}
    spy = MagicMock()
    page._save_snapshot_async = spy

    page._on_snapshot_autosave_finished()

    # РЕГРЕСС: до фикса ни _save_snapshot_async, ни таймер не
    # перезапускались, потому что условие требовало is_session_active ==
    # True — финальный снимок молча терялся, на диске оставалась более
    # старая версия очереди.
    spy.assert_called_once_with(force=True)
    assert page._snapshot_force_save_pending is False


def test_non_forced_pending_save_still_uses_delayed_timer_when_session_active():
    """Характеризация: обычный (не force) отложенный запрос, накопленный
    во время работы воркера, по-прежнему уходит через 15-секундный таймер,
    если сессия ещё активна — новая ветка force-flush не должна его
    перехватывать."""
    page = _bare_page()
    page._is_queue_autosave_enabled = lambda: True
    page.is_session_active = True
    page._snapshot_save_requested = True
    page._snapshot_force_save_pending = False
    page._snapshot_autosave_worker = SimpleNamespace(isRunning=lambda: False, result=True)
    page._write_snapshot_ui_settings = lambda *a, **k: None
    page._get_full_ui_settings = lambda: {}
    page._get_snapshot_path = lambda: "/tmp/queue_snapshot.db"
    timer = SimpleNamespace(start=MagicMock())
    page._snapshot_save_timer = timer
    spy = MagicMock()
    page._save_snapshot_async = spy

    page._on_snapshot_autosave_finished()

    timer.start.assert_called_once()
    spy.assert_not_called()


# ---------------------------------------------------------------------------
# ui-dialogs-setup/logic/5-snapshot-restore-rebuild-wipes
# ---------------------------------------------------------------------------

def test_translation_options_changed_skips_rebuild_during_snapshot_restore():
    """settings_changed, случайно пришедший от translation_options_widget
    во время восстановления снимка очереди (например, из-за автоматического
    снятия batch_checkbox при len(html_files) <= 1), не должен пересобирать
    задачи — иначе только что восстановленные статусы и история ошибок
    стираются свежими pending-задачами."""
    page = _bare_page()
    page._snapshot_restore_in_progress = True
    page.is_session_active = False
    page.selected_file = "book.epub"
    page.html_files = ["chapter1.xhtml"]
    page.task_manager = SimpleNamespace()
    page._refresh_auto_translate_runtime_context = lambda: None
    page._mark_settings_as_dirty = lambda: None
    page._prepare_and_display_tasks = MagicMock()

    page._on_translation_options_changed()

    page._prepare_and_display_tasks.assert_not_called()


def test_translation_options_changed_rebuilds_normally_outside_restore():
    """Характеризация: вне восстановления снимка обычная пересборка очереди
    по settings_changed по-прежнему срабатывает (новое условие не должно
    перекрывать штатный путь)."""
    page = _bare_page()
    page._snapshot_restore_in_progress = False
    page.is_session_active = False
    page.selected_file = "book.epub"
    page.html_files = ["chapter1.xhtml"]
    page.task_manager = SimpleNamespace()
    page._refresh_auto_translate_runtime_context = lambda: None
    page._mark_settings_as_dirty = lambda: None
    page._prepare_and_display_tasks = MagicMock()

    page._on_translation_options_changed()

    page._prepare_and_display_tasks.assert_called_once_with(clean_rebuild=True)


# ---------------------------------------------------------------------------
# ui-dialogs-setup/logic/4-stale-is-session-active-after-
# ---------------------------------------------------------------------------

def test_check_and_sync_active_session_resets_stale_flag_when_no_session():
    """is_session_active, ложно взведённый ЭТИМ ЖЕ методом по синхронизации
    с чужой (дочерней) сессией (_session_active_forced_by_sync=True), чей
    session_finished был проигнорирован из-за is_blocked_by_child_dialog,
    должен сбрасываться, как только шина сообщает, что активной сессии
    больше нет — иначе флаг застревает навсегда и блокирует
    check_ready/_mark_settings_as_dirty и т.п."""
    page = _bare_page()
    page.bus = SimpleNamespace(get_data=lambda key: None)
    page.engine = SimpleNamespace(session_id=None, task_manager=None)
    page.is_session_active = True  # застрял True от предыдущей ложной синхронизации
    page._session_active_forced_by_sync = True  # взведён именно этим методом
    page._set_controls_enabled = MagicMock()
    page.status_bar = SimpleNamespace(start_session=MagicMock(), stop_session=MagicMock())

    result = page._check_and_sync_active_session()

    # РЕГРЕСС: до фикса метод только включал контролы, но не сбрасывал флаг —
    # is_session_active оставался True навсегда.
    assert result is False
    assert page.is_session_active is False
    assert page._session_active_forced_by_sync is False
    page.status_bar.stop_session.assert_called_once()
    page._set_controls_enabled.assert_called_once_with(True)


def test_check_and_sync_active_session_noop_when_already_inactive():
    """Характеризация: когда флаг и так False, лишних вызовов
    status_bar.stop_session быть не должно (не создаём лишний UI-шум на
    каждый check_ready)."""
    page = _bare_page()
    page.bus = SimpleNamespace(get_data=lambda key: None)
    page.engine = SimpleNamespace(session_id=None, task_manager=None)
    page.is_session_active = False
    page._set_controls_enabled = MagicMock()
    page.status_bar = SimpleNamespace(start_session=MagicMock(), stop_session=MagicMock())

    result = page._check_and_sync_active_session()

    assert result is False
    assert page.is_session_active is False
    page.status_bar.stop_session.assert_not_called()


def test_check_and_sync_active_session_does_not_reset_flag_set_by_normal_session_started():
    """РЕГРЕСС ревью (minor #3): в штатном окне завершения сессии движок уже
    снял current_active_session из шины, а _finalize_session_state (который
    сам сбросит is_session_active и вызовет stop_session) ещё не доставлен
    через QueuedConnection. is_session_active в этот момент True, но взведён
    обычным событием 'session_started' (_session_active_forced_by_sync=False),
    а не синхронизацией с чужой сессией — метод не должен вмешиваться и
    досрочно дублировать stop_session/enable-controls."""
    page = _bare_page()
    page.bus = SimpleNamespace(get_data=lambda key: None)
    page.engine = SimpleNamespace(session_id=None, task_manager=None)
    page.is_session_active = True
    page._session_active_forced_by_sync = False  # взведён обычным session_started
    page._set_controls_enabled = MagicMock()
    page.status_bar = SimpleNamespace(start_session=MagicMock(), stop_session=MagicMock())

    result = page._check_and_sync_active_session()

    assert result is False
    # is_session_active остаётся True — сброс сделает штатный
    # _finalize_session_state, а не эта функция.
    assert page.is_session_active is True
    page.status_bar.stop_session.assert_not_called()
    page._set_controls_enabled.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# Регресс замечаний ревью 2026-09-13 (major/minor по группе ui_dialogs_setup_a)
# ---------------------------------------------------------------------------

def test_translation_options_changed_does_not_latch_rebuild_flag_during_restore():
    """MAJOR: ранний return по _snapshot_restore_in_progress должен стоять
    ДО `self._task_queue_needs_rebuild = True` — иначе флаг защёлкивается
    здесь же и следующее нажатие «Старт» (_ensure_pending_tasks_for_start)
    всё равно вызовет деструктивный clean_rebuild, стерев восстановленные
    статусы/историю ошибок отложенно."""
    page = _bare_page()
    page._snapshot_restore_in_progress = True
    page._task_queue_needs_rebuild = False
    page.is_session_active = False
    page.selected_file = "book.epub"
    page.html_files = ["chapter1.xhtml"]
    page.task_manager = SimpleNamespace()
    page._refresh_auto_translate_runtime_context = lambda: None
    page._mark_settings_as_dirty = lambda: None
    page._prepare_and_display_tasks = MagicMock()

    page._on_translation_options_changed()

    page._prepare_and_display_tasks.assert_not_called()
    # РЕГРЕСС: до фикса флаг здесь взводился в True, несмотря на пропущенную
    # немедленную пересборку.
    assert page._task_queue_needs_rebuild is False


def test_ensure_pending_tasks_for_start_does_not_rebuild_after_snapshot_restore():
    """MAJOR (сквозной): settings_changed, случайно пришедший во время
    восстановления снимка, не должен приводить к деструктивному
    clean_rebuild при последующем нажатии «Старт» — весь путь
    _on_translation_options_changed → _ensure_pending_tasks_for_start."""
    page = _bare_page()
    page._snapshot_restore_in_progress = True
    page._task_queue_needs_rebuild = False
    page.is_session_active = False
    page.selected_file = "book.epub"
    page.html_files = ["chapter1.xhtml"]
    page.task_manager = SimpleNamespace()
    page._refresh_auto_translate_runtime_context = lambda: None
    page._mark_settings_as_dirty = lambda: None
    page._prepare_and_display_tasks = MagicMock()

    # Паразитный settings_changed приходит во время восстановления снимка.
    page._on_translation_options_changed()
    # Восстановление снимка завершилось (try/finally в _restore_queue_snapshot).
    page._snapshot_restore_in_progress = False

    # Пользователь нажимает «Старт»: task_manager уже содержит восстановленные
    # задачи, поэтому реальный _ensure_pending_tasks_for_start (без моков на
    # проверяемых ветках) не должен требовать пересборки.
    page.engine = None
    page.output_folder = "/tmp/out"
    page.task_manager.has_pending_tasks = lambda: True
    rebuild_calls = []
    page._prepare_and_display_tasks = lambda **kwargs: rebuild_calls.append(kwargs)

    result = page._ensure_pending_tasks_for_start()

    assert result is True
    # РЕГРЕСС: до фикса _task_queue_needs_rebuild оставался True после
    # restore, и _ensure_pending_tasks_for_start всё равно вызывал
    # _prepare_and_display_tasks(clean_rebuild=True), стирая восстановленную
    # очередь на старте перевода.
    assert rebuild_calls == []


# ---------------------------------------------------------------------------
# Регресс minor: _snapshot_force_save_pending не сбрасывался вне ветки
# _on_snapshot_autosave_finished (ui_dialogs_setup_a review, minor #2)
# ---------------------------------------------------------------------------

def test_queue_autosave_toggled_off_clears_pending_force_save():
    """Выключение автосохранения очереди должно снимать не только
    _snapshot_save_requested, но и отложенный force-запрос — иначе он
    переживёт выключенный тумблер и переиграется позже вне сессии/по
    чужому проекту, когда воркер наконец освободится."""
    page = _bare_page()
    page._snapshot_save_timer = SimpleNamespace(stop=MagicMock())
    page._snapshot_save_requested = True
    page._snapshot_force_save_pending = True
    page._mark_settings_as_dirty = lambda: None

    page._on_queue_autosave_toggled(False)

    assert page._snapshot_save_requested is False
    # РЕГРЕСС: до фикса флаг форс-запроса не сбрасывался здесь вовсе.
    assert page._snapshot_force_save_pending is False


def test_snapshot_autosave_finished_does_not_replay_force_save_during_restore():
    """Отложенный force-запрос не должен переигрываться, если воркер
    освободился ровно в момент, когда уже идёт восстановление другого
    снимка — иначе запись ушла бы уже по новому _get_snapshot_path()/
    task_manager, вне какой-либо сессии (по аналогии с гейтом в
    _schedule_snapshot_save)."""
    page = _bare_page()
    page._is_queue_autosave_enabled = lambda: True
    page._get_snapshot_path = lambda: "/tmp/queue_snapshot.db"
    page._snapshot_autosave_worker = SimpleNamespace(isRunning=lambda: False, result=True)
    page._write_snapshot_ui_settings = lambda *a, **k: None
    page._get_full_ui_settings = lambda: {}
    page._snapshot_force_save_pending = True
    page._snapshot_restore_in_progress = True  # воркер финишировал во время restore
    page._snapshot_save_requested = False
    page.is_session_active = False
    page._snapshot_save_timer = SimpleNamespace(start=MagicMock())
    spy = MagicMock()
    page._save_snapshot_async = spy

    page._on_snapshot_autosave_finished()

    spy.assert_not_called()
    assert page._snapshot_force_save_pending is False


# ---------------------------------------------------------------------------
# Регресс minor: залипший is_session_active не снимался детерминированно
# сразу при закрытии дочернего auto-glossary диалога (ui_dialogs_setup_a
# review, minor #4)
# ---------------------------------------------------------------------------

def test_on_auto_glossary_dialog_closed_resyncs_stale_session_flag_immediately():
    """Закрытие дочернего диалога авто-глоссария должно детерминированно
    снимать ложно взведённый is_session_active (через
    _check_and_sync_active_session), а не полагаться на то, что когда-нибудь
    его снимет произвольный следующий check_ready()/on_enter()."""
    page = _bare_page()
    page._auto_glossary_poll_timer = SimpleNamespace(stop=MagicMock())
    page._auto_glossary_dialog = object()
    page._auto_glossary_running = True
    page._auto_followup_running = True
    page.is_blocked_by_child_dialog = True
    page._auto_glossary_pending_translation = False
    page._auto_glossary_completed = True
    page.is_session_active = True
    page._session_active_forced_by_sync = True  # ложно взведён чужой сессией
    page.bus = SimpleNamespace(get_data=lambda key: None)
    page.engine = SimpleNamespace(session_id=None, task_manager=None)
    page.status_bar = SimpleNamespace(start_session=MagicMock(), stop_session=MagicMock())
    page._set_controls_enabled = MagicMock()
    page.check_ready = MagicMock()

    page._on_auto_glossary_dialog_closed(0)

    # РЕГРЕСС: до фикса метод проверял только `if not self.is_session_active`
    # и не звал _check_and_sync_active_session — флаг оставался True, а
    # check_ready() не вызывался.
    assert page.is_session_active is False
    page.status_bar.stop_session.assert_called_once()
    page.check_ready.assert_called_once()
