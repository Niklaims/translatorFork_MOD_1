"""drain_cancelled_tasks: уборка своих задач не должна глотать чужую отмену.

Sonar python:S7497 указывал на шесть мест с одной и той же формой — «отменяю
задачу, которой владею сам, и гашу её CancelledError». Для самой задачи это
штатно, но замер показал, что внешняя отмена, попавшая в то же окно, пропадала
целиком: охватывающая корутина завершалась штатно вместо раскрутки. Разделитель —
прирост счётчика Task.cancelling() (Python 3.11), а не сам факт его ненулевого
значения: уборку часто зовут из блока `except asyncio.CancelledError`, где
счётчик уже равен единице.
"""
import asyncio

import pytest

from gemini_translator.utils.async_helpers import drain_cancelled_tasks


async def _sleeper():
    await asyncio.sleep(3600)


def test_external_cancel_during_the_drain_is_not_swallowed():
    async def attempt(steps_before_cancel):
        victim = asyncio.create_task(_sleeper())
        await asyncio.sleep(0)

        outer = asyncio.create_task(drain_cancelled_tasks(victim))
        await asyncio.sleep(0)  # уборка дошла до `await victim`
        for _ in range(steps_before_cancel):
            if outer.done():
                return None
            await asyncio.sleep(0)
        if outer.done():
            return None

        outer.cancel()
        try:
            await outer
            survived = True
        except asyncio.CancelledError:
            survived = False

        assert victim.done()
        return survived

    async def scenario():
        checked = 0
        for steps in range(3):
            survived = await attempt(steps)
            if survived is None:
                continue
            checked += 1
            assert survived is False, (
                f"внешняя отмена потеряна (шагов до отмены: {steps})"
            )
        return checked

    assert asyncio.run(scenario()) >= 2


def test_drain_started_from_an_unwinding_cancel_finishes_every_task():
    """Счётчик cancelling() уже равен 1 — обрывать уборку на этом нельзя."""

    async def scenario():
        first = asyncio.create_task(_sleeper())
        second = asyncio.create_task(_sleeper())
        await asyncio.sleep(0)

        async def body():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await drain_cancelled_tasks(first, second)
                raise

        task = asyncio.create_task(body())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert first.cancelled() and second.cancelled()

    asyncio.run(scenario())


def test_a_failing_task_does_not_stop_the_rest():
    async def scenario():
        async def boom():
            raise RuntimeError("задача провалилась")

        failing = asyncio.create_task(boom())
        pending = asyncio.create_task(_sleeper())
        await asyncio.sleep(0)

        await drain_cancelled_tasks(failing, pending)

        assert pending.cancelled()

    asyncio.run(scenario())


def test_without_an_outside_cancel_the_drain_stays_quiet():
    async def scenario():
        async def done_quickly():
            return "готово"

        finished = asyncio.create_task(done_quickly())
        await asyncio.sleep(0)
        assert finished.done()

        pending = asyncio.create_task(_sleeper())
        await asyncio.sleep(0)

        await drain_cancelled_tasks(finished, None, pending)

        assert finished.result() == "готово"
        assert pending.cancelled()

    asyncio.run(scenario())


def test_outside_a_task_the_drain_never_raises():
    """loop.run_until_complete без задачи: current_task() пуст, падать нечему."""
    loop = asyncio.new_event_loop()
    try:
        pending = loop.create_task(_sleeper())
        loop.run_until_complete(asyncio.sleep(0))
        loop.run_until_complete(drain_cancelled_tasks(pending))
        assert pending.cancelled()
    finally:
        loop.close()
