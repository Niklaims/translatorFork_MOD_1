"""The quality section must show the report and never act on a stale selection."""

from __future__ import annotations

import json
import os
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from gemini_translator.qa.capabilities import QaCapabilitySettings
from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import ChapterMetrics, QaJournalEntry, RiskLevel
from gemini_translator.qa.settings import QaSettings
from gemini_translator.ui.dialogs.validation_dialogs import (
    BookQaReportSnapshot,
    ChapterQaTableModel,
    TranslationQualityDialog,
    translation_quality_dialog as dialog_module,
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _journal(repaired: bool = True) -> QaJournal:
    journal = QaJournal.empty(book_id="book-1")
    for index in range(6):
        journal.upsert_metrics(
            ChapterMetrics(
                chapter_id=f"chapter-{index}",
                source_language="zh",
                target_language="ru",
                source_chars=1000,
                translated_chars=2900 + index * 20,
                possible_gaps=index % 2,
                glossary_conflicts=index % 3,
                risk_level=RiskLevel.MEDIUM if index % 2 else RiskLevel.LOW,
            )
        )
    if repaired:
        journal.append(
            QaJournalEntry(entry_id="e1", chapter_id="chapter-1", decision="fixed")
        )
        journal.append_repair({"patch_id": "p1", "chapter_id": "chapter-1"})
    return journal


class _Gate:
    def __init__(self, chapter_id: str, reason: str) -> None:
        self.chapter_id = chapter_id
        self.reason = reason


def _dialog(qt_app, **kwargs) -> TranslationQualityDialog:
    dialog = TranslationQualityDialog(**kwargs)
    dialog.set_report(BookQaReportSnapshot.from_journal(_journal()))
    return dialog


def test_dialog_exposes_the_four_actions(qt_app):
    """The user must find exactly the four documented actions, by name."""
    dialog = _dialog(qt_app)

    assert dialog.check_chapter_button.text() == "Проверить и исправить главу"
    assert dialog.check_all_button.text() == "Проверить и исправить все главы"
    assert dialog.undo_chapter_button.text() == "Отменить исправления главы"
    assert (
        dialog.undo_all_button.text()
        == "Отменить все автоматические исправления"
    )


def test_a_running_check_disables_conflicting_actions(qt_app):
    """Two overlapping passes over one book would fight over the same files."""
    dialog = _dialog(qt_app)
    dialog.select_chapter("chapter-1")

    dialog.set_busy(True)
    assert not dialog.check_all_button.isEnabled()
    assert not dialog.check_chapter_button.isEnabled()
    assert not dialog.undo_all_button.isEnabled()
    assert dialog.cancel_button.isEnabled()

    dialog.set_busy(False)
    assert dialog.check_all_button.isEnabled()
    assert dialog.check_chapter_button.isEnabled()
    assert not dialog.cancel_button.isEnabled()


def test_actions_require_the_state_they_act_on(qt_app):
    """Undo must be offered only where an automatic repair actually exists."""
    dialog = _dialog(qt_app)

    dialog.select_chapter("chapter-0")
    assert dialog.check_chapter_button.isEnabled()
    assert not dialog.undo_chapter_button.isEnabled()

    dialog.select_chapter("chapter-1")
    assert dialog.undo_chapter_button.isEnabled()


def test_selecting_a_chapter_shows_its_decisions(qt_app):
    """A row is only useful with the reasoning behind it."""
    dialog = _dialog(qt_app)

    dialog.select_chapter("chapter-1")
    details = dialog.details.toPlainText()

    assert "chapter-1" in details
    assert "zh → ru" in details
    assert "Исправлено" in details


def test_report_summary_names_blocked_chapters(qt_app):
    """A stopped translation must be visible without opening a row."""
    dialog = _dialog(qt_app)
    snapshot = BookQaReportSnapshot.from_journal(
        _journal(), open_gates=[_Gate("chapter-3", "подтверждённый пропуск")]
    )

    dialog.set_report(snapshot)

    assert snapshot.blocked_chapters == ("chapter-3",)
    assert "chapter-3" in dialog.summary_label.text()
    dialog.select_chapter("chapter-3")
    assert "подтверждённый пропуск" in dialog.details.toPlainText()


def test_check_chapter_emits_the_selected_chapter(qt_app):
    """The action must apply to what the user has selected, or to nothing."""
    dialog = _dialog(qt_app)
    seen: list[str] = []
    dialog.check_chapter_requested.connect(seen.append)

    dialog._request_check_chapter()
    assert seen == []

    dialog.select_chapter("chapter-2")
    dialog._request_check_chapter()
    assert seen == ["chapter-2"]


def test_embedding_provider_choice_offers_its_own_models_and_key(qt_app):
    """The user picks the embedding key and model, not the translation session."""
    dialog = _dialog(
        qt_app,
        api_keys=[
            {"key": "AIzaSy-gemini-key-value", "provider": "gemini"},
            {"key": "sk-openai-key-value", "provider": "openai"},
        ],
    )

    dialog.embedding_provider_combo.setCurrentIndex(
        dialog.embedding_provider_combo.findData("openai_compatible")
    )
    models = [
        dialog.embedding_model_combo.itemText(index)
        for index in range(dialog.embedding_model_combo.count())
    ]
    assert "text-embedding-3-small" in models
    assert dialog.embedding_base_url_edit.isEnabled()

    dialog.embedding_key_combo.setCurrentIndex(
        dialog.embedding_key_combo.findData("sk-openai-key-value")
    )
    dialog.embedding_base_url_edit.setText("https://api.openai.com/v1")
    dialog.embedding_model_combo.setEditText("text-embedding-3-large")
    settings = dialog.qa_settings()

    assert settings.embedding_provider == "openai_compatible"
    assert settings.embedding_api_key == "sk-openai-key-value"
    assert settings.embedding_base_url == "https://api.openai.com/v1"
    assert settings.embedding_model == "text-embedding-3-large"
    assert settings.embedding_setup_problem() == ""


def test_incomplete_embedding_setup_is_explained_not_silently_accepted(qt_app):
    """Choosing a provider without a key must say so before a session starts."""
    dialog = _dialog(qt_app)

    dialog.embedding_provider_combo.setCurrentIndex(
        dialog.embedding_provider_combo.findData("gemini")
    )

    assert "ключ" in dialog.embedding_status_label.text().lower()
    assert dialog.qa_settings().embedding_setup_problem() != ""


def test_keys_are_never_shown_in_full(qt_app):
    """A dropdown of API keys must stay unreadable over someone's shoulder."""
    dialog = _dialog(
        qt_app, api_keys=[{"key": "AIzaSy-super-secret-key", "provider": "gemini"}]
    )

    labels = [
        dialog.embedding_key_combo.itemText(index)
        for index in range(dialog.embedding_key_combo.count())
    ]

    assert all("super-secret" not in label for label in labels)
    assert any("…" in label for label in labels)


def test_stage_switches_round_trip_through_the_dialog(qt_app):
    """The dialog is the only place to turn quality control off; it must work."""
    dialog = _dialog(
        qt_app,
        settings=QaSettings(
            check_completeness_after_chapter=False,
            auto_repair_confirmed_omissions=False,
            capabilities=QaCapabilitySettings(slovnet_enabled=True),
        ),
    )

    assert dialog.completeness_check.isChecked() is False
    assert dialog.repair_omissions_check.isChecked() is False
    settings = dialog.qa_settings()
    assert settings.check_completeness_after_chapter is False
    assert settings.capabilities.slovnet_enabled is True
    assert settings.capabilities.razdel_enabled is True


def test_settings_changes_are_published_once_edited(qt_app):
    """The page saves what the dialog reports; silence would lose the change."""
    dialog = _dialog(qt_app)
    published: list[QaSettings] = []
    dialog.settings_changed.connect(published.append)

    dialog.language_check.setChecked(False)

    assert published
    assert published[-1].check_language_after_chapter is False


def test_table_model_rejects_anything_but_a_snapshot(qt_app):
    """A live DataFrame from a background thread must never reach the table."""
    model = ChapterQaTableModel()

    with pytest.raises(TypeError):
        model.set_snapshot({"rows": []})


def test_progress_reports_real_counts(qt_app):
    """A whole-book pass must show how far it actually is."""
    dialog = _dialog(qt_app)

    dialog.set_progress(2, 6, "chapter-2")

    assert dialog.progress.maximum() == 6
    assert dialog.progress.value() == 2
    assert "chapter-2" in dialog.progress.format()


def test_export_is_offered_only_when_there_is_a_report(qt_app):
    """Exporting an empty report would hand the user four empty files."""
    dialog = TranslationQualityDialog()

    assert dialog.export_button.isEnabled() is False

    dialog.set_report(BookQaReportSnapshot.from_journal(_journal()))
    assert dialog.export_button.isEnabled() is True

    dialog.set_busy(True)
    assert dialog.export_button.isEnabled() is False


def test_the_chunk_spin_offers_the_automatic_size(qt_app):
    """Нижнее положение крутилки — «как при переводе», а не запрещённый ноль."""
    dialog = _dialog(qt_app)

    assert dialog.language_chunk_spin.minimum() == 0
    assert dialog.language_chunk_spin.specialValueText()
    dialog.language_chunk_spin.setValue(0)

    assert dialog.qa_settings().language_chunk_chars == 0


def test_the_quality_window_carries_the_cometkiwi_address_both_ways(qt_app):
    """Адрес ПК — единственная настройка CometKiwi, которая реально меняется."""
    dialog = TranslationQualityDialog(
        settings=QaSettings(
            capabilities=QaCapabilitySettings(cometkiwi_enabled=True),
            cometkiwi_model="wmt22-cometkiwi-da",
            cometkiwi_license_accepted=True,
            cometkiwi_endpoint="http://192.168.1.50:8765",
        )
    )

    assert dialog.cometkiwi_endpoint_edit.text() == "http://192.168.1.50:8765"

    dialog.cometkiwi_endpoint_edit.setText("  http://192.168.1.77:9000  ")

    assert dialog.qa_settings().cometkiwi_endpoint == "http://192.168.1.77:9000"


def test_an_empty_address_says_the_scoring_stays_on_this_machine(qt_app):
    dialog = TranslationQualityDialog(settings=QaSettings())

    dialog.cometkiwi_endpoint_edit.setText("")
    dialog.cometkiwi_check_button.click()

    assert "на этом компьютере" in dialog.cometkiwi_status_label.text()


def test_typing_an_address_updates_the_readiness_the_dialog_shows(qt_app):
    """Адрес вписан — окно не должно продолжать называть CometKiwi ненастроенным.

    qa_settings() reads the widget directly, so a missing textChanged hookup is
    invisible to the other tests. This one watches what the user actually sees.
    """
    dialog = TranslationQualityDialog(
        settings=QaSettings(
            capabilities=QaCapabilitySettings(cometkiwi_enabled=True),
            cometkiwi_model="wmt22-cometkiwi-da",
            cometkiwi_license_accepted=True,
        )
    )
    emitted = []
    dialog.settings_changed.connect(emitted.append)

    dialog.cometkiwi_endpoint_edit.setText("http://192.168.1.50:8765")

    assert emitted, "typing an address must report a settings edit"
    assert emitted[-1].cometkiwi_endpoint == "http://192.168.1.50:8765"
    assert "cometkiwi" not in dialog.capability_status_label.text()

    dialog.cometkiwi_endpoint_edit.setText("")

    assert "cometkiwi" in dialog.capability_status_label.text()


# --- _check_cometkiwi_endpoint's network path, over a real socket ---------
#
# In PyQt6 an exception escaping a slot reaches sys.excepthook, and by default
# Qt's qFatal() aborts the whole application. The except branches below are
# what stand between a bad address and a crashed app, so they are exercised
# against a real local HTTP server rather than only the empty-address early
# return. Each server is a ThreadingHTTPServer bound to an OS-assigned port
# ("127.0.0.1", 0), served from a daemon thread, and torn down through
# shutdown() then server_close() — the same idiom test_cometkiwi_server.py
# uses for the real server this dialog eventually talks to, redefined locally
# per this task's instructions rather than imported from that test module.


def _answering(status: int, body: bytes):
    """Build a request handler that answers every GET with one fixed response."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002 - keep test output quiet
            pass

    return _Handler


class _RealHealthServer:
    """A real local HTTP server, for exercising the check's actual socket path."""

    def __init__(self, handler_class) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc_info) -> bool:
        self._httpd.shutdown()
        self._httpd.server_close()
        return False

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"


