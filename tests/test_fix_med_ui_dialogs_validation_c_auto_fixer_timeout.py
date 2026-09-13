# -*- coding: utf-8 -*-
"""Регресс для ui-dialogs-validation/runtime/4-auto-fixer-nested-eventloop-no
и для замечаний код-ревью группы ui_dialogs_validation_c к первой версии
этой страховки.

run_auto_untranslated_fixer крутит вложенный QEventLoop, ожидая сигнал
``finished`` скрытой AITranslationPage. Этот сигнал приходит только если
translation_engine принял команду старта сессии. Если движок отклонил её
(is_starting/занятый session_id — например, гонка с ручным запуском
перевода тем же движком, пока в фоне ещё шёл автовалидатор),
``dialog.finished`` не эмитируется НИКОГДА, и без тайм-аута цикл событий
крутится вечно: автопайплайн замирает без возможности продолжения.

Тест привязывает НАСТОЯЩЕЕ тело run_auto_untranslated_fixer к минимальному
объекту, подменяя AITranslationDialog фейковым QObject, который никогда не
эмитирует finished — так же, как вело бы себя реальное отклонение команды
старта движком. AUTO_UNTRANSLATED_FIXER_START_TIMEOUT_MS уменьшен до
нескольких миллисекунд, чтобы тест не ждал реальные 10 минут (проверяем
факт срабатывания страховки, а не секунды).

Код-ревью (needs_work) на первую версию этой страховки указал два дефекта,
для которых ниже добавлены отдельные регресс-тесты:

- major: тайм-аут был сделан на ВСЮ AI-сессию, а не watchdog только на
  ПОДТВЕРЖДЕНИЕ СТАРТА — легитимная, но долгая (>N минут) сессия фиксера
  обрывалась бы страховкой ровно тогда, когда всё идёт штатно
  (test_started_session_is_not_killed_by_start_watchdog).
- minor: в ветке тайм-аута страница гасилась голым dialog.deleteLater(),
  минуя собственный путь остановки зависшего старта (reject() ->
  _check_can_close() -> _abort_stuck_session_start() ->
  _restore_preserved_queue()) — снятая со страницы чужая очередь задач
  терялась (test_timed_out_session_is_stopped_via_reject_not_bare_delete).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from gemini_translator.ui.dialogs.validation import TranslationValidatorPage as P


_APP = QApplication.instance() or QApplication([])


def _make_app():
    return _APP


class _FakeAutoFixerDialog(QObject):
    """Имитирует AITranslationPage(auto_start=True), у которой движок
    ПРОИГНОРИРОВАЛ команду старта: finished не эмитируется никогда, а
    _owned_session_id (выставляется реальной страницей по событию
    session_started) остаётся не установленным."""

    finished = pyqtSignal(int)

    def __init__(self, tasks_payloads, settings_manager, parent=None, **kwargs):
        # Реальный parent (QWidget с некорректной родословной) сюда не
        # передаём — фейку не нужна настоящая иерархия виджетов.
        super().__init__(None)
        self.tasks_payloads = tasks_payloads
        self.finish_reason = ''
        self.hidden = False

    def hide(self):
        self.hidden = True

    def get_translated_results(self):
        # До настоящего теста дело не должно дойти: страховка обязана
        # вернуть ошибку раньше этого вызова.
        raise AssertionError(
            "get_translated_results() не должен вызываться — сессия не стартовала"
        )


class _Harness(QWidget):
    """Минимальный объект с настоящим телом run_auto_untranslated_fixer."""

    run_auto_untranslated_fixer = P.run_auto_untranslated_fixer
    _get_auto_untranslated_prompt_text = P._get_auto_untranslated_prompt_text
    _format_auto_untranslated_trace_details = P._format_auto_untranslated_trace_details
    # P._truncate_auto_trace_text — обычный staticmethod; доступ через класс
    # уже возвращает голую функцию, и без повторного staticmethod() она бы
    # неявно приняла self первым позиционным аргументом при вызове через
    # self._truncate_auto_trace_text(...).
    _truncate_auto_trace_text = staticmethod(P._truncate_auto_trace_text)
    # Ускоряем тест: страховка должна сработать за миллисекунды, а не за
    # боевые 10 минут (AUTO_UNTRANSLATED_FIXER_START_TIMEOUT_MS).
    AUTO_UNTRANSLATED_FIXER_START_TIMEOUT_MS = 30

    def __init__(self, data_for_dialog):
        super().__init__()
        self.settings_manager = object()
        self._data_for_dialog = data_for_dialog

    def _collect_untranslated_fixer_payload(self, target_internal_paths=None, show_feedback=False):
        return list(self._data_for_dialog), {}

    def _apply_untranslated_fixer_changes(self, changes, soup_cache, **kwargs):
        # Применение изменённых фрагментов к results_data — отдельная логика,
        # не имеющая отношения к дефекту про зависший QEventLoop; стаб
        # только фиксирует, что до неё вообще дошло исполнение (то есть
        # штатное завершение НЕ было ошибочно принято за тайм-аут).
        self.applied_changes = list(changes)
        return {'groups_changed': len(changes), 'replacements': len(changes), 'affected_rows': 0, 'saved_count': 0}


def test_ignored_start_command_times_out_instead_of_hanging_forever():
    _make_app()
    h = _Harness([{"context": "Hello world."}])

    with patch(
        "gemini_translator.ui.dialogs.validation.AITranslationDialog",
        _FakeAutoFixerDialog,
    ):
        # Без страховки этот вызов завис бы навсегда (dialog.finished
        # никогда не эмитируется) — pytest-таймаута тут нет, так что
        # зависший тест сам по себе доказал бы дефект, провалив прогон по
        # общему таймауту. Со страховкой вызов обязан вернуться быстро с
        # понятной ошибкой.
        result = h.run_auto_untranslated_fixer()

    assert result["success"] is False
    assert "не стартовала" in result["error"] or "движок" in result["error"]


def test_normal_finish_still_returns_results_without_a_false_timeout():
    """Страховка не должна ложно срабатывать на штатном быстром finished."""
    _make_app()
    h = _Harness([{"context": "Hello world."}])

    class _FakeDialogThatFinishesImmediately(_FakeAutoFixerDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Эмулируем штатное завершение сессии почти сразу — но ПОСЛЕ
            # того, как run_auto_untranslated_fixer успеет подключить
            # dialog.finished к wait_loop.quit (иначе emit() до connect()
            # ничего не разбудит, как и в реальном Qt).
            QTimer.singleShot(0, lambda: self.finished.emit(0))

        def get_translated_results(self):
            return ["<html><body><p data-id=\"0\">Hello!</p></body></html>"]

    with patch(
        "gemini_translator.ui.dialogs.validation.AITranslationDialog",
        _FakeDialogThatFinishesImmediately,
    ):
        result = h.run_auto_untranslated_fixer()

    assert result["success"] is True
    assert result["translated_groups"] == 1


def test_started_session_is_not_killed_by_start_watchdog():
    """РЕГРЕСС на major-замечание код-ревью: тайм-аут — это watchdog только
    на ПОДТВЕРЖДЕНИЕ СТАРТА (dialog._owned_session_id), а не на всю сессию.

    Первая версия страховки гасила wait_loop через фиксированный интервал
    безусловно — даже если событие session_started уже пришло и сессия
    легитимно продолжается дольше этого интервала (десятки глав, RPM-лимиты,
    ретраи). Здесь _owned_session_id выставляется сразу же (как это делает
    реальная AITranslationPage._on_global_event на событие session_started),
    а finished приходит уже ПОСЛЕ того, как старый безусловный тайм-аут
    успел бы сработать. На исправленном коде это не должно считаться
    тайм-аутом.
    """
    _make_app()
    h = _Harness([{"context": "Hello world."}])
    # Watchdog на подтверждение старта — совсем короткий; дальше сессия
    # обязана считаться стартовавшей и ждаться без верхней границы.
    h.AUTO_UNTRANSLATED_FIXER_START_TIMEOUT_MS = 15

    class _FakeDialogStartedButSlow(_FakeAutoFixerDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Движок подтвердил старт немедленно...
            self._owned_session_id = "sess-1"
            # ...но сама AI-сессия объективно дольше интервала watchdog'а.
            QTimer.singleShot(120, lambda: self.finished.emit(0))

        def get_translated_results(self):
            return ["<html><body><p data-id=\"0\">Hello!</p></body></html>"]

    with patch(
        "gemini_translator.ui.dialogs.validation.AITranslationDialog",
        _FakeDialogStartedButSlow,
    ):
        result = h.run_auto_untranslated_fixer()

    assert result["success"] is True, (
        f"стартовавшая сессия ложно принята за тайм-аут: {result.get('error')!r}"
    )
    assert result["translated_groups"] == 1


def test_timed_out_session_is_stopped_via_reject_not_bare_delete():
    """РЕГРЕСС на minor-замечание код-ревью: тайм-аут обязан гасить страницу
    через её собственный reject() (-> _check_can_close() ->
    _abort_stuck_session_start() -> _restore_preserved_queue()), а не голым
    dialog.deleteLater() — иначе снятая со страницы перед стартом чужая
    очередь задач никогда не возвращается на место.
    """
    _make_app()
    h = _Harness([{"context": "Hello world."}])

    created = []

    class _FakeDialogWithReject(_FakeAutoFixerDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.reject_called = False
            created.append(self)

        def reject(self):
            self.reject_called = True

    with patch(
        "gemini_translator.ui.dialogs.validation.AITranslationDialog",
        _FakeDialogWithReject,
    ):
        result = h.run_auto_untranslated_fixer()

    assert result["success"] is False
    assert len(created) == 1
    assert created[0].reject_called is True, (
        "тайм-аут погасил диалог напрямую (deleteLater), не пройдя через "
        "reject() -> _abort_stuck_session_start() -> _restore_preserved_queue()"
    )
