# -*- coding: utf-8 -*-
"""Какие строки набора входят в другие строки того же набора.

Без зависимостей: модуль нужен language_tools, а тот импортируют почти все
(term_frequency_tools со своим Ахо–Корасиком сам импортирует language_tools
и PyQt6, поэтому общий индекс живёт отдельно).
"""

from collections import deque


def contained_terms(terms):
    """Для каждой строки ``terms`` — индексы других строк набора, которые в неё
    входят как подстроки, по возрастанию индекса.

    Ахо–Корасик по всему набору: один проход по каждой строке вместо сравнения
    всех пар (перебор на глоссарии в 4000 терминов — 0,34 с). Строки набора
    должны быть непустыми и разными.
    """
    children = [{}]
    ends = [-1]  # индекс строки, которая кончается в узле
    for index, term in enumerate(terms):
        node = 0
        for char in term:
            child = children[node].get(char)
            if child is None:
                child = len(children)
                children.append({})
                ends.append(-1)
                children[node][char] = child
            node = child
        ends[node] = index

    fail = [0] * len(children)
    # Ближайший по цепочке fail узел, где кончается строка набора, либо -1.
    next_end = [-1] * len(children)
    queue = deque(children[0].values())
    while queue:
        node = queue.popleft()
        for char, child in children[node].items():
            state = fail[node]
            while state and char not in children[state]:
                state = fail[state]
            candidate = children[state].get(char, 0)
            fail[child] = candidate if candidate != child else 0
            target = fail[child]
            next_end[child] = target if ends[target] >= 0 else next_end[target]
            queue.append(child)

    result = []
    for index, term in enumerate(terms):
        found = set()
        node = 0
        for char in term:
            while node and char not in children[node]:
                node = fail[node]
            node = children[node].get(char, 0)
            hit = node if ends[node] >= 0 else next_end[node]
            while hit != -1:
                found.add(ends[hit])
                hit = next_end[hit]
        found.discard(index)
        result.append(sorted(found))
    return result
