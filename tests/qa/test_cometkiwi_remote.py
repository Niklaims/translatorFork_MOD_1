"""Scoring on another machine: the address, the transport, and the refusals."""

from __future__ import annotations

import pytest

from gemini_translator.qa.estimators.cometkiwi_client import CometKiwiRunnerConfig


def _remote(**overrides) -> CometKiwiRunnerConfig:
    values = {
        "runner_path": "",
        "model_dir": "",
        "model": "wmt22-cometkiwi-da",
        "device": "cuda",
        "endpoint": "http://192.168.1.50:8765",
    }
    values.update(overrides)
    return CometKiwiRunnerConfig(**values)


def test_a_remote_config_does_not_want_a_local_runner_or_local_weights():
    """Раннер и веса живут на ПК; требовать их на Mac — выключить возможность."""
    assert _remote().is_remote is True
    assert _remote().setup_problem() == ""


def test_an_empty_endpoint_keeps_the_local_rules():
    config = CometKiwiRunnerConfig(
        runner_path="", model_dir="", model="wmt22-cometkiwi-da"
    )
    assert config.is_remote is False
    assert config.setup_problem() == "runner_missing"


@pytest.mark.parametrize(
    "endpoint",
    [
        "192.168.1.50:8765",        # без схемы
        "ftp://192.168.1.50:8765",  # чужая схема
        "http://",                  # без хоста
        "http://192.168.1.50:0",    # порт вне диапазона
        "http://192.168.1.50:abc",  # порт не число
    ],
)
def test_an_unusable_address_is_named_and_not_dialled(endpoint):
    assert _remote(endpoint=endpoint).setup_problem() == "endpoint_invalid"


def test_the_model_name_is_still_required_remotely():
    """Оценка без имени модели бесполезна при сравнении прогонов."""
    assert _remote(model="").setup_problem() == "model_missing"


def test_a_trailing_slash_does_not_make_a_second_address():
    assert _remote(endpoint="http://192.168.1.50:8765/").score_url() == (
        "http://192.168.1.50:8765/score"
    )
    assert _remote().score_url() == "http://192.168.1.50:8765/score"
