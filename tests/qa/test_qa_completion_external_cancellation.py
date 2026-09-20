"""QA-адаптер: Task.cancel() извне не должен теряться в сливе отменённых задач.

Sonar python:S7497 на _drain_cancelled_task и _discard_unscheduled_awaitable.
Замер до правки: отмена, пришедшая в окно между `task.cancel()` и концом
`await task`, пропадала — _await_with_cancellation на пути успеха отдавала
готовый результат так, будто отмены не было. В complete_json потерю подбирал
следующий _raise_if_cancelling, то есть наружу она всё же выходила, но одним
шагом позже и уже без связи с моментом остановки.

Механика разделителя вынесена в utils.async_helpers.drain_cancelled_tasks и
проверяется отдельно (tests/test_async_helpers_drain_cancelled.py); здесь —
поведение самого адаптера.
"""
import asyncio
import inspect
import json

import pytest

from gemini_translator.qa.llm import (
    CancellationToken,
    ExistingHandlerCompletionClient,
    QaModelSelection,
)


def _client(event_sink=None):
    return ExistingHandlerCompletionClient(lambda model: object(), event_sink)


def test_external_cancel_does_not_let_a_finished_call_return_its_result():
    """Путь успеха _await_with_cancellation: отмена важнее готового ответа."""
    client = _client()

    async def attempt(steps_before_cancel):
        async def payload():
            await asyncio.sleep(0)
            return "результат"

        coro = payload()
        try:
            outer = asyncio.create_task(
                client._await_with_cancellation(coro, CancellationToken())
            )
            for _ in range(steps_before_cancel):
                if outer.done():
                    return None
                await asyncio.sleep(0)
            if outer.done():
                return None

            outer.cancel()
            try:
                await outer
                return True
            except asyncio.CancelledError:
                return False
        finally:
            # Отмена на первых шагах случается раньше, чем адаптер успевает
            # завернуть корутину в задачу: закрываем её сами, иначе тест шумит.
            if inspect.getcoroutinestate(coro) == inspect.CORO_CREATED:
                coro.close()

    async def scenario():
        checked = 0
        for steps in range(8):
            survived = await attempt(steps)
            if survived is None:
                continue
            checked += 1
            assert survived is False, (
                f"внешняя отмена потеряна в _await_with_cancellation "
                f"(шагов до отмены: {steps})"
            )
        return checked

    assert asyncio.run(scenario()) >= 6


def test_cancelled_wait_leaves_no_task_behind():
    """Уборка из блока except обязана добить и вызов, и сторожа отмены."""
    client = _client()

    async def scenario():
        async def hangs():
            await asyncio.sleep(3600)

        outer = asyncio.create_task(
            client._await_with_cancellation(hangs(), CancellationToken())
        )
        for _ in range(3):
            await asyncio.sleep(0)

        before = {t for t in asyncio.all_tasks() if t is not outer}
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer

        leftovers = {
            t for t in asyncio.all_tasks() if t not in before and t is not outer
        }
        assert not [t for t in leftovers if not t.done()]

    asyncio.run(scenario())


def test_cancelling_complete_json_always_unwinds():
    """Сквозная гарантия: отмена задачи на любом шаге поднимается из complete_json."""
    payload = json.dumps({"ok": True})

    class _Handler:
        def execute_api_call(self, prompt, log_prefix, **kwargs):
            async def run():
                await asyncio.sleep(0)
                return payload

            return run()

    async def sink(event):
        await asyncio.sleep(0)

    async def attempt(steps_before_cancel):
        client = ExistingHandlerCompletionClient(lambda model: _Handler(), sink)
        task = asyncio.create_task(
            client.complete_json(
                "prompt",
                model=QaModelSelection(provider="p", model="m"),
                max_output_tokens=64,
                cancellation=CancellationToken(),
            )
        )
        for _ in range(steps_before_cancel):
            if task.done():
                return None
            await asyncio.sleep(0)
        if task.done():
            return None

        task.cancel()
        try:
            await task
            return True
        except asyncio.CancelledError:
            return False

    async def scenario():
        checked = 0
        for steps in range(40):
            survived = await attempt(steps)
            if survived is None:
                break
            checked += 1
            assert survived is False, (
                f"complete_json вернула результат после отмены "
                f"(шагов до отмены: {steps})"
            )
        return checked

    assert asyncio.run(scenario()) >= 10
