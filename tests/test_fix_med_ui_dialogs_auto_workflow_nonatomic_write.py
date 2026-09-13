# -*- coding: utf-8 -*-
"""
ui-dialogs-other/bugs/3-auto-consistency-nonatomic-wri

AutoConsistencyWorker.run() сохранял главы, исправленные AI-consistency
автофиксом, напрямую: ``open(path, "w").write(content)`` — без
temp-файла и os.replace(). Если процесс падает между truncate('w') и
завершением записи буфера (краш, kill -9, OOM), уже переведённая и
провалидированная глава на диске остаётся усечённой без возможности
восстановления.

Каноническая атомарная запись (temp-файл в той же директории + fsync +
os.replace) уже вынесена в gemini_translator.utils.io_utils
(atomic_write_text/atomic_write_bytes, см. dedup cluster-43) и обязана
использоваться вместо инлайн-копий — см.
tests/test_dedup_cluster_43_atomic_write.py, который проверяет ровно
такую же маршрутизацию для chapter_editor.py/ai_bridge.py/repair_store.py.

Тесты ниже гоняют боевое тело AutoConsistencyWorker.run() на минимальном
харнессе: реальный ConsistencyEngine подменён лёгким QObject-стабом
(analyze_chapters/fix_all_chapters), сигналы — настоящие pyqtSignal.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore

from gemini_translator.ui.dialogs import auto_workflow
from gemini_translator.ui.dialogs.auto_workflow import AutoConsistencyWorker
from gemini_translator.utils import io_utils


class _StubConsistencyEngine(QtCore.QObject):
    """Минимальная замена ConsistencyEngine: сигналы настоящие (pyqtSignal),
    остальное — ровно то, что читает AutoConsistencyWorker.run()."""

    progress_updated = QtCore.pyqtSignal(int, int)
    error_occurred = QtCore.pyqtSignal(str)
    log_message = QtCore.pyqtSignal(str)

    def __init__(self, settings_manager):
        super().__init__()
        self.all_problems = [{"confidence": "high"}]
        self.chapter_problems_map = {"ch1.xhtml": [{"confidence": "high"}]}
        self.fixed_files: dict[str, str] = {}
        self.analyze_calls = []
        self.fix_calls = []
        self.close_calls = 0

    def analyze_chapters(self, chapters, config, active_keys, mode):
        self.analyze_calls.append((chapters, config, active_keys, mode))

    def fix_all_chapters(self, chapters, config, active_keys):
        self.fix_calls.append((chapters, config, active_keys))
        return dict(self.fixed_files)

    def get_request_response_trace(self):
        return []

    def close_session_resources(self):
        self.close_calls += 1


def _run_worker_and_collect(worker):
    results = {"finished": None, "failed": None}
    worker.finished_with_result.connect(lambda payload: results.__setitem__("finished", payload))
    worker.failed.connect(lambda message: results.__setitem__("failed", message))
    worker.run()
    return results


def test_auto_consistency_worker_routes_chapter_write_through_atomic_write_text(
    tmp_path, monkeypatch
):
    """Маршрутизация: запись исправленной главы обязана идти через
    io_utils.atomic_write_text, а не через инлайн open(path, "w")."""
    chapter_path = tmp_path / "ch1.xhtml"
    chapter_path.write_text("оригинальный переведённый текст главы", encoding="utf-8")

    stub_engine = _StubConsistencyEngine(settings_manager=None)
    stub_engine.fixed_files = {str(chapter_path): "исправленный текст главы"}
    monkeypatch.setattr(auto_workflow, "ConsistencyEngine", lambda settings_manager: stub_engine)

    calls = []
    real_atomic_write_text = io_utils.atomic_write_text

    def spy(path, text, **kwargs):
        calls.append((str(path), text))
        return real_atomic_write_text(path, text, **kwargs)

    monkeypatch.setattr(auto_workflow, "atomic_write_text", spy, raising=False)

    worker = AutoConsistencyWorker(
        settings_manager=None,
        chapters=[{"name": "ch1.xhtml", "content": "x", "path": str(chapter_path)}],
        config={"consistency_fix_confidences": ["high"]},
        active_keys=["key"],
        auto_fix=True,
    )
    results = _run_worker_and_collect(worker)

    assert results["failed"] is None, results["failed"]
    assert calls, (
        "AutoConsistencyWorker.run() обязан записывать fixed_files через "
        "io_utils.atomic_write_text, а не напрямую через open(path, 'w')"
    )
    assert calls[0] == (str(chapter_path), "исправленный текст главы")
    assert chapter_path.read_text(encoding="utf-8") == "исправленный текст главы"


def test_auto_consistency_worker_preserves_original_chapter_on_write_crash(
    tmp_path, monkeypatch
):
    """Свойство атомарности: если запись обрывается на середине (сбой между
    temp-файлом и os.replace), уже сохранённая на диске глава не должна
    оказаться усечённой/повреждённой — исходное содержимое остаётся как
    было."""
    chapter_path = tmp_path / "ch1.xhtml"
    original_text = "оригинальный переведённый текст главы, который нельзя терять"
    chapter_path.write_text(original_text, encoding="utf-8")

    stub_engine = _StubConsistencyEngine(settings_manager=None)
    stub_engine.fixed_files = {str(chapter_path): "новый текст, который так и не должен примениться"}
    monkeypatch.setattr(auto_workflow, "ConsistencyEngine", lambda settings_manager: stub_engine)

    def crashing_replace(src, dst):
        raise OSError("симуляция краха процесса между temp-файлом и os.replace")

    monkeypatch.setattr(io_utils.os, "replace", crashing_replace)

    worker = AutoConsistencyWorker(
        settings_manager=None,
        chapters=[{"name": "ch1.xhtml", "content": "x", "path": str(chapter_path)}],
        config={"consistency_fix_confidences": ["high"]},
        active_keys=["key"],
        auto_fix=True,
    )
    results = _run_worker_and_collect(worker)

    # Ошибка записи обязана дойти до failed-сигнала, а не быть проглоченной.
    assert results["failed"] is not None
    assert results["finished"] is None
    # Главное свойство: исходный файл на диске не тронут (не усечён, не
    # заменён частичным содержимым) — только temp-файл мог пострадать.
    assert chapter_path.read_text(encoding="utf-8") == original_text
    leftover_temp_files = [p for p in tmp_path.iterdir() if p != chapter_path]
    assert leftover_temp_files == [], (
        "осиротевший temp-файл не должен оставаться после сбоя os.replace"
    )
