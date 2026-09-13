"""Итоговый проход в конце сессии должен называть причину, по которой главы не проверены."""

from gemini_translator.core.chapter_qa_coordinator import BookQaResult
from gemini_translator.core.translation_engine import TranslationEngine


def _engine(events):
    engine = TranslationEngine.__new__(TranslationEngine)
    engine._post_event = lambda name, data=None: events.append((name, data or {}))
    engine._check_if_session_finished = lambda: events.append(("finished-check", {}))
    return engine


def _messages(events):
    return [data.get("message", "") for name, data in events if name == "log_message"]


def test_final_pass_summary_says_the_rest_waits_for_keys():
    events = []

    _engine(events)._on_final_qa_finished(
        BookQaResult(
            skipped=("chapter-2", "chapter-3"), stopped=("chapter-2", "chapter-3")
        ),
        None,
    )

    (message,) = _messages(events)
    assert "Ключи для проверки больше недоступны" in message
    assert "не проверено глав: 2" in message
    assert ("finished-check", {}) in events


def test_final_pass_summary_without_a_key_stop_is_unchanged():
    events = []

    _engine(events)._on_final_qa_finished(BookQaResult(skipped=("chapter-1",)), None)

    assert _messages(events) == ["[QA] Итоговый проход завершён, проверено глав: 0."]
