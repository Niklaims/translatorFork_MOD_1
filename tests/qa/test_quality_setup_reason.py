"""The quality window says why a check could not be built, not that it is off."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication

from gemini_translator.ui.dialogs.validation import TranslationValidatorPage


class _ProjectManagerStub:
    project_folder = "/tmp/project"


class _SettingsManager:
    def get_qa_settings(self):
        return object()

    def load_proxy_settings(self):
        return {}

    def load_key_statuses(self):
        return [{"provider": "gemini", "key": "key-1"}]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qt_app):
    # The page reads the application's version, which the running app sets.
    if not hasattr(qt_app, "global_version"):
        qt_app.global_version = ""
    with patch.object(TranslationValidatorPage, "_perform_initial_cjk_scan"):
        page = TranslationValidatorPage(
            "/tmp/nonexistent-translations",
            "/tmp/nonexistent-book.epub",
            project_manager=_ProjectManagerStub(),
        )
    # The constructor schedules a table fill that would fire inside another test.
    timer = getattr(page, "_populate_initial_table_timer", None)
    if timer is not None:
        timer.stop()
    had_coordinator = hasattr(qt_app, "qa_coordinator")
    previous = getattr(qt_app, "qa_coordinator", None)
    qt_app.qa_coordinator = None
    page._quality_settings_manager = lambda: _SettingsManager()
    yield page
    if had_coordinator:
        qt_app.qa_coordinator = previous
    elif hasattr(qt_app, "qa_coordinator"):
        delattr(qt_app, "qa_coordinator")
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _assembly(attach):
    return patch.multiple(
        "gemini_translator.qa.assembly",
        resolve_manual_qa_model=lambda settings_manager, qa_settings: ("gemini", "gemini-model"),
        green_keys=lambda settings_manager, provider, model: ["key-1"],
        aiohttp_session_factory=lambda proxy: (lambda: None),
        detect_source_language=lambda text: "en",
        manual_session_settings=lambda settings_manager, proxy: object(),
        embedding_keys_for_session=lambda provider, keys: {},
        attach_chapter_qa_coordinator=attach,
    ), patch(
        "gemini_translator.qa.handler_factory.build_qa_handler_factory",
        lambda **kwargs: (lambda *args, **options: None),
    )


def test_the_window_names_the_reason_the_check_was_not_built(qt_app, page):
    """«Проверка выключена целиком» висела и тогда, когда сломан был журнал книги."""

    def attach(app, **kwargs):
        report = kwargs.get("on_unavailable")
        if report is not None:
            report("Журнал проверки книги повреждён: Expecting value")
        return None

    assembly_patch, handler_patch = _assembly(attach)
    with assembly_patch, handler_patch:
        coordinator = page._build_manual_quality_coordinator(qt_app)

    assert coordinator is None
    assert page._quality_setup_problem == "Журнал проверки книги повреждён: Expecting value"


def test_a_refusal_without_a_reason_does_not_claim_the_check_is_off(qt_app, page):
    assembly_patch, handler_patch = _assembly(lambda app, **kwargs: None)
    with assembly_patch, handler_patch:
        page._build_manual_quality_coordinator(qt_app)

    assert page._quality_setup_problem == "Проверка сейчас недоступна."
