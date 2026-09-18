"""Хвост perf:disk-reads/1 (кэш исходного EPUB в qa/assembly).

Кэш держит открытый zipfile исходной книги; close_cached_source_archives()
появился вместе с ним, но из боевого кода не вызывался — дескриптор жил бы
до смены книги или выхода из приложения (на Windows это блокирует
перемещение/удаление EPUB). Теперь кэш закрывается (а) при отсоединении
координатора проверки (конец сессии перевода, пересборка ручного
координатора) и (б) когда контроллер окна качества выходит из состояния
«занят» — то есть по окончании каждого прохода или проверки главы.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import gemini_translator.qa.assembly as assembly
import gemini_translator.ui.dialogs.validation_dialogs.translation_quality_controller as controller_module
from gemini_translator.ui.dialogs.validation_dialogs.translation_quality_controller import (
    TranslationQualityController,
)


class _Coordinator:
    def __init__(self):
        self.shutdown_calls = 0

    def shutdown(self, timeout=None):
        self.shutdown_calls += 1


def test_detach_coordinator_closes_cached_source_archives():
    coordinator = _Coordinator()
    app = SimpleNamespace(qa_coordinator=coordinator)
    with mock.patch.object(assembly, "close_cached_source_archives") as close_spy:
        assembly.detach_chapter_qa_coordinator(app)
    close_spy.assert_called_once_with()
    assert coordinator.shutdown_calls == 1
    assert app.qa_coordinator is None


def test_controller_releases_source_archives_when_it_stops_being_busy(qapp):
    controller = TranslationQualityController(
        coordinator_provider=lambda: None,
        journal_loader=lambda: None,
        gates_provider=lambda: (),
        event_builder=lambda chapter_ids: (),
    )
    with mock.patch.object(controller_module, "close_cached_source_archives") as close_spy:
        controller._set_busy(True)
        close_spy.assert_not_called()      # на старте прохода архив ещё нужен
        controller._set_busy(False)
        close_spy.assert_called_once_with()
        controller._set_busy(False)        # повторный «не занят» — не повод закрывать снова
        close_spy.assert_called_once_with()
