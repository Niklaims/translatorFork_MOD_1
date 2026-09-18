"""Token usage of the provider call in flight.

A worker runs up to ``max_concurrent_requests`` calls through one API handler
at once, so the numbers of a call cannot live on the handler: a neighbouring
call would overwrite them or wipe them. Each attempt of ``execute_api_call``
opens its own tally in a ContextVar instead. asyncio tasks and ``run_sync``
threads start from a copy of the context, so they share the tally object of
the attempt that started them and fill it for that attempt only.

Whoever publishes usage calls ``token_usage.publish_token_usage`` through this
module, never a copy imported by name: the nolib bridge replaces that
attribute to write every call to its usage log.
"""

from __future__ import annotations

import contextvars


class _AttemptTally:
    """What the provider reported for one attempt."""

    __slots__ = ("usage",)

    def __init__(self) -> None:
        self.usage: dict | None = None


_current_attempt: contextvars.ContextVar[_AttemptTally | None] = contextvars.ContextVar(
    "token_usage_attempt", default=None
)


def begin_attempt() -> contextvars.Token:
    """Open an empty tally for the attempt about to run."""
    return _current_attempt.set(_AttemptTally())


def end_attempt(token: contextvars.Token) -> None:
    """Close the tally that ``begin_attempt`` opened."""
    _current_attempt.reset(token)


def remember(
    input_tokens: int,
    output_tokens: int,
    *,
    cached_tokens: int | None = None,
    thinking_tokens: int | None = None,
    total_tokens: int | None = None,
) -> None:
    """Keep what the provider billed for the current attempt.

    A stream reports running totals, so the latest report replaces the one
    before it. ``output_tokens`` includes thinking, ``thinking_tokens`` is its
    share. Outside an attempt there is nowhere to keep the numbers.
    """
    tally = _current_attempt.get()
    if tally is None:
        return
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens or (input_tokens + output_tokens),
    }
    if cached_tokens is not None:
        usage["cached_tokens"] = cached_tokens
    if thinking_tokens is not None:
        usage["thinking_tokens"] = thinking_tokens
    tally.usage = usage


def reported() -> dict | None:
    """A copy of what the current attempt reported, or None."""
    tally = _current_attempt.get()
    if tally is None or tally.usage is None:
        return None
    return dict(tally.usage)


def publish_token_usage(usage: dict, poster=None) -> None:
    """The one exit for usage: hand it to ``poster`` when there is one."""
    if callable(poster):
        poster("token_usage_updated", usage)
