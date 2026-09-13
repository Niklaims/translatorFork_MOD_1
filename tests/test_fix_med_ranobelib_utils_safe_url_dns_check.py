# -*- coding: utf-8 -*-
"""Регресс-тест на находку ranobelib/bugs/5-safe-url-gate-no-dns-check.

``is_safe_remote_http_url`` (ranobelib/utils.py) отклонял только URL, где
сам hostname был IP-литералом из приватного/loopback диапазона, либо
буквальным localhost/.local. Для произвольного доменного имени, которое
через DNS резолвится в приватный/loopback/link-local адрес (DNS rebinding
или скрытый внутренний сервис), функция возвращала True без какого-либо
резолвинга — гейт проходил, хотя workers.py использует именно эту функцию
как единственную защиту перед urllib.request.Request на cover_url,
полученный из непроверенного HTML со страницы Rulate.

Тесты патчат ``socket.getaddrinfo`` (внешнюю сетевую зависимость, а не саму
проверяемую функцию), чтобы детерминированно и без сети проверить реальное
тело is_safe_remote_http_url на разных исходах DNS-резолвинга.
"""
import os
import socket
import sys

TESTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
RANOBELIB_DIR = os.path.join(PROJECT_ROOT, "ranobelib")

if RANOBELIB_DIR not in sys.path:
    sys.path.insert(0, RANOBELIB_DIR)

from utils import is_safe_remote_http_url  # noqa: E402


def _fake_getaddrinfo(ip):
    def _resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _resolver


def test_domain_resolving_to_loopback_is_rejected(monkeypatch):
    """Домен (не IP-литерал), резолвящийся в 127.0.0.1, должен быть отклонён.

    Раньше hostname, не совпадающий ни с одним IP-литералом, безусловно
    проходил гейт (ipaddress.ip_address бросает ValueError -> return True),
    даже если реальный DNS-адрес — loopback.
    """
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))
    assert is_safe_remote_http_url("http://evil.example.com/cover.jpg") is False


def test_domain_resolving_to_private_network_is_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("10.0.0.5"))
    assert is_safe_remote_http_url("http://internal.example.com/cover.jpg") is False


def test_domain_resolving_to_link_local_is_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    assert is_safe_remote_http_url("http://metadata.example.com/cover.jpg") is False


def test_domain_resolving_to_public_ip_is_still_allowed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert is_safe_remote_http_url("http://cdn.example.com/cover.jpg") is True


def test_domain_that_fails_to_resolve_is_not_blocked_by_dns_check(monkeypatch):
    """Хост, который вообще не резолвится, не блокируем DNS-проверкой:

    реальный запрос всё равно упадёт на резолве (SSRF-риска нет), а этот
    случай уже покрыт существующим характеризационным тестом
    tests/test_ranobelib_epub_parser.py, который трогать нельзя.
    """

    def _raise(host, port, *args, **kwargs):
        raise socket.gaierror("nodename nor servname provided, or not known")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    assert is_safe_remote_http_url("http://nonexistent.invalid/cover.jpg") is True


def test_ip_literal_hostname_does_not_trigger_dns_resolution(monkeypatch):
    """IP-литералы проверяются напрямую и не должны идти через getaddrinfo."""

    def _boom(*args, **kwargs):
        raise AssertionError("getaddrinfo не должен вызываться для IP-литерала")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    assert is_safe_remote_http_url("http://127.0.0.1/cover.jpg") is False
    assert is_safe_remote_http_url("http://8.8.8.8/cover.jpg") is True
