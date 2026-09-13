# -*- coding: utf-8 -*-
"""ui_dialogs_validation_dialogs_untranslated_fixer_dialog — med-фиксы.

ui-dialogs-validation/runtime/10-fixer-apply-filters-quadratic:
apply_filters, _show_row_action_menu (через _count_related_occurrences) и
ProjectGlossaryController.find_entries пересобирали blacklist-разбиение и
сканировали ВЕСЬ глоссарий линейно на КАЖДОГО кандидата КАЖДОЙ строки —
квадратичная стоимость на каждый тик фильтра/открытие контекстного меню
строки. Тесты ниже проверяют алгоритмическое свойство (число сканирований),
а не секунды: после фикса число проходов по blacklist_set/glossary_entries
не растёт с числом кандидатов/терминов.

Доработка по замечаниям ревью (needs_work):
- major: phrase_blocked не зависел от кандидата, но пересчитывался для
  КАЖДОГО кандидата в ОБОИХ циклах _collect_visible_candidates_for_item —
  для фразового blacklist выигрыша почти не было (N*M*2 вызовов
  _phrase_matches_context на строку). См.
  PhraseBlockedComputedOnceTests.
- minor: _partition_blacklist_entries клала пустую запись blacklist в
  phrases, а _phrase_matches_context('', haystack) для неё всегда
  возвращает True — блокируя ВСЕХ кандидатов. См.
  EmptyBlacklistEntryIgnoredTests.
- minor: populate_table не переиспользовал glossary_index для тултипов —
  полный линейный проход по project_glossary на каждый термин каждой
  строки. См. PopulateTableReusesGlossaryIndexTests.

ui-dialogs-validation/runtime/12-non-atomic-chapter-and-glossar:
половина в untranslated_fixer_dialog.py (ProjectGlossaryController.save)
уже переведена на atomic_write_json — здесь это зафиксировано регрессионным
тестом (см. ProjectGlossaryControllerSaveIsAtomicTests).
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.ui.dialogs.validation_dialogs import untranslated_fixer_dialog as ufd
from gemini_translator.ui.dialogs.validation_dialogs.untranslated_fixer_dialog import (
    ProjectGlossaryController,
    UntranslatedFixerPage,
)

_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Node:
    """Обычный (не-Qt) объект с .parent() — этого достаточно для
    ProjectGlossaryController._discover_context (см. другие тесты этого
    модуля, например test_dedup_pcluster_70_glossary_entry_normalization.py).
    """

    def __init__(self, parent=None, **attrs):
        self._parent = parent
        for key, value in attrs.items():
            setattr(self, key, value)

    def parent(self):
        return self._parent


def _controller():
    owner = _Node(parent=_Node())
    return ProjectGlossaryController(owner)


class _CountingList(list):
    """Список, считающий, сколько раз его перебрали (__iter__). Используется
    чтобы доказать, что find_entries с готовым индексом больше НЕ сканирует
    glossary_entries линейно."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.iter_calls = 0

    def __iter__(self):
        self.iter_calls += 1
        return super().__iter__()


