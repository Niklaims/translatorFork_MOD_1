"""Хвост perf:network/1 (оркестратор создаёт сессию на каждую попытку).

Доминирующая стоимость новой aiohttp-сессии — ssl.create_default_context(),
который заново читает и разбирает CA-bundle (~9 мс) при каждом вызове
_create_ssl_context(). Контекст не мутируется ни одним потребителем
(проверено grep'ом: нет check_hostname/verify_mode/load_*), поэтому его
можно безопасно разделять между сессиями и кэшировать по той же сигнатуре
(SSL_CERT_FILE/SSL_CERT_DIR или certifi), по которой сессия и так решает,
не устарел ли её контекст.
"""

from __future__ import annotations

import ssl
from unittest import mock

import gemini_translator.api.base as base


def test_same_signature_reuses_one_ssl_context(monkeypatch):
    base._SSL_CONTEXT_CACHE.clear()
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    with mock.patch.object(ssl, "create_default_context", wraps=ssl.create_default_context) as spy:
        first = base._create_ssl_context()
        second = base._create_ssl_context()
    assert first is second
    assert spy.call_count == 1


def test_changed_signature_builds_a_new_context(monkeypatch, tmp_path):
    base._SSL_CONTEXT_CACHE.clear()
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    certifi_context = base._create_ssl_context()
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    env_context = base._create_ssl_context()
    assert env_context is not certifi_context
    # Возврат к прежней сигнатуре отдаёт прежний контекст, а не строит третий.
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    assert base._create_ssl_context() is certifi_context


def test_public_alias_shares_the_cache():
    base._SSL_CONTEXT_CACHE.clear()
    assert base.create_ssl_context() is base._create_ssl_context()