def test_check_reports_a_healthy_server_over_a_real_connection(qt_app):
    body = json.dumps(
        {
            "schema_version": 1,
            "model": "wmt22-cometkiwi-da",
            "device": "cuda",
            "loaded": True,
        }
    ).encode("utf-8")
    dialog = TranslationQualityDialog(settings=QaSettings())

    with _RealHealthServer(_answering(200, body)) as server:
        dialog.cometkiwi_endpoint_edit.setText(server.base_url)
        dialog._check_cometkiwi_endpoint()

    text = dialog.cometkiwi_status_label.text()
    assert "Связь есть" in text
    assert "wmt22-cometkiwi-da" in text
    assert "cuda" in text
    assert "веса в памяти" in text


def test_check_reports_an_unreachable_server(qt_app):
    """Port 9 (discard) refuses at once, so this never waits out the timeout."""
    dialog = TranslationQualityDialog(settings=QaSettings())
    dialog.cometkiwi_endpoint_edit.setText("http://127.0.0.1:9")

    dialog._check_cometkiwi_endpoint()

    assert "Сервер не отвечает" in dialog.cometkiwi_status_label.text()


def test_check_reports_an_unparseable_response(qt_app):
    dialog = TranslationQualityDialog(settings=QaSettings())

    with _RealHealthServer(_answering(200, b"not json")) as server:
        dialog.cometkiwi_endpoint_edit.setText(server.base_url)
        dialog._check_cometkiwi_endpoint()

    assert dialog.cometkiwi_status_label.text() == "Ответ сервера не разобран."


