"""Помощник недопереводов собирает контексты за один обход главы.

Прежде для каждого недопереведённого слова дерево главы обходилось заново
(find_all(string=шаблон)): на 65 помеченных главах это треть открытия окна.
Эталон ниже — прежний сбор дословно; совпадать должно всё: контексты, места,
порядок групп и вхождений, сами узлы.
"""

from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from bs4 import BeautifulSoup, Comment, Declaration, ProcessingInstruction
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from PyQt6 import QtWidgets

from gemini_translator.ui.dialogs.validation import TranslationValidatorPage

_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _reference_collect(results_data):
    """Прежний _collect_untranslated_fixer_payload (без ветки show_feedback)."""
    grouped_data_map = {}
    soup_cache = {}
    processed_containers_ids = set()

    inline_tags = {
        'span', 'a', 'strong', 'em', 'b', 'i', 'u', 'font',
        'small', 'big', 'sub', 'sup', 'strike', 'code', 'var', 'cite'
    }
    safe_blocks = {
        'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'li', 'dt', 'dd', 'blockquote', 'pre', 'caption', 'figcaption', 'td', 'th', 'label'
    }
    dangerous_roots = {'body', 'html', 'main', '[document]'}

    for row_index, result_data in results_data.items():
        internal_path = result_data.get('internal_html_path')
        if result_data.get('status') == 'retry':
            continue
        if 'untranslated_words' not in result_data:
            continue
        soup_cache[row_index] = BeautifulSoup(result_data['translated_html'], 'html.parser')
        soup = soup_cache[row_index]
        for term in result_data['untranslated_words']:
            term_pattern = re.compile(re.escape(term), re.IGNORECASE)
            for node in soup.find_all(string=term_pattern):
                if not node.parent:
                    continue
                if isinstance(node, (ProcessingInstruction, Comment, Declaration)):
                    continue
                if node.find_parent(['head', 'script', 'style', 'title']):
                    continue
                effective_container = node.parent
                while effective_container and effective_container.name in inline_tags:
                    if effective_container.parent:
                        effective_container = effective_container.parent
                    else:
                        break
                container_name = effective_container.name
                if container_name in dangerous_roots:
                    use_orphan_mode = True
                elif container_name in safe_blocks:
                    use_orphan_mode = False
                else:
                    use_orphan_mode = any(
                        getattr(child, 'name', None) in safe_blocks.union({'div', 'section', 'article', 'table', 'ul', 'ol'})
                        for child in effective_container.children
                    )
                if use_orphan_mode:
                    target_object, context_text = node, str(node).strip()
                    location_desc, is_orphan_flag = f"Текст-сирота (в <{container_name}>)", True
                else:
                    target_object = effective_container
                    context_text = "".join(str(child) for child in effective_container.contents).strip()
                    location_desc, is_orphan_flag = f"Тег <{container_name}>", False
                if not context_text:
                    continue
                if len(context_text) > 2000:
                    target_object = node
                    context_text = str(node).strip()
                    if len(context_text) > 2000:
                        context_text = context_text[:100] + "..."
                    location_desc = f"Текст-сирота (слишком большой блок <{container_name}>)"
                    is_orphan_flag = True
                    if not context_text:
                        continue
                if id(target_object) in processed_containers_ids:
                    continue
                processed_containers_ids.add(id(target_object))
                group = grouped_data_map.setdefault(context_text, {
                    'term': term, 'context': context_text, 'location_info': location_desc,
                    'occurrences': [], 'source_type': 'system', 'internal_html_path': internal_path,
                })
                group['occurrences'].append({
                    'target': target_object, 'is_orphan': is_orphan_flag,
                    'row_index': row_index, 'internal_html_path': internal_path,
                })
    if not grouped_data_map:
        return [], {}
    return list(grouped_data_map.values()), soup_cache


class _PageStub:
    """Настоящий метод сбора на лёгкой странице (метод — атрибут класса)."""

    _collect_untranslated_fixer_payload = TranslationValidatorPage._collect_untranslated_fixer_payload

    def __init__(self, results_data):
        self.results_data = results_data

    def _ensure_row_translated_html_loaded(self, row_index):
        return self.results_data[row_index]['translated_html']


def _normalized(items, soup_cache):
    return (
        [
            (
                item['term'], item['context'], item['location_info'], item['source_type'],
                item['internal_html_path'],
                [
                    (type(o['target']).__name__, str(o['target']), o['is_orphan'], o['row_index'], o['internal_html_path'])
                    for o in item['occurrences']
                ],
            )
            for item in items
        ],
        {row: str(soup) for row, soup in soup_cache.items()},
    )


_PIECES = [
    "<p>", "</p>", "<div>", "</div>", "<span>", "</span>", "<b>", "</b>", "<em>", "</em>",
    "<li>", "</li>", "<ul>", "</ul>", "<td>", "</td>", "<section>", "</section>",
    "<!-- Lin Feng -->", "<script>Lin()</script>", "<style>.Feng{}</style>",
    "<head><title>Lin Feng</title></head>", "<h2>", "</h2>",
    "Lin", " Feng", "林峰", " текст ", "Sect", " master", "\n",
]
_TERMS = ["Lin", "Feng", "Lin Feng", "林峰", "sect", "Master", "zz"]


@st.composite
def _results(draw):
    rows = {}
    for row in range(draw(st.integers(min_value=1, max_value=3))):
        body = "".join(draw(st.lists(st.sampled_from(_PIECES), max_size=40)))
        data = {'internal_html_path': f"Text/ch{row}.xhtml", 'translated_html': f"<html><body>{body}</body></html>"}
        if draw(st.booleans()):
            data['untranslated_words'] = draw(st.lists(st.sampled_from(_TERMS), min_size=1, max_size=4, unique=True))
        if draw(st.integers(min_value=0, max_value=5)) == 0:
            data['status'] = 'retry'
        rows[row] = data
    return rows


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_results())
def test_single_pass_collects_exactly_what_the_per_term_scan_did(results_data):
    items, soup_cache = _PageStub(results_data)._collect_untranslated_fixer_payload(show_feedback=False)
    expected_items, expected_cache = _reference_collect(results_data)

    assert _normalized(items, soup_cache) == _normalized(expected_items, expected_cache)
