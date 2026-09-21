# -*- coding: utf-8 -*-
"""Самый частый повтор короткого фрагмента в тексте главы.

Окно проверки ищет зацикленный ответ модели регуляркой ``(.{N})\\1{4,}`` для
каждой длины N от 20 до 1. На обычной главе совпадений почти никогда нет, и
каждая регулярка проходила текст целиком впустую — треть времени анализа.

Совпадение для длины N есть тогда и только тогда, когда найдутся 4N подряд
позиций j с ``text[j] == text[j + N]``. Это проверяется в C: кодовые точки —
32-битные группы большого целого, сдвиг на N групп и XOR дают нулевую группу
на каждой такой позиции, и остаётся найти строку нулевых байтов. Строка может
лечь не по границе групп и дать ложное «может быть» — тогда решает сама
регулярка. Ложного «не может» не бывает, поэтому результат прежний.
"""

import re

MIN_REPS = 5
MAX_PATTERN_LEN = 20


def _repeat_prefilter(text, required_extra):
    """Проверка «может ли найтись ``(.{N})\\1{required_extra,}``» для любых N."""
    encoded = text.encode("utf-32-le", "surrogatepass")
    value = int.from_bytes(encoded, "little")
    size = len(encoded)
    length = len(text)

    def may_repeat(pattern_len):
        # j + N должно оставаться внутри текста: сравниваем только первые
        # length - N групп, в остальные сдвиг вписал нули.
        compared = length - pattern_len
        if compared < pattern_len * required_extra:
            return False
        differences = (value ^ (value >> (32 * pattern_len))).to_bytes(size, "little")
        zero_run = b"\x00" * (4 * pattern_len * required_extra)
        return differences.find(zero_run, 0, 4 * compared) != -1

    return may_repeat


def find_most_repeated_pattern(text, min_reps=MIN_REPS, max_pattern_len=MAX_PATTERN_LEN):
    """Фрагмент длиной до ``max_pattern_len``, повторённый подряд больше всего раз.

    Возвращает ``(фрагмент, число_повторов, длина_фрагмента_1)`` или None.
    Для каждой длины берётся первое вхождение; пробельный фрагмент считается,
    только если он повторён не меньше 50 раз. Длины перебираются от большей к
    меньшей, при равенстве выигрывает более длинный фрагмент.
    """
    required_extra = max(1, min_reps - 1)
    may_repeat = _repeat_prefilter(text, required_extra)

    best_repeat_candidate = None
    max_reps_found = 0
    for pattern_len in range(max_pattern_len, 0, -1):
        if not may_repeat(pattern_len):
            continue
        regex = re.compile(r"(.{" + str(pattern_len) + r"})\1{" + str(required_extra) + r",}", re.DOTALL)
        match = regex.search(text)
        if not match:
            continue
        full_sequence = match.group(0)
        repeated_pattern = match.group(1)

        # Обычные пробельные отступы не в счёт, если их не экстремально много.
        if repeated_pattern.strip() == "" and len(full_sequence) // len(repeated_pattern) < 50:
            continue

        actual_count = len(full_sequence) // len(repeated_pattern)
        # Точка, повторённая 100 раз, важнее тега, повторённого 6 раз.
        if actual_count > max_reps_found:
            max_reps_found = actual_count
            best_repeat_candidate = (repeated_pattern, actual_count, pattern_len == 1)

    return best_repeat_candidate