def test_check_reports_an_http_error_distinctly_from_unreachable(qt_app):
    """A 404 from the wrong service must not be blamed on a firewall."""
    dialog = TranslationQualityDialog(settings=QaSettings())

    with _RealHealthServer(_answering(404, b'{"error": "not_found"}')) as server:
        dialog.cometkiwi_endpoint_edit.setText(server.base_url)
        dialog._check_cometkiwi_endpoint()

    text = dialog.cometkiwi_status_label.text()
    assert "ответил ошибкой 404" in text
    assert "брандмауэр" not in text


# --- the check takes scoring's route and names what actually went wrong ----


def _health(model: str = "wmt22-cometkiwi-da") -> bytes:
    return json.dumps(
        {"schema_version": 1, "model": model, "device": "cuda", "loaded": True}
    ).encode("utf-8")


def _check(dialog: TranslationQualityDialog, address: str) -> str:
    dialog.cometkiwi_endpoint_edit.setText(address)
    dialog._check_cometkiwi_endpoint()
    return dialog.cometkiwi_status_label.text()


def test_check_goes_straight_to_the_pc_whatever_proxy_is_configured(
    qt_app, monkeypatch
):
    """Scoring's aiohttp session ignores proxies; a check that honoured them lied."""
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    # urlopen() caches one opener, built from the environment of its first
    # call; dropping it keeps this test from depending on the order tests run.
    monkeypatch.setattr(urllib.request, "_opener", None)
    dialog = TranslationQualityDialog(settings=QaSettings())

    with _RealHealthServer(_answering(200, _health())) as server:
        text = _check(dialog, server.base_url)

    assert text == "Связь есть: wmt22-cometkiwi-da на cuda, веса в памяти."


