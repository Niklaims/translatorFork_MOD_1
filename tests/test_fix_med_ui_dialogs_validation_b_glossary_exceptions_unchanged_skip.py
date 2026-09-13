# -*- coding: utf-8 -*-
"""Регресс для ui-dialogs-validation/runtime/9-glossary-update-rescans-whole-
(группа ui_dialogs_validation_b).

apply_fixer_result (вложенная функция _push_untranslated_fixer_page) при
page.has_glossary_updates() вызывал _recalculate_untranslated_words_for_rows
по ВСЕМ строкам книги -- независимо от того, приняты изменения в помощнике
недоперевода или нажата "Отмена". Единственное, от чего реально зависит
результат пересчёта -- итоговый набор исключений детектора
(_get_effective_word_exceptions -> UntranslatedWordDetector(word_exceptions),
других входов у детектора нет). Если правка глоссария из фиксера не изменила
этот набор (термин добавили и тут же убрали, правка не дала новых латинских
остатков, или пользователь просто открыл и закрыл диалог глоссария), полный
пересчёт по всей книге на GUI-потоке без прогресса -- чистая трата времени, в
том числе на нажатие "Отмена".

_push_untranslated_fixer_page теперь снимает снимок
_get_effective_word_exceptions() ДО открытия страницы фиксера и сравнивает
его с текущим значением в apply_fixer_result: полный пересчёт выполняется,
только если набор действительно изменился.

Тест привязывает НАСТОЯЩЕЕ тело _push_untranslated_fixer_page к минимальному
объекту (ShellPage) с поддельной страницей фиксера вместо тяжёлого реального
виджета и считает, сколько раз реально вызывается
_recalculate_untranslated_words_for_rows -- алгоритмическое свойство (число
вызовов), а не измерение времени.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PyQt6 import QtCore

from gemini_translator.ui.dialogs import validation as validation_module
from gemini_translator.ui.dialogs.validation import TranslationValidatorPage as P
from gemini_translator.ui.shell import ShellPage


_APP = QtCore.QCoreApplication.instance()
if _APP is None:
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])


class _FakeFixerPage(ShellPage):
    result_ready = QtCore.pyqtSignal(bool)
    navigate_to_chapter_requested = QtCore.pyqtSignal(dict)
    mark_chapters_for_retry_requested = QtCore.pyqtSignal(list)

    def __init__(self, data, parent=None, initial_source_filter="all"):
        super().__init__(parent)
        self.data = data
        self.initial_source_filter = initial_source_filter
        # Тест управляет этими двумя флагами напрямую перед emit().
        self.glossary_updates = True
        self.changes = []
        self.save_immediately = False
        self.restored = None

    def restore_filter_state(self, saved_state, restore_selection=False):
        self.restored = (saved_state, restore_selection)

    def save_filter_state(self):
        return {}

    def has_glossary_updates(self):
        return self.glossary_updates

    def get_changes(self):
        return list(self.changes)

    def should_save_immediately(self):
        return self.save_immediately


class _Harness(ShellPage):
    """Минимальный объект с настоящим телом _push_untranslated_fixer_page."""

    _push_untranslated_fixer_page = P._push_untranslated_fixer_page

    def __init__(self, word_exceptions_sequence):
        super().__init__()
        self.results_data = {0: {'internal_html_path': 'Text/c1.xhtml'},
                              1: {'internal_html_path': 'Text/c2.xhtml'}}
        self._fixer_filter_state = None
        self._fixer_data_fingerprint = None
        # Каждый вызов _get_effective_word_exceptions выдаёт следующий набор
        # из последовательности; последний элемент повторяется дальше.
        self._word_exceptions_sequence = list(word_exceptions_sequence)
        self.word_exceptions_call_count = 0
        self.recalculated_rows = []
        self.reapplied = 0
        self.stats_updates = 0
        self.applied_changes = []
        self.navigated = []
        self.retried = []

    def _get_effective_word_exceptions(self):
        self.word_exceptions_call_count += 1
        if len(self._word_exceptions_sequence) > 1:
            return self._word_exceptions_sequence.pop(0)
        return self._word_exceptions_sequence[0]

    def _recalculate_untranslated_words_for_rows(self, rows):
        self.recalculated_rows.append(list(rows))

    def reapply_filters(self):
        self.reapplied += 1

    def _recalc_untranslated_stats_ui(self):
        self.stats_updates += 1

    def _apply_untranslated_fixer_changes(self, changes, soup_cache, save_immediately=False, show_feedback=True):
        self.applied_changes.append((changes, soup_cache, save_immediately, show_feedback))
        return {"replacements": len(changes)}

    def navigate_to_problem_chapter(self, payload):
        self.navigated.append(payload)

    def mark_chapters_for_retry(self, chapter_paths):
        self.retried.append(chapter_paths)


def _open_and_get_page(harness):
    pages = []
    harness.request_push.connect(pages.append)
    with patch.object(validation_module, "UntranslatedFixerPage", _FakeFixerPage, create=True):
        harness._push_untranslated_fixer_page(
            [], {},
            effective_source_filter="all",
            saved_state=None,
            new_fp="fp",
        )
    assert len(pages) == 1
    return pages[0]


def test_no_full_recalc_on_cancel_when_word_exceptions_unchanged():
    """До исправления: recalculated_rows содержит один полный вызов по всем
    строкам книги ДАЖЕ на нажатие 'Отмена', если set исключений не менялся."""
    harness = _Harness(word_exceptions_sequence=[{"foo"}])
    page = _open_and_get_page(harness)
    page.glossary_updates = True  # диалог глоссария открывали, но набор не изменился

    with patch.object(validation_module.QMessageBox, "information"):
        page.result_ready.emit(False)  # "Отмена"

    assert harness.recalculated_rows == [], (
        f"полный пересчёт по всем главам не должен запускаться на 'Отмена', "
        f"когда набор исключений детектора не изменился, но был вызван "
        f"{len(harness.recalculated_rows)} раз(а)"
    )
    assert harness.reapplied == 0
    assert harness.stats_updates == 0
    assert harness.word_exceptions_call_count == 2, (
        "снимок должен сниматься один раз до открытия страницы и один раз "
        "при закрытии, для сравнения"
    )


def test_full_recalc_still_happens_on_cancel_when_word_exceptions_changed():
    """Если набор исключений действительно изменился, поведение должно
    остаться прежним: полный пересчёт по всем строкам книги."""
    harness = _Harness(word_exceptions_sequence=[{"foo"}, {"foo", "bar"}])
    page = _open_and_get_page(harness)
    page.glossary_updates = True

    with patch.object(validation_module.QMessageBox, "information"):
        page.result_ready.emit(False)

    assert harness.recalculated_rows == [[0, 1]], (
        "при реально изменившемся наборе исключений пересчёт по всей книге "
        "обязан выполниться, как и раньше"
    )
    assert harness.reapplied == 1
    assert harness.stats_updates == 1


def test_no_full_recalc_when_accepted_without_changes_and_exceptions_unchanged():
    """Тот же дефект в ветке 'Применить' без изменений текста (только правка
    глоссария): полный пересчёт не нужен, если набор исключений не менялся,
    но дешёвое обновление статистики UI по-прежнему должно произойти."""
    harness = _Harness(word_exceptions_sequence=[{"foo"}])
    page = _open_and_get_page(harness)
    page.glossary_updates = True
    page.changes = []

    with patch.object(validation_module.QMessageBox, "information") as info_box:
        page.result_ready.emit(True)

    assert harness.recalculated_rows == []
    assert harness.reapplied == 0
    # Дешёвое обновление статистики UI (не полный пересчёт недоперевода)
    # всё равно должно случиться -- эквивалентно ветке "нет изменений".
    assert harness.stats_updates == 1
    assert info_box.called, "пользователь должен узнать, что правка глоссария сохранена"


def test_recalc_happens_when_accepted_without_changes_and_exceptions_changed():
    harness = _Harness(word_exceptions_sequence=[{"foo"}, {"foo", "bar"}])
    page = _open_and_get_page(harness)
    page.glossary_updates = True
    page.changes = []

    with patch.object(validation_module.QMessageBox, "information"):
        page.result_ready.emit(True)

    assert harness.recalculated_rows == [[0, 1]]
    assert harness.reapplied == 1
    assert harness.stats_updates == 1
