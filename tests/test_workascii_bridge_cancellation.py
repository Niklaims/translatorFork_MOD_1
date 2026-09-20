"""ChatGPT Web (work_ascii): сворачивание моста не должно глотать чужую отмену.

Sonar python:S7497 на четырёх обработчиках asyncio.CancelledError в
workascii_chatgpt.py (_drain_stdout, _drain_stderr и две пары cancel/await в
_terminate_bridge_locked). Замер до правки: внешняя отмена, пришедшая в окно
между `stdout_task.cancel()` и концом `await stdout_task`, пропадала во всех
раскладках планировщика — охватывающая корутина продолжала работу вместо
раскрутки, а `execute_api_call` в api/base.py так и не видел CancelledError и
не мог отличить остановку сессии от успешного ответа.

Разделитель — счётчик Task.cancelling() (Python 3.11): снимок до cancel()
отделяет отмену, которую запросили мы сами, от внешней, пришедшей в то же окно.
Снимок обязателен: call_api зовёт _terminate_bridge уже из блока
`except asyncio.CancelledError`, где cancelling() и так равен 1, и голая
проверка «cancelling() > 0 → raise» оборвала бы штатную уборку моста.
"""
import asyncio
from types import SimpleNamespace

import pytest

from gemini_translator.api.errors import NetworkError
from gemini_translator.api.handlers.workascii_chatgpt import WorkAsciiChatGptApiHandler


class _SilentStream:
    """stdout/stderr моста, которые молчат до самой отмены."""

    def __init__(self):
        self._gate = None

    async def readline(self):
        if self._gate is None:
            self._gate = asyncio.get_running_loop().create_future()
        await self._gate
        return b""


def _handler(returncode=0):
    worker = SimpleNamespace(
        provider_config={"is_async": True, "base_timeout": 1800},
        prompt_builder=SimpleNamespace(system_instruction=""),
        _post_event=lambda *args, **kwargs: None,
    )
    handler = WorkAsciiChatGptApiHandler(worker)
    handler._bridge_process = SimpleNamespace(
        stdout=_SilentStream(),
        stderr=_SilentStream(),
        returncode=returncode,
    )
    return handler


async def _start_drains(handler):
    handler._stdout_task = asyncio.create_task(handler._drain_stdout())
    handler._stderr_task = asyncio.create_task(handler._drain_stderr())
    for _ in range(3):
        await asyncio.sleep(0)
    return handler._stdout_task, handler._stderr_task


def test_external_cancel_during_bridge_teardown_is_not_swallowed():
    """Остановка сессии в окне сворачивания обязана раскрутить вызывающего."""

    async def attempt(steps_before_cancel):
        handler = _handler()
        stdout_task, stderr_task = await _start_drains(handler)

        outer = asyncio.create_task(handler._terminate_bridge())
        await asyncio.sleep(0)  # outer доходит до `await stdout_task`
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

        # Что бы ни случилось с отменой, мост обязан быть свёрнут.
        assert stdout_task.done() and stderr_task.done()
        return survived

    async def scenario():
        checked = 0
        for steps in range(4):
            survived = await attempt(steps)
            if survived is None:
                continue
            checked += 1
            assert survived is False, (
                f"внешняя отмена потеряна: _terminate_bridge завершилась штатно "
                f"(шагов до отмены: {steps})"
            )
        return checked

    assert asyncio.run(scenario()) >= 3


def test_teardown_from_an_unwinding_cancel_still_finishes():
    """call_api сворачивает мост уже из except CancelledError — уборка обязана дойти до конца.

    В этот момент cancelling() охватывающей задачи уже равен 1. Проверка без
    снимка приняла бы его за новую отмену, бросила бы CancelledError на первой
    же задаче дренажа и оставила вторую висеть.
    """

    async def scenario():
        handler = _handler()
        stdout_task, stderr_task = await _start_drains(handler)

        async def body():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await handler._terminate_bridge()
                raise

        task = asyncio.create_task(body())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert stdout_task.done() and stderr_task.done()
        assert handler._stdout_task is None and handler._stderr_task is None
        assert handler._bridge_process is None

    asyncio.run(scenario())


def test_cancelled_stdout_drain_still_fails_pending_commands():
    """Отмена дренажа обязана и раскрутиться, и добить висящие futures.

    Блок finally в _drain_stdout — единственное место, где ожидающий ответа
    вызов получает ошибку моста. Проброс CancelledError его не отменяет.
    """

    async def scenario():
        handler = _handler(returncode=3)
        stdout_task = asyncio.create_task(handler._drain_stdout())
        await asyncio.sleep(0)

        pending = asyncio.get_running_loop().create_future()
        handler._pending_commands["cmd-1"] = pending

        stdout_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stdout_task

        assert pending.done()
        assert isinstance(pending.exception(), NetworkError)
        assert "Exit code: 3" in str(pending.exception())
        assert handler._pending_commands == {}

    asyncio.run(scenario())


def test_plain_teardown_without_outside_cancel_stays_quiet():
    """Без внешней отмены сворачивание моста обязано пройти молча."""

    async def scenario():
        handler = _handler()
        stdout_task, stderr_task = await _start_drains(handler)

        pending = asyncio.get_running_loop().create_future()
        handler._pending_commands["cmd-1"] = pending

        await handler._terminate_bridge()

        assert stdout_task.done() and stderr_task.done()
        assert handler._bridge_process is None
        assert isinstance(pending.exception(), NetworkError)

    asyncio.run(scenario())
