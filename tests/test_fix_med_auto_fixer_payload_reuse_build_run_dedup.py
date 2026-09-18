# -*- coding: utf-8 -*-
"""Регресс для ui-dialogs-validation/runtime/7-fixer-soup-cache-whole-book-me
(перенос из волны 2, остаток находки 7 -- автопайплайн).

В автопайплайне setup.py._on_auto_validator_finished сначала вызывает
dialog.build_auto_untranslated_request_details(target_internal_paths=fix_signature)
только ради текста трассировки для лога, а сразу следом --
dialog.run_auto_untranslated_fixer(target_internal_paths=fix_signature) с ТЕМ ЖЕ
набором путей глав. run_auto_untranslated_fixer собирал payload
(_collect_untranslated_fixer_payload -- полный BeautifulSoup-парсинг HTML
каждой флагованной главы) заново, хотя build_ только что собрал ровно то же
самое -- двойной полный синхронный парсинг книги на каждый точечный фикс
недоперевода в авто-режиме.

Код-ревью (needs_work) на первую версию этой страховки указал:

- major: первая версия теста звала _collect_untranslated_fixer_payload_cached
  НАПРЯМУЮ вместо настоящего run_auto_untranslated_fixer -- ловушка не
  участвовала в реальном месте дефекта и пережила бы откат боевой проводки
  (getattr-обёртки внутри run_) незамеченной
  (test_run_reuses_payload_collected_by_build_exactly_once ниже теперь
  привязывает настоящее тело run_auto_untranslated_fixer к харнессу,
  settings_manager=None даёт ему завершиться сразу после сбора payload, не
  создавая AITranslationDialog/QEventLoop/таймеры).
- minor: временная связка build_ -> run_ через self._auto_untranslated_payload_cache
  в ветке дедупликации (setup.py -- «тот же набор глав подряд», run_
  вообще не вызывается) оставляла bs4-деревья в кеше висеть дольше, чем до
  появления кеша (test_dedup_branch_clears_leftover_payload_cache ниже).

Тест привязывает НАСТОЯЩИЕ тела build_auto_untranslated_request_details,
run_auto_untranslated_fixer, _collect_untranslated_fixer_payload_cached и
_collect_untranslated_fixer_payload к минимальному объекту и считает, сколько
раз реально был выполнен парсинг за пару build_ + run_.

(a) Алгоритмическое свойство: суммарно на пару build_ + run_ парсинг должен
    произойти РОВНО ОДИН раз, а не два. До исправления -- 2 вызова.
(b) Корректность: payload, отданный кешем при прямом обращении к
    _collect_untranslated_fixer_payload_cached, должен быть ТЕМ ЖЕ (по
    содержимому), что видел build_ -- ничего не потеряно и не придумано
    заново; отдельно проверяются промахи кеша (другой набор путей,
    отсутствие предшествующего build_, повторное обращение после того, как
    кеш уже выдан один раз) -- всё это обязано по-прежнему запускать
    настоящий сбор, а не тихо вернуть пустоту или чужие данные.
(c) Ветка дедупликации в setup.py (run_ вообще не вызывается) обязана
    сбрасывать кеш, оставленный build_, а не удерживать его bs4-деревья
    дольше, чем до появления кеша.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from gemini_translator.ui.dialogs.setup import InitialSetupDialog
from gemini_translator.ui.dialogs.validation import TranslationValidatorPage as P


_APP = QApplication.instance() or QApplication([])


class _Harness(QWidget):
    """Минимальный объект с настоящими телами методов автопайплайна."""

    build_auto_untranslated_request_details = P.build_auto_untranslated_request_details
    run_auto_untranslated_fixer = P.run_auto_untranslated_fixer
    _collect_untranslated_fixer_payload_cached = P._collect_untranslated_fixer_payload_cached
    _format_auto_untranslated_trace_details = P._format_auto_untranslated_trace_details
    _get_auto_untranslated_prompt_text = P._get_auto_untranslated_prompt_text
    _truncate_auto_trace_text = staticmethod(P._truncate_auto_trace_text)

    def __init__(self, results_data):
        super().__init__()
        self.results_data = results_data
        # None -- как и в реальном автопайплайне, run_auto_untranslated_fixer
        # добирается до этой проверки уже ПОСЛЕ сбора payload и возвращает
        # {'success': False, 'error': 'Settings manager is unavailable.'} --
        # не успевая создать AITranslationDialog, QEventLoop или таймеры
        # (см. tests/test_fix_med_ui_dialogs_validation_c_auto_fixer_timeout.py,
        # тот же приём для той же цели).
        self.settings_manager = None
        self._auto_untranslated_payload_cache = None
        self.collect_call_count = 0
        self.deleted = False
        # Реальное тело _collect_untranslated_fixer_payload, привязанное к
        # этому харнессу -- вызывается через обёртку ниже, которая считает
        # вызовы, не подменяя саму логику сбора (тот же приём, что и в
        # tests/test_fix_med_ui_dialogs_validation_b_fixer_double_collect.py).
        self._real_collect = P._collect_untranslated_fixer_payload.__get__(self)

    def _collect_untranslated_fixer_payload(self, target_internal_paths=None, show_feedback=True):
        self.collect_call_count += 1
        return self._real_collect(target_internal_paths=target_internal_paths, show_feedback=show_feedback)

    def _ensure_row_translated_html_loaded(self, row_idx):
        return self.results_data[row_idx].get('translated_html')

    def deleteLater(self):
        # Отмечаем факт вызова для теста дедуп-ветки, не подменяя
        # настоящую очистку Qt-объекта.
        self.deleted = True
        super().deleteLater()


class _SettingsWidgetStub:
    """Минимальная замена AutoTranslateWidget -- нужен только get_settings()."""

    def __init__(self, settings):
        self._settings = dict(settings)

    def get_settings(self):
        return dict(self._settings)


class _AutoWorkflowDedupHarness:
    """Минимальный объект с настоящим телом _on_auto_validator_finished --
    только для сценария «тот же набор глав подряд» (дедуп-ветка).
    Дублирует минимально нужный набор полей харнесса
    tests/test_auto_workflow_followup.py::_AutoWorkflowHarness локально,
    не трогая тот файл (другая группа код-ревью)."""

    _on_auto_validator_finished = InitialSetupDialog._on_auto_validator_finished
    _finish_auto_validator_followup = InitialSetupDialog._finish_auto_validator_followup

    def __init__(self, dialog, repeated_signature):
        self._auto_validator_dialog = dialog
        self.auto_translate_widget = _SettingsWidgetStub({
            'retry_short_enabled': False,
            'retry_untranslated_enabled': True,
            'ai_consistency_enabled': False,
        })
        self._auto_last_untranslated_fix_signatures = {repeated_signature}
        self.logs = []
        self.reset_calls = 0
        self.ready_calls = 0

    def _get_effective_auto_short_ratio_limit(self, auto_settings, data):
        return 0.70, "default"

    def _auto_log(self, message, force=False, **kwargs):
        self.logs.append(message)

    def _format_auto_chapter_list(self, chapters, limit=10, preserve_order=False):
        values = list(chapters[:limit]) if isinstance(chapters, tuple) else list(chapters)[:limit]
        return ", ".join(values)

    def _reset_auto_workflow_state(self):
        self.reset_calls += 1

    def check_ready(self):
        self.ready_calls += 1


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
            'translated_html': '<html><body><p>Он сказал World миру.</p></body></html>',
            'untranslated_words': ['World'],
            'status': 'neutral',
        },
    }


def test_run_reuses_payload_collected_by_build_exactly_once():
    """До исправления: build_ + run_ вместе парсят книгу дважды. После --
    ровно один раз, а run_auto_untranslated_fixer переиспользует уже
    собранное.

    Настоящий вызов run_auto_untranslated_fixer (а не имитация вызовом
    _collect_untranslated_fixer_payload_cached напрямую -- код-ревью
    needs_work на первую версию этого теста указало, что так тест обходит
    getattr-проводку внутри run_ стороной и пережил бы её откат
    незамеченным): settings_manager=None доводит его до возврата сразу
    после сбора payload, так что взаимодействие с AITranslationDialog не
    нужно эмулировать вовсе.
    """
    harness = _Harness(_make_results_data())
    fix_signature = ('Text/chapter1.xhtml', 'Text/chapter2.xhtml')

    details_text = harness.build_auto_untranslated_request_details(
        target_internal_paths=fix_signature,
        batch_size=50,
    )
    assert details_text, "трассировка должна была собраться из непустого payload"
    assert harness.collect_call_count == 1

    # То же самое сочетание вызовов и тот же target_internal_paths, что и в
    # setup.py._on_auto_validator_finished: build_ -- для текста трассировки,
    # затем run_ -- уже за реальным фиксом.
    result = harness.run_auto_untranslated_fixer(target_internal_paths=fix_signature)

    assert harness.collect_call_count == 1, (
        f"payload собирался {harness.collect_call_count} раз(а) вместо одного -- "
        "run_auto_untranslated_fixer не переиспользовал результат build_"
    )
    # settings_manager=None -> run_ возвращается сразу после сбора payload с
    # понятной ошибкой, но groups_found считается от РЕАЛЬНО собранного (не
    # пустого и не urезанного) payload -- если бы кеш отдал что-то не то,
    # это число разошлось бы с количеством глав.
    assert result['success'] is False
    assert result['groups_found'] == 2
    assert 'Settings manager' in result['error']


def test_dedup_branch_clears_leftover_payload_cache():
    """Код-ревью needs_work, находка 3 (minor): ветка «тот же набор глав
    подряд» в setup.py._on_auto_validator_finished вообще не вызывает
    run_auto_untranslated_fixer -- а build_auto_untranslated_request_details
    чуть выше по той же ветке уже успел положить собранный payload (вместе
    с soup_cache -- bs4-деревьями ВСЕХ флагованных глав) в
    dialog._auto_untranslated_payload_cache. Без явного сброса эти деревья
    удерживались бы дольше, чем до появления кеша (до правки run_
    пересобирал payload сам и никогда не оставлял такого кеша висеть)."""
    dialog = _Harness(_make_results_data())
    fix_signature = ('Text/chapter1.xhtml', 'Text/chapter2.xhtml')

    harness = _AutoWorkflowDedupHarness(dialog, repeated_signature=fix_signature)
    assert dialog._auto_untranslated_payload_cache is None

    harness._on_auto_validator_finished(total_scanned=2, suspicious_found=2)

    # _on_auto_validator_finished сам вызывает build_ (ради текста
    # трассировки для лога) до дедуп-проверки -- подтверждаем, что кеш
    # реально был заполнен, иначе тест ничего бы не проверял.
    assert harness.reset_calls == 1, "дедуп-ветка должна была довести автопайплайн до финиша"
    assert dialog.deleted, "страница должна была быть отпущена через deleteLater()"
    assert dialog._auto_untranslated_payload_cache is None, (
        "кеш, оставленный build_, пережил ветку дедупликации -- bs4-деревья "
        "всех флагованных глав удерживаются дольше, чем до появления кеша"
    )


def test_cache_is_single_use_and_scoped_to_matching_paths():
    """Кеш не должен утекать между несвязанными вызовами: другой набор путей
    (или отсутствие предшествующего build_) обязан запускать настоящий сбор,
    а не тихо возвращать пустоту/чужие данные; повторное обращение с тем же
    ключом после того, как кеш уже выдан один раз, тоже пересобирает."""
    harness = _Harness(_make_results_data())

    # "run_" без предшествующего build_ -- обычный путь (обратная совместимость).
    data_for_dialog, _ = harness._collect_untranslated_fixer_payload_cached(
        target_internal_paths=('Text/chapter1.xhtml',),
    )
    assert harness.collect_call_count == 1
    assert {item['internal_html_path'] for item in data_for_dialog} == {'Text/chapter1.xhtml'}

    harness.build_auto_untranslated_request_details(
        target_internal_paths=('Text/chapter1.xhtml', 'Text/chapter2.xhtml'),
        batch_size=50,
    )
    assert harness.collect_call_count == 2

    # Другой набор путей -- кеш промахивается намеренно, собираем заново.
    data_mismatch, _ = harness._collect_untranslated_fixer_payload_cached(
        target_internal_paths=('Text/chapter2.xhtml',),
    )
    assert harness.collect_call_count == 3
    assert {item['internal_html_path'] for item in data_mismatch} == {'Text/chapter2.xhtml'}

    # Кеш от build_ уже израсходован промахом выше -- повторное обращение с
    # ИСХОДНЫМ (совпадающим) ключом не должно найти чужой старый кеш и снова
    # запускает настоящий сбор, а не падает и не отдаёт пустоту.
    data_again, _ = harness._collect_untranslated_fixer_payload_cached(
        target_internal_paths=('Text/chapter1.xhtml', 'Text/chapter2.xhtml'),
    )
    assert harness.collect_call_count == 4
    assert {item['internal_html_path'] for item in data_again} == {
        'Text/chapter1.xhtml', 'Text/chapter2.xhtml',
    }
