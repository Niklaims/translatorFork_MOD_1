"""Наложения терминов через Ахо–Корасик дают то же, что перебор всех пар.

Раньше GlossaryLogic.find_overlap_groups сравнивал каждую пару терминов —
O(N²), 0,34 с на глоссарии в 4000 терминов при каждом открытии менеджера.
Эталон ниже — прежний перебор дословно. Совпадать должно всё, включая порядок
ключей и элементов: окно наложений показывает группы в этом порядке.
"""

from __future__ import annotations

from collections import defaultdict

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gemini_translator.utils.language_tools import GlossaryLogic, _glossary_text
from gemini_translator.utils.substring_index import contained_terms

# Маленький алфавит — много вложений; иероглифы, латиница, пробел и знаки.
_ALPHABET = "林峰主王ab c-'"


def _reference(glossary_list):
    terms_set = {_glossary_text(e.get('original')) for e in glossary_list if _glossary_text(e.get('original'))}
    groups, inverted = defaultdict(list), defaultdict(list)
    terms = sorted(list(terms_set), key=len)
    for i in range(len(terms)):
        for j in range(i + 1, len(terms)):
            if terms[i] in terms[j]:
                groups[terms[i]].append(terms[j])
                inverted[terms[j]].append(terms[i])
    return groups, inverted


def _ordered(mapping):
    return [(key, list(values)) for key, values in mapping.items()]


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.text(alphabet=_ALPHABET, min_size=0, max_size=7), max_size=40))
def test_overlaps_match_the_pairwise_reference(originals):
    glossary = [{"original": original, "rus": "", "note": ""} for original in originals]

    groups, inverted = GlossaryLogic().find_overlap_groups(glossary)
    expected_groups, expected_inverted = _reference(glossary)

    assert _ordered(groups) == _ordered(expected_groups)
    assert _ordered(inverted) == _ordered(expected_inverted)


def test_contained_terms_lists_every_inner_term_once_in_index_order():
    terms = ["a", "ab", "b", "abab", "ba"]

    assert contained_terms(terms) == [[], [0, 2], [], [0, 1, 2, 4], [0, 2]]