@pytest.mark.parametrize("address", ["192.168.1.50:8765", "pc-in-the-hall"])
def test_check_names_an_address_scoring_would_refuse_and_dials_nothing(
    qt_app, monkeypatch, address
):
    """Scoring writes endpoint_invalid for these; the check used to blame a firewall."""
    dialog = TranslationQualityDialog(settings=QaSettings())
    attempts = []
    real_open = urllib.request.OpenerDirector.open

    def _recording_open(self, *args, **kwargs):
        attempts.append(args)
        return real_open(self, *args, **kwargs)

    def _recording_connection(*args, **kwargs):
        attempts.append(args)
        raise OSError("the check must not open a connection")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _recording_open)
    monkeypatch.setattr(socket, "create_connection", _recording_connection)

    text = _check(dialog, address)

    assert text == "Адрес не разобран: нужен вид http://host:port."
    assert attempts == []


def test_check_says_the_server_accepted_the_connection_but_never_answered(
    qt_app, monkeypatch
):
    monkeypatch.setattr(dialog_module, "COMETKIWI_CHECK_TIMEOUT_SECONDS", 0.3)
    dialog = TranslationQualityDialog(settings=QaSettings())

    # listen() and never accept(): the kernel completes the handshake, so the
    # connection is accepted, and nothing on the other side ever answers.
    with socket.create_server(("127.0.0.1", 0)) as listener:
        host, port = listener.getsockname()[:2]
        text = _check(dialog, f"http://{host}:{port}")

    assert text == "Сервер принял соединение, но не ответил за 0.3 с."


