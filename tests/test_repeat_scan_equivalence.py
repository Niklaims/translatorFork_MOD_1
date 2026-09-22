"""Поиск повторов в главе: быстрый путь даёт ровно прежний результат.

Прежде окно проверки гоняло по главе 20 регулярок `(.{N})\\1{4,}`, и каждая
почти всегда проходила текст целиком впустую — треть времени анализа. Теперь
регулярка запускается, только если в тексте есть 4N подряд позиций с
text[j] == text[j+N]: без них совпадения быть не может. Эталон ниже — прежний
цикл дословно.
"""

from __future__ import annotations

import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gemini_translator.utils.repeat_scan import find_most_repeated_pattern


def _reference(translated_content):
    """Прежний блок «5. Повторы» из ValidationThread._analyze_html_content."""
    min_reps_scan = 5
    max_pattern_len = 20

    best_repeat_candidate = None
    max_reps_found = 0

    for pattern_len in range(max_pattern_len, 0, -1):
        required_extra = max(1, min_reps_scan - 1)
        try:
            regex = re.compile(r'(.{' + str(pattern_len) + r'})\1{' + str(required_extra) + r',}', re.DOTALL)
            match = regex.search(translated_content)
            if match:
                full_sequence = match.group(0)
                repeated_pattern = match.group(1)

                if repeated_pattern.strip() == "" and len(full_sequence) // len(repeated_pattern) < 50:
                    continue

                actual_count = len(full_sequence) // len(repeated_pattern)

                if actual_count > max_reps_found:
                    max_reps_found = actual_count
                    best_repeat_candidate = (repeated_pattern, actual_count, pattern_len == 1)
        except re.error:
            continue

    return best_repeat_candidate


_UNITS = ["a", "b", "ab", "abc", " ", "  ", "\n", "Жр", "林", "<p>", "</p>", "!", ".", "\x00", "\ud800"]


@st.composite
def _texts(draw):
    parts = []
    for _ in range(draw(st.integers(min_value=0, max_value=8))):
        unit = draw(st.sampled_from(_UNITS))
        if draw(st.booleans()):
            unit = unit * draw(st.integers(min_value=1, max_value=60))
        parts.append(unit)
    return "".join(parts)


@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_texts())
def test_matches_the_twenty_regex_scan(text):
    assert find_most_repeated_pattern(text) == _reference(text)


def test_long_whitespace_run_counts_only_past_fifty():
    assert find_most_repeated_pattern(" " * 49) is None
    assert find_most_repeated_pattern(" " * 60) == _reference(" " * 60)


def test_degenerate_model_loop_is_reported():
    text = "<p>Начало.</p>" + "Он пошёл дальше. " * 12 + "<p>Конец.</p>"

    assert find_most_repeated_pattern(text) == _reference(text)
    assert find_most_repeated_pattern(text)[1] >= 5
