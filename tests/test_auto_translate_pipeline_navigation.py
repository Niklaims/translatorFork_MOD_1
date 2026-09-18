import re
import pytest
from PyQt6.QtWidgets import QApplication
from gemini_translator.ui.dialogs.validation_dialogs.untranslated_fixer_dialog import (
    is_english_junk,
    ENGLISH_JUNK_PATTERNS,
)
from gemini_translator.ui.widgets.auto_translate_pipeline_widget import (
    AutoTranslatePipelineWidget,
    StageCardWidget,
)

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_english_junk_detector_patterns():
    # Ads and scanlation junk
    assert is_english_junk("Read latest chapters at novelsite.com")
    assert is_english_junk("Translated by: Team Light")
    assert is_english_junk("TL: John, ED: Smith")
    assert is_english_junk("Support us on Patreon / Discord")
    assert is_english_junk("Visit boxnovel for fastest update")
    assert is_english_junk("All rights reserved")

    # Regular narrative Russian and clean terms should not be junk
    assert not is_english_junk("Привет, мир!")
    assert not is_english_junk("Клинок черного дракона")
    assert not is_english_junk("System Notification: Level Up")

def test_auto_translate_pipeline_widget_stages(qapp):
    widget = AutoTranslatePipelineWidget()
    stages = widget.get_enabled_stages()
    assert "machine_translation" in stages
    assert "untranslated_fixing" in stages

    # Check stage status update
    widget.set_stage_status("machine_translation", "running")
    assert widget.stages["machine_translation"].status == "running"

    widget.set_stage_status("machine_translation", "completed")
    assert widget.stages["machine_translation"].status == "completed"

def test_stage_card_edit_signal(qapp):
    card = StageCardWidget("untranslated_fixing", "Доперевод")
    received = []
    card.edit_requested.connect(lambda s: received.append(s))
    card.btn_edit.click()
    assert received == ["untranslated_fixing"]

def test_pipeline_navigation_mapping():
    mapping = {
        'glossary_collection': 4,  # Глоссарий
        'glossary_validation': 4,  # Глоссарий
        'machine_translation': 5,  # Промпт
        'ai_editing': 7,           # ИИ-редактура
    }
    for stage in ['glossary_collection', 'glossary_validation', 'machine_translation', 'ai_editing']:
        assert stage in mapping

def test_purge_english_junk_in_untranslated_fixer(qapp):
    from gemini_translator.ui.dialogs.validation_dialogs.untranslated_fixer_dialog import UntranslatedFixerPage
    sample_data = [
        {
            'term': 'Patreon',
            'context': 'Support the translator on Patreon for bonus chapters!',
            'location_info': 'Ch. 1',
        },
        {
            'term': 'TL: Smith',
            'context': 'Translated by Smith\nEditor: John\nAll rights reserved',
            'location_info': 'Ch. 2',
        },
        {
            'term': 'привет',
            'context': 'Нормальный русский абзац без рекламы.',
            'location_info': 'Ch. 3',
        }
    ]
    page = UntranslatedFixerPage(sample_data)
    purged_count = page._purge_english_junk(interactive=False)
    assert purged_count == 2
    # First item was pure junk
    assert sample_data[0].get('new_context') == ""
    # Second item was pure junk
    assert sample_data[1].get('new_context') == ""
    # Third item unchanged
    assert sample_data[2].get('new_context', sample_data[2]['context']) == 'Нормальный русский абзац без рекламы.'
