"""DNS-over-HTTPS fallback for hosts the system resolver lies about.

A blocked or hijacked system resolver can return an address that does not
accept connections (the usual case is an ISP block page).  The fix keeps the
original hostname for TLS/SNI and the ``Host`` header and replaces only the
address the connector dials, so certificate verification stays intact.

The fallback is deliberately lazy: it is asked for only after a real
connection failure, and only for a hostname (never for an IP literal).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time

import aiohttp

# IP literals on purpose: if the system resolver hijacks dns.google too, a
# hostname endpoint would be resolved to the same broken address.  Both
# certificates carry the IP in their SAN list.
DOH_ENDPOINTS = (
    "https://8.8.8.8/resolve",
    "https://1.1.1.1/dns-query",
)
DOH_HEADERS = {"accept": "application/dns-json"}

# How long a successful DoH answer may be reused by one handler.
DOH_OVERRIDE_TTL_SECONDS = 300.0


def is_ip_literal(host) -> bool:
    if not isinstance(host, str) or not host:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def answers_from_doh_payload(payload, family=socket.AF_INET):
    """Extract ``(family, address)`` pairs from a Google/Cloudflare JSON answer."""
    if not isinstance(payload, dict):
        return []
    records = []
    for answer in payload.get("Answer") or []:
        if not isinstance(answer, dict):
            continue
        if answer.get("type") not in (1, 28):
            continue
        try:
            address = ipaddress.ip_address(str(answer.get("data") or "").strip())
        except ValueError:
            continue
        if address.version == 4 and family == socket.AF_INET:
            records.append((socket.AF_INET, str(address)))
        elif address.version == 6 and family == socket.AF_INET6:
            records.append((socket.AF_INET6, str(address)))
    return records


def _session_factory(ssl_context, timeout):
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        connector=aiohttp.TCPConnector(ssl=ssl_context),
        trust_env=False,
    )


async def _query_endpoint(session, endpoint, host, timeout):
    for record_type, family in (("A", socket.AF_INET), ("AAAA", socket.AF_INET6)):
        try:
            request_timeout = aiohttp.ClientTimeout(total=max(0.1, timeout))
            async with session.get(
                endpoint,
                params={"name": host, "type": record_type},
                headers=DOH_HEADERS,
                timeout=request_timeout,
            ) as response:
                if response.status != 200:
                    continue
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
            continue
        records = answers_from_doh_payload(payload, family)
        if records:
            return records
    return []


async def resolve_via_doh(
    host,
    *,
    ssl_context,
    timeout=4.0,
    endpoints=DOH_ENDPOINTS,
    session_factory=None,
):
    """Resolve ``host`` through DoH; return ``[(family, address), ...]``.

    Returns an empty list when every endpoint is unreachable or answers with
    nothing usable.  Callers keep the normal resolver in that case.
    """
    if not host or is_ip_literal(host):
        return []

    deadline = time.monotonic() + max(0.1, float(timeout))
    factory = session_factory or _session_factory
    try:
        session = factory(ssl_context, timeout)
    except Exception:
        return []

    try:
        async with session as client:
            for endpoint in endpoints:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                records = await _query_endpoint(client, endpoint, host, remaining)
                if records:
                    return records
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return []
    return []


class OverridingResolver(aiohttp.abc.AbstractResolver):
    """Resolver that serves cached DoH answers and delegates everything else."""

    def __init__(self, overrides, fallback=None):
        # overrides: {hostname: (expires_at_monotonic, [(family, address), ...])}
        self._overrides = overrides
        self._fallback = fallback if fallback is not None else aiohttp.resolver.ThreadedResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        entry = self._overrides.get(host)
        if entry:
            expires_at, addresses = entry
            if expires_at > time.monotonic():
                selected = [
                    (address_family, address)
                    for address_family, address in addresses
                    if family in (socket.AF_UNSPEC, address_family)
                ]
                if selected:
                    return [
                        {
                            "hostname": host,
                            "host": address,
                            "port": port,
                            "family": address_family,
                            "proto": 0,
                            "flags": 0,
                        }
                        for address_family, address in selected
                    ]
            else:
                self._overrides.pop(host, None)
        return await self._fallback.resolve(host, port, family)

    async def close(self):
        await self._fallback.close()
