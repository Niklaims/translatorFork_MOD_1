# -*- coding: utf-8 -*-
"""Регресс на perf:cpu-hotpaths/3-term-frequency-substring-casca.

aggregate_term_frequency_stats раньше для КАЖДОГО найденного термина
перебирала ВЕСЬ глоссарий (`for sub_term in glossary_terms: if sub_term in
found_term`) — O(T) операций `in` на каждый найденный термин, то есть до
O(T^2) на анализ книги. Тест проверяет алгоритмическое свойство: число
обращений к `str.__contains__` на найденном термине не должно расти вместе
с размером глоссария (было — росло линейно с T на каждый найденный термин;
стало — не должно расти вовсе, так как индекс строится один раз и найденный
термин лишь обходится посимвольно).
"""

import random
import unittest

from gemini_translator.utils.term_frequency_tools import (
    aggregate_term_frequency_stats,
    collect_glossary_originals,
)


def _reference_aggregate(glossary_source, term_occurrences, term_distribution):
    """Эталонная (старая, заведомо корректная) реализация — прямой перебор.

    Используется только в тестах для сверки результата после перехода на
    Ахо-Корасик индекс: поведение должно совпадать буквально."""
    glossary_terms = collect_glossary_originals(glossary_source)

    result_counts = {term: int(term_occurrences.get(term, 0)) for term in glossary_terms}
    result_files = {term: set(term_distribution.get(term, set())) for term in glossary_terms}

    for found_term, found_count in term_occurrences.items():
        found_count = int(found_count or 0)
        if found_count <= 0:
            continue
        found_files = set(term_distribution.get(found_term, set()))
        for sub_term in glossary_terms:
            if len(sub_term) >= len(found_term):
                continue
            if sub_term in found_term:
                result_counts[sub_term] = result_counts.get(sub_term, 0) + found_count
                result_files.setdefault(sub_term, set()).update(found_files)

    return {
        term: {
            "count": int(result_counts.get(term, 0)),
            "files": sorted(result_files.get(term, set())),
        }
        for term in glossary_terms
    }


class _CountingStr(str):
    """Строка, считающая обращения к `__contains__` (т.е. `x in этот_объект`)."""

    calls = 0

    def __contains__(self, other):
        _CountingStr.calls += 1
        return str.__contains__(self, other)


class AggregateTermFrequencySubstringIndexTests(unittest.TestCase):
    def setUp(self):
        _CountingStr.calls = 0

    def _run(self, glossary_size):
        # Один найденный термин длиной 12 символов; остальной глоссарий —
        # заведомо более короткие термины, которые в старом коде все до
        # единого проверяются оператором `in` на found_term.
        found_term = _CountingStr("found_term12")
        glossary_terms = [f"g{i}" for i in range(glossary_size)]

        glossary_source = [{"original": term} for term in glossary_terms + [str(found_term)]]
        term_occurrences = {found_term: 3}
        term_distribution = {found_term: {"chapter1.xhtml"}}

        return aggregate_term_frequency_stats(glossary_source, term_occurrences, term_distribution)

    def test_contains_call_count_does_not_grow_with_glossary_size(self):
        self._run(glossary_size=50)
        calls_small = _CountingStr.calls

        _CountingStr.calls = 0
        self._run(glossary_size=2000)
        calls_large = _CountingStr.calls

        # Раньше: calls_small == 50, calls_large == 2000 (растёт линейно с T
        # на один найденный термин, то есть O(T) на found_term и O(T^2) на
        # книгу). После фикса количество обращений к `in` на found_term не
        # должно зависеть от размера глоссария вовсе.
        self.assertEqual(
            calls_large,
            calls_small,
            "число проверок `in` на найденном термине не должно расти с размером глоссария",
        )

    def test_nested_substring_counts_match_previous_direct_scan_semantics(self):
        # "Cat" — подстрока и "Category", и "Catalog"; "Category" не подстрока
        # "Catalog" и наоборот; "Dog" ни с чем не пересекается.
        glossary_source = [
            {"original": "Category"},
            {"original": "Catalog"},
            {"original": "Cat"},
            {"original": "Dog"},
        ]
        term_occurrences = {"Category": 3, "Catalog": 2, "Cat": 1, "Dog": 5}
        term_distribution = {
            "Category": {"ch1.xhtml"},
            "Catalog": {"ch2.xhtml"},
            "Cat": {"ch3.xhtml"},
            "Dog": {"ch4.xhtml"},
        }

        result = aggregate_term_frequency_stats(glossary_source, term_occurrences, term_distribution)

        self.assertEqual(result["Category"]["count"], 3)
        self.assertEqual(result["Catalog"]["count"], 2)
        # 1 (свой счётчик) + 3 (из Category) + 2 (из Catalog)
        self.assertEqual(result["Cat"]["count"], 6)
        self.assertEqual(result["Dog"]["count"], 5)
        self.assertEqual(result["Cat"]["files"], ["ch1.xhtml", "ch2.xhtml", "ch3.xhtml"])

    def test_matches_reference_direct_scan_on_randomized_glossaries(self):
        rng = random.Random(20260913)
        alphabet = "abc"

        for _ in range(30):
            term_count = rng.randint(1, 12)
            terms = sorted({
                "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 6)))
                for _ in range(term_count)
            })
            if not terms:
                continue

            glossary_source = [{"original": term} for term in terms]
            term_occurrences = {
                term: rng.randint(0, 5) for term in terms if rng.random() < 0.8
            }
            term_distribution = {
                term: {f"file_{i}.xhtml" for i in range(rng.randint(0, 2))}
                for term in term_occurrences
            }

            expected = _reference_aggregate(glossary_source, term_occurrences, term_distribution)
            actual = aggregate_term_frequency_stats(glossary_source, term_occurrences, term_distribution)
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