def test_check_reports_json_that_is_not_an_object_as_unparsed(qt_app):
    dialog = TranslationQualityDialog(settings=QaSettings())

    with _RealHealthServer(_answering(200, b"[1, 2]")) as server:
        text = _check(dialog, server.base_url)

    assert text == "Ответ сервера не разобран."


def _hanging_up():
    """Build a handler that reads each GET and closes without answering it."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
            self.close_connection = True

        def log_message(self, format, *args):  # noqa: A002 - keep test output quiet
            pass

    return _Handler


def test_check_reports_any_other_failure_without_its_exception_text(qt_app):
    """http.client's RemoteDisconnected is neither a URLError nor a timeout."""
    dialog = TranslationQualityDialog(settings=QaSettings())

    with _RealHealthServer(_hanging_up()) as server:
        text = _check(dialog, server.base_url)

    assert text == "Проверка связи не удалась."


def test_check_warns_when_the_pc_runs_another_model_than_the_settings_name(qt_app):
    dialog = TranslationQualityDialog(
        settings=QaSettings(cometkiwi_model="wmt22-cometkiwi-da")
    )

    with _RealHealthServer(
        _answering(200, _health(model="wmt23-cometkiwi-da-xl"))
    ) as server:
        text = _check(dialog, server.base_url)

    assert text == (
        "Связь есть: wmt23-cometkiwi-da-xl на cuda, веса в памяти. "
        "Внимание: на ПК модель wmt23-cometkiwi-da-xl, "
        "а в настройках — wmt22-cometkiwi-da."
    )


def test_check_cuts_each_model_name_in_the_warning_to_80_characters(qt_app):
    dialog = TranslationQualityDialog(settings=QaSettings(cometkiwi_model="c" * 100))

    with _RealHealthServer(_answering(200, _health(model="s" * 100))) as server:
        text = _check(dialog, server.base_url)

    assert text.endswith(
        f" Внимание: на ПК модель {'s' * 80}, а в настройках — {'c' * 80}."
    )


@pytest.mark.parametrize(
    "server_model, configured_model",
    [
        ("wmt22-cometkiwi-da", "wmt22-cometkiwi-da"),
        ("wmt22-cometkiwi-da", ""),
        ("", "wmt22-cometkiwi-da"),
    ],
)
def test_check_warns_only_when_two_names_disagree(
    qt_app, server_model, configured_model
):
    dialog = TranslationQualityDialog(
        settings=QaSettings(cometkiwi_model=configured_model)
    )

    with _RealHealthServer(_answering(200, _health(model=server_model))) as server:
        text = _check(dialog, server.base_url)

    assert text.startswith("Связь есть:")
    assert "Внимание" not in text


def test_a_model_name_from_the_network_is_shown_as_plain_text(qt_app):
    """The server is unauthenticated: nothing it sends is rendered as markup."""
    dialog = TranslationQualityDialog(settings=QaSettings())

    with _RealHealthServer(_answering(200, _health(model="<b>x</b>"))) as server:
        text = _check(dialog, server.base_url)

    assert "<b>x</b>" in text
    assert dialog.cometkiwi_status_label.textFormat() == Qt.TextFormat.PlainText