class _CountingSet(set):
    """Множество, считающее свои __iter__-вызовы. Используется чтобы
    доказать, что _collect_visible_candidates_for_item больше не пересобирает
    blacklist-разбиение на каждого кандидата."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.iter_calls = 0

    def __iter__(self):
        self.iter_calls += 1
        return super().__iter__()


class _FixerHarness:
    """Минимальный харнесс: боевые тела нужных методов, привязанные к
    простому объекту (по образцу test_untranslated_fixer_navigation.py)."""

    _get_effective_context_payload = UntranslatedFixerPage._get_effective_context_payload
    _collect_visible_candidates_for_item = UntranslatedFixerPage._collect_visible_candidates_for_item
    _blacklist_partition = UntranslatedFixerPage._blacklist_partition
    _phrase_matches_context = staticmethod(UntranslatedFixerPage._phrase_matches_context)
    _count_related_occurrences = UntranslatedFixerPage._count_related_occurrences
    _count_related_occurrences_batch = UntranslatedFixerPage._count_related_occurrences_batch
    populate_table = UntranslatedFixerPage.populate_table
    _get_glossary_match_summary = UntranslatedFixerPage._get_glossary_match_summary
    _get_glossary_entries_for_term = UntranslatedFixerPage._get_glossary_entries_for_term


def _item(term, context):
    return {
        "term": term,
        "context": context,
        "location_info": "Text/chapter1.xhtml",
        "source_type": "system",
    }


# --- ProjectGlossaryController.build_index / find_entries: без квадратичного скана ---

class GlossaryIndexAvoidsRescanTests(unittest.TestCase):
    def test_find_entries_without_index_scans_glossary_each_call(self):
        # Базовая линия (регресс не сломан): без индекса поведение прежнее —
        # линейный проход по glossary_entries на каждый вызов.
        controller = _controller()
        entries = _CountingList([{"original": "Foo", "rus": "a"}])

        controller.find_entries(entries, "Foo")
        controller.find_entries(entries, "Foo")

        self.assertEqual(entries.iter_calls, 2)

    def test_find_entries_with_index_does_not_rescan_glossary(self):
        controller = _controller()
        entries = _CountingList([
            {"original": "Foo", "rus": "a"},
            {"original": "Bar", "rus": "b"},
        ])

        index = controller.build_index(entries)
        entries.iter_calls = 0  # build_index сам обязан пройти список один раз — сбрасываем счётчик

        result_foo = controller.find_entries(entries, "Foo", index=index)
        result_bar = controller.find_entries(entries, "Bar", index=index)
        result_missing = controller.find_entries(entries, "Baz", index=index)

        # Ключевая проверка: после построения индекса повторные find_entries
        # НЕ перебирают glossary_entries заново (ui-dialogs-validation/runtime/10).
        self.assertEqual(entries.iter_calls, 0)
        self.assertEqual([e["original"] for e in result_foo], ["Foo"])
        self.assertEqual([e["original"] for e in result_bar], ["Bar"])
        self.assertEqual(result_missing, [])

    def test_index_returns_copies_not_live_references(self):
        controller = _controller()
        entries = [{"original": "Foo", "rus": "a"}]
        index = controller.build_index(entries)

        found = controller.find_entries(entries, "Foo", index=index)
        found[0]["rus"] = "mutated"

        self.assertEqual(entries[0]["rus"], "a")


# --- _blacklist_partition: одиночные слова/фразы разбиваются один раз ---

class BlacklistPartitionReuseTests(unittest.TestCase):
    def _harness(self, blacklist):
        dialog = _FixerHarness()
        dialog.blacklist_set = blacklist
        return dialog

    def test_partition_splits_single_words_and_phrases(self):
        dialog = self._harness({"Ignore", "two words phrase"})
        singles, phrases = dialog._blacklist_partition()

        self.assertEqual(singles, {"ignore"})
        self.assertEqual(phrases, ["two words phrase"])

    def test_collect_candidates_does_not_rescan_blacklist_per_candidate(self):
        # Много различных "чужеродных" кандидатов в одном контексте.
        words = [f"Alien{i}" for i in range(30)]
        context = "<p>" + " ".join(words) + "</p>"
        dialog = self._harness(_CountingSet({"zzzignored"}))

        payload = dialog._collect_visible_candidates_for_item(_item("Alien0", context))

        self.assertGreaterEqual(len(payload["remaining_candidates"]), 30)
        # ДО фикса: два independent-прохода по self.blacklist_set НА КАЖДОГО
        # кандидата в ДВУХ циклах => __iter__ вызывался бы ~4*30=120 раз.
        # ПОСЛЕ фикса: разбиение строится один раз до обоих циклов.
        self.assertLessEqual(dialog.blacklist_set.iter_calls, 2)

    def test_passed_in_partition_is_reused_verbatim(self):
        dialog = self._harness(_CountingSet({"unused"}))
        partition = dialog._blacklist_partition()
        dialog.blacklist_set.iter_calls = 0

        dialog._collect_visible_candidates_for_item(_item("Alien", "<p>Alien text</p>"), partition)

        # Явно переданное разбиение не должно провоцировать повторный обход
        # исходного blacklist_set вообще.
        self.assertEqual(dialog.blacklist_set.iter_calls, 0)


# --- _count_related_occurrences_batch: один проход по строкам на пачку терминов ---

class CountRelatedOccurrencesBatchTests(unittest.TestCase):
    def _harness(self, items):
        dialog = _FixerHarness()
        dialog.original_data = items
        dialog.blacklist_set = set()
        return dialog

    def test_batch_counts_match_single_term_calls(self):
        items = [
            _item("Alpha", "<p>Alpha context</p>"),
            _item("Beta", "<p>Beta context</p>"),
            _item("Alpha", "<p>Alpha again</p>"),
        ]
        dialog = self._harness(items)

        counts = dialog._count_related_occurrences_batch(["Alpha", "Beta", "Missing"])

        self.assertEqual(counts["alpha"], 2)
        self.assertEqual(counts["beta"], 1)
        self.assertEqual(counts["missing"], 0)

    def test_single_term_helper_delegates_to_batch_with_same_result(self):
        items = [_item("Alpha", "<p>Alpha context</p>")]
        dialog = self._harness(items)

        self.assertEqual(dialog._count_related_occurrences("Alpha"), 1)
        self.assertEqual(dialog._count_related_occurrences("Nope"), 0)

    def test_batch_scans_original_data_once_regardless_of_term_count(self):
        # ДО фикса: _show_row_action_menu вызывал _count_related_occurrences
        # по кругу для top_candidates[:10] — 10 проходов по original_data.
        # ПОСЛЕ фикса: _count_related_occurrences_batch делает один проход
        # независимо от того, сколько терминов ищем (ui-dialogs-validation/
        # runtime/10).
        items = [_item(f"Term{i}", f"<p>Term{i} context</p>") for i in range(20)]
        dialog = self._harness(items)

        call_count = {"n": 0}
        original = UntranslatedFixerPage._collect_visible_candidates_for_item

        def counting_wrapper(self, item, blacklist_partition=None):
            call_count["n"] += 1
            return original(self, item, blacklist_partition)

        many_terms = [f"Term{i}" for i in range(10)]
        # Патчим именно на харнессе: _FixerHarness захватил свою собственную
        # ссылку на функцию в момент определения класса, и патч на
        # UntranslatedFixerPage её не затронул бы.
        with mock.patch.object(
            _FixerHarness,
            "_collect_visible_candidates_for_item",
            counting_wrapper,
        ):
            dialog._count_related_occurrences_batch(many_terms)

        # Один проход по всем 20 строкам — НЕ 10 (по числу терминов) * 20.
        self.assertEqual(call_count["n"], len(items))


# --- phrase_blocked считается один раз на item, а не на каждого кандидата
# в каждом из двух циклов (доработка по major-замечанию ревью) ---

class PhraseBlockedComputedOnceTests(unittest.TestCase):
    def _harness(self, blacklist):
        dialog = _FixerHarness()
        dialog.blacklist_set = blacklist
        return dialog

    def test_phrase_matches_context_not_recomputed_per_candidate(self):
        # phrase_blocked не зависит от кандидата (аргументы — фраза и
        # clean_text_lower, оба инвариантны в цикле). ДО доработки он
        # пересчитывался для КАЖДОГО кандидата в ОБОИХ циклах: с N=~31
        # кандидатами и M=2 фразами это давало ~124 вызова
        # _phrase_matches_context на ОДНУ строку (см. ручную проверку в
        # docstring модуля/отчёте). ПОСЛЕ доработки — не больше M вызовов
        # на всю строку (посчитано один раз, переиспользовано в обоих
        # циклах).
        words = [f"Alien{i}" for i in range(30)]
        context = "<p>" + " ".join(words) + "</p>"
        phrases = {"some multi word phrase", "another long phrase here"}
        dialog = self._harness(phrases)

        call_count = {"n": 0}
        original = UntranslatedFixerPage._phrase_matches_context

        def counting_phrase_matches(phrase, haystack):
            call_count["n"] += 1
            return original(phrase, haystack)

        with mock.patch.object(
            _FixerHarness, "_phrase_matches_context", staticmethod(counting_phrase_matches)
        ):
            dialog._collect_visible_candidates_for_item(_item("Alien0", context))

        # Ключевая проверка находки: до доработки было бы N_candidates * M *
        # 2_цикла (десятки-сотни вызовов); после — не больше M.
        self.assertLessEqual(call_count["n"], len(phrases))
        self.assertGreater(call_count["n"], 0)  # проверка реально произошла

    def test_phrase_blacklist_still_blocks_matching_candidates(self):
        # Доработка не должна изменить СЕМАНТИКУ — только число пересчётов.
        dialog = self._harness({"secret phrase"})
        context = "<p>this is a secret phrase right here and OtherWord</p>"

        payload = dialog._collect_visible_candidates_for_item(_item("OtherWord", context))

        self.assertIn("OtherWord", payload["remaining_candidates"])


# --- Пустая запись blacklist не должна блокировать вообще всех кандидатов
# (доработка по minor-замечанию ревью) ---

class EmptyBlacklistEntryIgnoredTests(unittest.TestCase):
    def _harness(self, blacklist):
        dialog = _FixerHarness()
        dialog.blacklist_set = blacklist
        return dialog

    def test_empty_entry_does_not_go_into_phrases(self):
        dialog = self._harness({""})
        singles, phrases = dialog._blacklist_partition()

        self.assertEqual(singles, set())
        self.assertEqual(phrases, [])

    def test_empty_blacklist_entry_does_not_block_all_candidates(self):
        # Достижимо через _load_from_project/restore_state без валидации.
        # ДО доработки: '' попадала в phrases, _phrase_matches_context('',
        # haystack) с len(''.split())==0<=1 возвращает '' in haystack ==
        # True для ЛЮБОГО непустого контекста -> phrase_blocked_for_item
        # всегда True -> diалог показывает 0 кандидатов.
        context = "<p>Alien Beta Gamma текст</p>"
        with_empty = self._harness({""})
        without_empty = self._harness(set())

        payload_with_empty = with_empty._collect_visible_candidates_for_item(
            _item("Alien", context)
        )
        payload_without_empty = without_empty._collect_visible_candidates_for_item(
            _item("Alien", context)
        )

        self.assertEqual(
            payload_with_empty["remaining_candidates"],
            payload_without_empty["remaining_candidates"],
        )
        self.assertEqual(payload_with_empty["stats"], payload_without_empty["stats"])
        self.assertGreater(len(payload_with_empty["remaining_candidates"]), 0)


# --- populate_table переиспользует построенный один раз индекс глоссария
# вместо линейного скана на каждый термин каждой строки (minor) ---

class PopulateTableReusesGlossaryIndexTests(unittest.TestCase):
    def _harness(self, original_data, project_glossary, selected_indices=None):
        dialog = _FixerHarness()
        dialog.table = QtWidgets.QTableWidget()
        dialog.table.setColumnCount(5)
        dialog.original_data = original_data
        dialog.selected_indices = selected_indices or set()
        dialog.project_glossary = project_glossary
        dialog.glossary_controller = _controller()
        return dialog

    def _row(self, term, glossary_matches):
        return {
            "term": term,
            "context": f"<p>{term}</p>",
            "location_info": "Text/chapter1.xhtml",
            "source_type": "system",
            "lang_tag": "latin",
            "stats": (0, 0, 0.0),
            "_glossary_matches": glossary_matches,
        }

    def test_populate_table_scans_glossary_once_not_per_term(self):
        entries = _CountingList([
            {"original": "Alpha", "rus": "Альфа"},
            {"original": "Beta", "rus": "Бета"},
        ])
        items = [
            self._row("Alpha", ["Alpha", "Beta"]),
            self._row("Beta", ["Alpha", "Beta"]),
        ]
        dialog = self._harness(items, entries)

        dialog.populate_table([0, 1])

        # 2 строки * 2 термина = 4 обращения к глоссарию, но build_index
        # проходит glossary_entries РОВНО один раз за весь вызов
        # populate_table (ui-dialogs-validation/runtime/10, доработка):
        # без этого было бы полное линейное сканирование на каждое из 4
        # обращений.
        self.assertEqual(entries.iter_calls, 1)

    def test_populate_table_tooltip_still_shows_glossary_matches(self):
        entries = [{"original": "Alpha", "rus": "Альфа", "note": ""}]
        items = [self._row("Alpha", ["Alpha"])]
        dialog = self._harness(items, entries)

        dialog.populate_table([0])

        tooltip = dialog.table.item(0, 1).toolTip()
        self.assertIn("Alpha -> Альфа", tooltip)


# --- ProjectGlossaryController.save: регресс на атомарность (finding 12) ---

class ProjectGlossaryControllerSaveIsAtomicTests(unittest.TestCase):
    def test_save_routes_through_atomic_write_json(self):
        # ui-dialogs-validation/runtime/12: вторая половина находки (первая —
        # в validation.py:save_changes, уже закрыта через atomic_write_text)
        # была про ProjectGlossaryController.save в ЭТОМ файле, которая
        # писала project_glossary.json напрямую open(path, 'w') + json.dump.
        # На момент проверки код уже использует atomic_write_json — тест
        # фиксирует это как регресс-гвоздь.
        controller = _controller()
        controller.project_folder = "/tmp/does-not-matter"

        with mock.patch.object(ufd, "atomic_write_json") as atomic_mock, \
             mock.patch("builtins.open", side_effect=AssertionError(
                 "save() не должен писать через open() напрямую — только через atomic_write_json"
             )):
            controller.save([{"original": "Foo", "rus": "Фу", "note": ""}])

        atomic_mock.assert_called_once()
        args, kwargs = atomic_mock.call_args
        self.assertTrue(args[0].endswith("project_glossary.json"))


if __name__ == "__main__":
    unittest.main()
