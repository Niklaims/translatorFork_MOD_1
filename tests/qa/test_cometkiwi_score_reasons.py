"""A chapter left without a CometKiwi score says why, in words a reader understands."""

from __future__ import annotations

import pytest

from gemini_translator.qa.estimators.cometkiwi_model_manager import (
    describe_quality_score_status,
)


@pytest.mark.parametrize(
    ("status", "text"),
    [
        ("completed", ""),
        ("not_run", ""),
        ("", ""),
        ("unavailable:endpoint_unreachable", "ПК не отвечает"),
        ("unavailable:endpoint_invalid", "адрес ПК записан неверно"),
        ("unavailable:endpoint_status_413", "ПК ответил ошибкой 413"),
        ("unavailable:timeout", "оценка не уложилась в отведённое время"),
        ("unavailable:out_of_memory", "не хватило памяти"),
        ("unavailable:runner_error:out_of_memory", "не хватило памяти"),
        ("unavailable:runner_error:outofmemoryerror", "не хватило видеопамяти"),
        ("unavailable:weights_missing", "не найдены веса модели"),
        ("unavailable:runner_error:checkpoint_missing", "не найдены веса модели"),
        (
            "unavailable:runner_error:runner_environment_incomplete",
            "не установлены пакеты для оценки",
        ),
        ("unavailable:response_too_large", "ответ оценки слишком большой"),
        ("unavailable:invalid_scores", "пришли негодные оценки"),
        ("unavailable:runner_exit_2", "программа оценки завершилась с кодом 2"),
        ("unavailable:runner_signal_9", "программа оценки прервана сигналом 9"),
        ("unavailable:runner_error", "программа оценки сообщила об ошибке"),
        (
            "unavailable:runner_error:keyerror",
            "программа оценки сообщила об ошибке (keyerror)",
        ),
        ("disabled:license_not_accepted", "не принята лицензия модели"),
        ("disabled:capability_disabled", "оценка выключена"),
        ("unavailable:model_missing", "не указана модель"),
        ("unavailable:something_new", "оценка недоступна (something_new)"),
        ("unavailable", "оценка недоступна"),
    ],
)
def test_every_stored_reason_reads_as_words(status, text):
    assert describe_quality_score_status(status) == text


# Every reason the client, the PC server and the runner can store
# (spec 2026-09-12, «Отказы и деградация»).
KNOWN_REASONS = (
    "model_missing",
    "endpoint_invalid",
    "runner_missing",
    "runner_not_found",
    "weights_missing",
    "endpoint_unreachable",
    "endpoint_status_500",
    "timeout",
    "runner_not_started",
    "out_of_memory",
    "runner_exit_1",
    "runner_signal_9",
    "runner_crashed",
    "response_too_large",
    "runner_failed",
    "invalid_response",
    "unsupported_schema_version",
    "request_id_mismatch",
    "runner_error",
    "runner_error:invalid_request",
    "runner_error:unsupported_schema_version",
    "runner_error:too_many_segments",
    "runner_error:unexpected_segment_field",
    "runner_error:score_count_mismatch",
    "runner_error:checkpoint_missing",
    "runner_error:invalid_model_output",
    "runner_error:runner_environment_incomplete",
    "runner_error:out_of_memory",
    "runner_error:outofmemoryerror",
    "runner_error:request_too_large",
    "runner_error:weights_missing",
    "score_count_mismatch",
    "invalid_scores",
    "invalid_reason",
)


@pytest.mark.parametrize("reason", KNOWN_REASONS)
def test_no_known_reason_is_shown_as_its_code(reason):
    text = describe_quality_score_status(f"unavailable:{reason}")

    assert text
    assert "(" not in text
    assert reason.split(":")[-1] not in text
