"""Every call counts its own tokens, even when calls share one handler.

A worker runs up to max_concurrent_requests calls through one API handler at
once. When the usage of a call lived in a handler field, a neighbouring call
overwrote it or wiped it, and a failed attempt published nothing although the
provider had billed it.
"""

import asyncio
import contextvars
import threading

from gemini_translator.api import token_usage


def test_remember_outside_an_attempt_keeps_nothing():
    token_usage.remember(10, 2)

    assert token_usage.reported() is None


def test_the_latest_report_of_an_attempt_wins():
    token = token_usage.begin_attempt()
    try:
        token_usage.remember(1200, 0)
        token_usage.remember(1200, 340, cached_tokens=1024, thinking_tokens=60, total_tokens=1600)
        reported = token_usage.reported()
    finally:
        token_usage.end_attempt(token)

    assert reported == {
        "input_tokens": 1200,
        "output_tokens": 340,
        "total_tokens": 1600,
        "cached_tokens": 1024,
        "thinking_tokens": 60,
    }
    assert token_usage.reported() is None


def test_optional_counts_are_left_out_and_the_total_is_summed():
    token = token_usage.begin_attempt()
    try:
        token_usage.remember(100, 20)
        reported = token_usage.reported()
    finally:
        token_usage.end_attempt(token)

    assert reported == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


def test_a_new_attempt_starts_empty_and_the_outer_one_comes_back():
    outer = token_usage.begin_attempt()
    try:
        token_usage.remember(1, 1)
        inner = token_usage.begin_attempt()
        try:
            assert token_usage.reported() is None
            token_usage.remember(2, 2)
        finally:
            token_usage.end_attempt(inner)
        assert token_usage.reported()["input_tokens"] == 1
    finally:
        token_usage.end_attempt(outer)


def test_reported_hands_out_a_copy():
    token = token_usage.begin_attempt()
    try:
        token_usage.remember(5, 5)
        token_usage.reported()["input_tokens"] = 999
        reported = token_usage.reported()
    finally:
        token_usage.end_attempt(token)

    assert reported["input_tokens"] == 5


def test_a_task_started_inside_the_attempt_reports_into_it():
    async def scenario():
        token = token_usage.begin_attempt()
        try:
            async def provider_call():
                token_usage.remember(30, 3)

            await asyncio.create_task(provider_call())
            return token_usage.reported()
        finally:
            token_usage.end_attempt(token)

    assert asyncio.run(scenario())["input_tokens"] == 30


def test_a_thread_running_in_a_copy_of_the_context_reports_into_the_attempt():
    token = token_usage.begin_attempt()
    try:
        context = contextvars.copy_context()
        thread = threading.Thread(target=context.run, args=(token_usage.remember, 40, 4))
        thread.start()
        thread.join()
        reported = token_usage.reported()
    finally:
        token_usage.end_attempt(token)

    assert reported["input_tokens"] == 40


def test_publish_hands_the_usage_to_a_poster_and_tolerates_none():
    events = []

    token_usage.publish_token_usage({"input_tokens": 1}, lambda name, payload: events.append((name, payload)))
    token_usage.publish_token_usage({"input_tokens": 2})
    token_usage.publish_token_usage({"input_tokens": 3}, poster="not callable")

    assert events == [("token_usage_updated", {"input_tokens": 1})]
