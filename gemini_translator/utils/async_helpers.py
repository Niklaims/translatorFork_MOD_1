# gemini_translator/utils/async_helpers.py
# -*- coding: utf-8 -*-

import asyncio
import contextvars
import functools
from concurrent.futures import Future, ThreadPoolExecutor
import threading

def run_sync(func, *args, forget: bool = False, timeout: float = None, executor=None, **kwargs) -> any:
    """
    Универсальная утилита для запуска синхронной, блокирующей функции 
    в фоновом потоке из асинхронного контекста.

    Args:
        func: Синхронная функция для выполнения.
        *args: Позиционные аргументы для функции.
        forget (bool): 
            - Если False (по умолчанию): Функция становится асинхронной. 
              Возвращает корутину, которую нужно ожидать (`await`).
            - Если True ("fire and forget"): Функция запускается в фоновом потоке,
              и управление немедленно возвращается. Возвращает None.
        timeout (float): 
            Опциональный таймаут в секундах. Работает только если `forget=False`.
            Если время истекает, выбрасывается `asyncio.TimeoutError`.
        **kwargs: Именованные аргументы для функции.

    Returns:
        - Корутина, которая при ожидании вернет результат выполнения `func` (если forget=False).
        - None (если forget=True).

    Raises:
        asyncio.TimeoutError: если истек таймаут (только при `forget=False`).
    """
    
    # Готовим вызов функции со всеми её аргументами
    func_with_args = functools.partial(func, *args, **kwargs)
    captured_context = contextvars.copy_context()

    def context_bound_call():
        return captured_context.run(func_with_args)

    async def main_wrapper():
        """Внутренняя асинхронная обертка, которая будет возвращена как корутина."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Если event loop не запущен, асинхронный вызов невозможен.
            # Это может произойти, если утилиту пытаются использовать вне async-функции.
            # Мы не можем вернуть awaitable, поэтому выбрасываем понятную ошибку.
            raise RuntimeError(
                "run_sync() can only be awaited inside a running asyncio event loop."
            )
        
        # Запускаем в указанном экзекуторе (executor=None → дефолтный экзекутор loop)
        future = loop.run_in_executor(executor, context_bound_call)
        
        # Асинхронно ждем завершения future с таймаутом.
        # asyncio.wait_for само обработает TimeoutError.
        return await asyncio.wait_for(future, timeout=timeout)

    if forget:
        try:
            loop = asyncio.get_running_loop()
            # Запускаем и "забываем"
            loop.run_in_executor(None, context_bound_call)
        except RuntimeError:
            # Если нет event loop'а, запускаем в обычном потоке.
            # Это обеспечивает предсказуемое поведение "fire and forget" всегда.
            thread = threading.Thread(target=context_bound_call)
            thread.daemon = True
            thread.start()
        return None # Для "fire and forget" всегда возвращаем None
    else:
        # Для режима ожидания возвращаем корутину, которую можно будет `await`.
        return main_wrapper()


async def drain_cancelled_tasks(*tasks) -> None:
    """Свернуть задачи, которыми владеет вызывающий, не проглотив чужую отмену.

    Отменить собственную задачу и погасить её `CancelledError` — штатная уборка.
    Опасность ровно одна: в то же окно может прийти отмена извне (остановка
    сессии, глобальный `asyncio.wait_for` в api/base.py). Голый
    `except asyncio.CancelledError: pass` съедает и её — охватывающая корутина
    продолжает работу вместо раскрутки, и вызывающий код принимает остановку за
    обычное завершение.

    Разделитель — счётчик `Task.cancelling()` (Python 3.11): он растёт на каждый
    запрошенный извне `cancel()`. Сравнивается прирост, а не сам факт ненулевого
    счётчика: уборку часто запускают прямо из блока
    `except asyncio.CancelledError`, где счётчик уже равен единице, и прерываться
    там нельзя — иначе ресурсы останутся висеть.

    Все задачи сворачиваются до конца в любом случае, проброс — только после:
    выход на первой же задаче оставил бы остальные без отмены. По той же причине
    обычные исключения гасятся — задачу всё равно выбрасывают, а её ошибка не
    должна обрывать уборку соседних.
    """
    current = asyncio.current_task()
    cancels_before = current.cancelling() if current is not None else 0

    for task in tasks:
        if task is None:
            continue
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    if current is not None and current.cancelling() > cancels_before:
        raise asyncio.CancelledError
