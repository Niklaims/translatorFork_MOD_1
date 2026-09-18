# -*- coding: utf-8 -*-
"""Регресс для minor-замечания рецензента (группа ui_dialogs_validation_b,
часть находки ui-dialogs-validation/runtime/7-fixer-soup-cache-whole-book-me).

_collect_untranslated_fixer_payload клал в каждый occurrences-словарь ключ
'soup_ref' со ссылкой на весь bs4-документ главы -- при этом ни одно место в
дереве кода это поле не читало (единственное попадание в grep было само
присваивание). Мёртвая лишняя ссылка на дерево, дословно упомянутая в
находке как одна из живых ссылок, удерживающих bs4-деревья в памяти.

Тест привязывает НАСТОЯЩЕЕ тело _collect_untranslated_fixer_payload к
минимальному объекту и проверяет, что occurrences не содержат 'soup_ref'.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from gemini_translator.ui.dialogs.validation import TranslationValidatorPage as P


_APP = QApplication.instance() or QApplication([])


class _Harness(QWidget):
    _collect_untranslated_fixer_payload = P._collect_untranslated_fixer_payload

    def __init__(self, results_data):
        super().__init__()
        self.results_data = results_data

    def _ensure_row_translated_html_loaded(self, row_idx):
        return self.results_data[row_idx]['translated_html']


def test_occurrences_do_not_carry_dead_soup_ref_field():
    harness = _Harness({
        0: {
            'internal_html_path': 'Text/chapter1.xhtml',
            'translated_html': '<html><body><p>Он сказал Hello миру.</p></body></html>',
            'untranslated_words': ['Hello'],
            'status': 'neutral',
        },
    })

    system_items, soup_cache = harness._collect_untranslated_fixer_payload(show_feedback=False)

    assert system_items, "payload должен был найти контекст с термином Hello"
    assert 0 in soup_cache, "soup_cache по-прежнему должен кэшировать дерево по row_index"
    for item in system_items:
        for occurrence in item['occurrences']:
            assert 'soup_ref' not in occurrence, (
                "occurrences не должны хранить лишнюю ссылку 'soup_ref' на "
                "bs4-дерево -- она нигде не читается, а soup доступен через "
                "soup_cache[row_index]"
            )
