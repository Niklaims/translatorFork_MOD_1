# -*- coding: utf-8 -*-
"""Регресс для ui-dialogs-validation/runtime/7-fixer-soup-cache-whole-book-me
(группа ui_dialogs_validation_b).

_open_untranslated_fixer сначала собирал payload помощника недоперевода
целиком (это означает полный BeautifulSoup-парсинг HTML каждой флагованной
главы книги через _collect_untranslated_fixer_payload), а затем, если
находились "устаревшие" строки (только что отредактированные вручную или
явно помеченные stale), пересчитывал недоперевод для них и СОБИРАЛ payload
ЗАНОВО целиком -- отбрасывая первый результат полностью. На книге с сотнями
флагованных глав это двойной полный синхронный парсинг на GUI-потоке ровно
в сценарии, для которого stale-логика и была добавлена (только что
отредактированные главы).

Тест привязывает НАСТОЯЩИЕ тела _open_untranslated_fixer и
_recalculate_untranslated_words_for_rows к минимальному объекту (без
поднятия реальной страницы UntranslatedFixerPage -- она подставляется через
monkeypatch класса) и считает, сколько раз реально был вызван
_collect_untranslated_fixer_payload.

(a) Алгоритмическое свойство: при наличии stale-строк payload обязан
    собираться РОВНО ОДИН раз, а не два. До исправления этот тест ПАДАЕТ
    (2 вызова).
(b) Корректность не должна пострадать от переноса пересчёта stale-строк
    перед сбором payload: итоговый data_for_dialog обязан отражать
    ПОСЛЕ-пересчётное состояние (термин из только что "отредактированной"
    stale-главы должен попасть в payload, переданный на страницу).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from gemini_translator.ui.dialogs.validation import TranslationValidatorPage as P


_APP = QApplication.instance() or QApplication([])


class _Harness(QWidget):
    """Минимальный объект с настоящими телами _open_untranslated_fixer и
    _recalculate_untranslated_words_for_rows."""

    _open_untranslated_fixer = P._open_untranslated_fixer
    _recalculate_untranslated_words_for_rows = P._recalculate_untranslated_words_for_rows
    _build_current_untranslated_exceptions = P._build_current_untranslated_exceptions
    _compute_fixer_data_fingerprint = P._compute_fixer_data_fingerprint

    def __init__(self, results_data):
        super().__init__()
        self.results_data = results_data
        self._fixer_stale_rows = set()
        self._fixer_filter_state = None
        self._fixer_data_fingerprint = None
        self.collect_call_count = 0
        self.pushed_payload = None
        # Реальное тело _collect_untranslated_fixer_payload, привязанное к
        # этому харнессу -- вызывается через обёртку ниже, которая считает
        # вызовы, не подменяя саму логику сбора.
        self._real_collect = P._collect_untranslated_fixer_payload.__get__(self)

    def _collect_untranslated_fixer_payload(self, target_internal_paths=None, show_feedback=True):
        self.collect_call_count += 1
        return self._real_collect(target_internal_paths=target_internal_paths, show_feedback=show_feedback)

    def _build_user_problem_terms_payload(self):
        return []

    def _ensure_row_translated_html_loaded(self, row_idx):
        return self.results_data[row_idx].get('translated_html')

    def _get_effective_word_exceptions(self):
        return set()


def _fake_push(self, data_for_dialog, soup_cache, *, effective_source_filter, saved_state, new_fp):
    # Заменяем настоящий UntranslatedFixerPage (тяжёлый реальный виджет,
    # не имеющий отношения к дефекту про двойной сбор) минимальной
    # фиксацией переданного payload.
    self.pushed_payload = list(data_for_dialog)


def _make_results_data():
    return {
        0: {
            'internal_html_path': 'Text/chapter1.xhtml',
            'translated_html': '<html><body><p>Он сказал Hello миру.</p></body></html>',
            'untranslated_words': ['Hello'],
            'status': 'neutral',
        },
        1: {
            'internal_html_path': 'Text/chapter2.xhtml',
            # Ещё не пересчитано -- ключа untranslated_words нет, хотя в
            # тексте есть латинское слово World (>= 3 букв), которое должно
            # быть найдено после пересчёта stale-строки.
            'translated_html': '<html><body><p>Он сказал World миру.</p></body></html>',
            'status': 'neutral',
        },
    }


def test_collect_is_called_exactly_once_when_stale_rows_exist(monkeypatch):
    """До исправления: _collect_untranslated_fixer_payload вызывается ДВАЖДЫ
    (один раз до пересчёта stale-строки, один раз после, отбрасывая первый
    результат) -- алгоритмическая избыточность, не секунды."""
    monkeypatch.setattr(P, "_push_untranslated_fixer_page", _fake_push)

    harness = _Harness(_make_results_data())
    harness._fixer_stale_rows.add(1)  # строка 1 требует пересчёта

    harness._open_untranslated_fixer()

    assert harness.collect_call_count == 1, (
        f"payload собирался {harness.collect_call_count} раз(а) вместо одного "
        "при наличии stale-строк -- двойной полный BeautifulSoup-парсинг книги"
    )


def test_stale_row_recalculation_still_reflected_in_pushed_payload(monkeypatch):
    """Перенос пересчёта stale-строк перед (единственным) сбором payload не
    должен потерять корректность: термин из только что пересчитанной строки
    обязан присутствовать в payload, переданном на страницу фиксера."""
    monkeypatch.setattr(P, "_push_untranslated_fixer_page", _fake_push)

    harness = _Harness(_make_results_data())
    harness._fixer_stale_rows.add(1)

    harness._open_untranslated_fixer()

    assert harness.pushed_payload is not None, "страница фиксера должна была открыться"
    paths_in_payload = {item['internal_html_path'] for item in harness.pushed_payload}
    assert 'Text/chapter1.xhtml' in paths_in_payload
    assert 'Text/chapter2.xhtml' in paths_in_payload, (
        "после пересчёта stale-строки её термин (World) должен попасть в "
        "payload помощника недоперевода"
    )
    # Stale-множество должно быть очищено после пересчёта.
    assert harness._fixer_stale_rows == set()


def test_collect_is_called_once_when_no_stale_rows(monkeypatch):
    """Базовый случай (без stale-строк) и раньше не дублировал сбор -- эта
    проверка защищает от случайной регрессии при рефакторинге."""
    monkeypatch.setattr(P, "_push_untranslated_fixer_page", _fake_push)

    data = _make_results_data()
    del data[1]  # оставляем только уже флагованную строку без stale
    harness = _Harness(data)

    harness._open_untranslated_fixer()

    assert harness.collect_call_count == 1
