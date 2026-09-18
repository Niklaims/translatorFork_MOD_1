"""
Регресс на perf:memory-retention/3-memfs-task-payload-never-freed
(и на замечания рецензента к первой версии этого фикса).

_normalize_payload кладёт исходный EPUB в общий mem_fs через os.copy_to_mem
(без unique=True) при КАЖДОЙ постановке книги в очередь. Копии освобождаются
в clear_all_queues (момент, когда очередь опустошается целиком и без
последующей вставки новых задач) через _release_tracked_virtual_epub_paths.

Ключевое условие, которое эти тесты проверяют на БОЕВОМ os_patch (реальный
MiniMemFS, реальные copy_to_mem/_patched_remove — не моки их возвращаемых
значений): освобождение памяти НЕ должно ломать восстановление снимка общей
очереди в AI-фиксере недоперевода. Последовательность там такая:
  1. get_all_pending_tasks() снимает payload, где file_data уже 'mem://…';
  2. clear_all_queues() — memfs-копия освобождается;
  3. позже add_pending_tasks(снимок) -> _normalize_payload('mem://…') —
     copy_to_mem видит несуществующий источник и раньше молча возвращал
     старый мёртвый путь; теперь _normalize_payload обязан пересоздать
     копию из запомненного реального пути книги (self._virtual_epub_sources).

Также проверяется гонка: add_priority_tasks может вызываться из потока
воркера (emerger_tasks.py режет главу на чанки), пока GUI-поток вызывает
clear_all_queues -> _release_tracked_virtual_epub_paths — доступ к
_active_virtual_epub_paths/_virtual_epub_sources должен быть под общим
замком, иначе возможна RuntimeError: Set changed size during iteration и
потеря пути, добавленного между чтением и очисткой множества.
"""
import io
import threading
import time
import types
import unittest
from unittest import mock

import os_patch
from gemini_translator.core.task_manager import ChapterQueueManager


class _FakeWriteConn:
    """Минимальная замена self._get_write_conn(): просто копит execute()."""

    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(sql)


class _FakeCursor:
    def __enter__(self):
        self._conn = _FakeWriteConn()
        return self._conn

    def __exit__(self, *exc_info):
        return False


class VirtualEpubReleaseTests(unittest.TestCase):
    def _make_stub(self):
        tm = types.SimpleNamespace(
            _active_virtual_epub_paths=set(),
            _virtual_epub_sources={},
            _virtual_paths_lock=threading.Lock(),
            _log=lambda *a, **k: None,
            _get_write_conn=lambda: _FakeCursor(),
            _safe_request_ui_update=lambda: None,
        )
        tm._normalize_payload = types.MethodType(ChapterQueueManager._normalize_payload, tm)
        tm._release_tracked_virtual_epub_paths = types.MethodType(
            ChapterQueueManager._release_tracked_virtual_epub_paths, tm
        )
        tm.clear_all_queues = types.MethodType(ChapterQueueManager.clear_all_queues, tm)
        return tm

    def _isolated_mem_fs(self):
        """
        Контекстный менеджер: подменяет только os_patch._get_or_create_mem_fs
        на свежий MiniMemFS (как test_memfs_epub_lifecycle.py), а не зовёт
        необратимый os_patch.apply() — тот патчит builtins.open, os.path,
        zipfile.ZipFile.__init__ и sqlite3.connect глобально и без отката,
        что недопустимо в общем тестовом процессе.
        """
        mem_fs = os_patch.MiniMemFS()
        return mem_fs

    def test_normalize_payload_tracks_created_virtual_path_in_real_memfs(self):
        """
        _normalize_payload должен создать в РЕАЛЬНОМ mem_fs (не в моке)
        читаемую копию и запомнить и виртуальный путь (для последующего
        освобождения), и исходный реальный путь книги (для последующего
        восстановления после освобождения).
        """
        import tempfile

        mem_fs = self._isolated_mem_fs()
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                real_path = f"{tmp_dir}/fake_book.epub"
                with open(real_path, "wb") as fh:
                    fh.write(b"epub-bytes")

                tm = self._make_stub()
                with mock.patch.object(os_patch, "_get_or_create_mem_fs", lambda: mem_fs), \
                        mock.patch(
                            "gemini_translator.core.task_manager.os.copy_to_mem",
                            os_patch.copy_to_mem,
                            create=True,
                        ):
                    result = tm._normalize_payload(("epub", real_path, "extra"))

                self.assertEqual(result[0], "epub")
                self.assertEqual(result[2:], ("extra",))
                virtual_path = result[1]
                self.assertTrue(virtual_path.startswith("mem://"))
                self.assertIn(virtual_path, tm._active_virtual_epub_paths)
                self.assertEqual(tm._virtual_epub_sources.get(virtual_path), real_path)

                internal = virtual_path[len("mem://"):]
                self.assertTrue(mem_fs.exists(internal))
                with mem_fs.openbin(internal) as fh:
                    self.assertEqual(fh.read(), b"epub-bytes")
        finally:
            mem_fs.close()

    def test_clear_all_queues_releases_memfs_copy_but_keeps_source_mapping(self):
        """
        clear_all_queues должен реально стереть данные из mem_fs (не только
        забыть про путь на стороне TaskManager) и забыть про сам виртуальный
        путь в _active_virtual_epub_paths — но НЕ должен стирать
        _virtual_epub_sources: это соответствие нужно, чтобы восстановить
        снимок общей очереди фиксера (см. следующий тест).
        """
        import tempfile

        mem_fs = self._isolated_mem_fs()
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                real_path = f"{tmp_dir}/book_a.epub"
                with open(real_path, "wb") as fh:
                    fh.write(b"book-a-bytes")

                tm = self._make_stub()
                with mock.patch.object(os_patch, "_get_or_create_mem_fs", lambda: mem_fs), \
                        mock.patch(
                            "gemini_translator.core.task_manager.os.copy_to_mem",
                            os_patch.copy_to_mem,
                            create=True,
                        ):
                    result = tm._normalize_payload(("epub", real_path))
                virtual_path = result[1]
                internal = virtual_path[len("mem://"):]
                self.assertTrue(mem_fs.exists(internal))

                with mock.patch.object(os_patch, "_get_or_create_mem_fs", lambda: mem_fs), \
                        mock.patch(
                            "gemini_translator.core.task_manager.os.remove",
                            os_patch._patched_remove,
                            create=True,
                        ):
                    tm.clear_all_queues()

                self.assertEqual(tm._active_virtual_epub_paths, set())
                self.assertFalse(
                    mem_fs.exists(internal),
                    "clear_all_queues должен реально освободить содержимое memfs-копии",
                )
                self.assertEqual(
                    tm._virtual_epub_sources.get(virtual_path),
                    real_path,
                    "соответствие виртуальный->реальный путь не должно стираться при "
                    "освобождении - оно нужно для восстановления снимка очереди",
                )
        finally:
            mem_fs.close()

    def test_normalize_payload_recovers_readable_copy_after_release(self):
        """
        БЛОКЕР из ревью: воспроизводит цепочку AI-фиксера недоперевода —
        normalize(реальный путь) -> clear_all_queues (копия освобождена) ->
        normalize(тот же виртуальный путь из старого снимка). Раньше второй
        вызов молча возвращал МЁРТВЫЙ путь (copy_to_mem видел отсутствующий
        источник и возвращал None, а _normalize_payload — payload_tuple без
        изменений). Теперь он обязан пересоздать копию из запомненного
        реального пути книги, и итоговый путь должен быть ЧИТАЕМЫМ.
        """
        import tempfile

        mem_fs = self._isolated_mem_fs()
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                real_path = f"{tmp_dir}/book.epub"
                with open(real_path, "wb") as fh:
                    fh.write(b"original-epub-bytes")

                tm = self._make_stub()
                with mock.patch.object(os_patch, "_get_or_create_mem_fs", lambda: mem_fs), \
                        mock.patch(
                            "gemini_translator.core.task_manager.os.copy_to_mem",
                            os_patch.copy_to_mem,
                            create=True,
                        ):
                    snapshot_payload = tm._normalize_payload(("epub", real_path))
                virtual_path = snapshot_payload[1]

                # clear_all_queues: снимок общей очереди фиксера уже сохранён
                # (в самом фиксере) с virtual_path выше, ДО этого вызова.
                with mock.patch.object(os_patch, "_get_or_create_mem_fs", lambda: mem_fs), \
                        mock.patch(
                            "gemini_translator.core.task_manager.os.remove",
                            os_patch._patched_remove,
                            create=True,
                        ):
                    tm.clear_all_queues()

                internal = virtual_path[len("mem://"):]
                self.assertFalse(
                    mem_fs.exists(internal),
                    "предусловие: memfs-копия должна быть реально освобождена",
                )

                # add_pending_tasks(снимок) -> _normalize_payload('mem://…')
                with mock.patch.object(os_patch, "_get_or_create_mem_fs", lambda: mem_fs), \
                        mock.patch(
                            "gemini_translator.core.task_manager.os.copy_to_mem",
                            os_patch.copy_to_mem,
                            create=True,
                        ):
                    restored_payload = tm._normalize_payload(("epub", virtual_path))

                restored_virtual_path = restored_payload[1]
                restored_internal = restored_virtual_path[len("mem://"):]
                self.assertTrue(
                    mem_fs.exists(restored_internal),
                    "после освобождения повторная нормализация уже виртуального "
                    "payload обязана дать РЕАЛЬНО существующую копию, а не мёртвый путь",
                )
                with mem_fs.openbin(restored_internal) as fh:
                    self.assertEqual(
                        fh.read(),
                        b"original-epub-bytes",
                        "восстановленная копия должна читаться и содержать данные книги",
                    )
        finally:
            mem_fs.close()

    def test_release_survives_missing_os_remove_patch(self):
        """
        Если патч 'os' не применён (нет os.remove для виртуальных путей),
        освобождение не должно ронять очистку очереди — как и _normalize_payload
        уже терпит AttributeError у os.copy_to_mem.
        """
        tm = self._make_stub()
        tm._active_virtual_epub_paths = {"mem://books/orphan.epub"}

        try:
            tm._release_tracked_virtual_epub_paths()
        except Exception as exc:  # pragma: no cover - defensive assertion
            self.fail(f"_release_tracked_virtual_epub_paths не должен падать: {exc!r}")

        self.assertEqual(tm._active_virtual_epub_paths, set())

    def test_concurrent_normalize_and_release_do_not_race(self):
        """
        MAJOR из ревью: add_priority_tasks (через _normalize_payload) может
        выполняться в потоке воркера (emerger_tasks.py режет главу на чанки),
        пока GUI-поток вызывает clear_all_queues -> _release_tracked_virtual_epub_paths.
        Без общего замка операция "прочитать всё множество и очистить его" в
        релизе, идущая параллельно с add() в normalize, теряет путь,
        добавленный МЕЖДУ чтением и очисткой множества - навсегда, поскольку
        clear() стирает и его тоже.

        Вместо вероятностной гонки на таймингах открываем это окно
        детерминированно: подменяем _active_virtual_epub_paths на set с
        переопределённым clear(), который сигналит о начале очистки и
        специально "засыпает" перед реальной работой. normalize-поток ждёт
        этого сигнала и в этот самый момент пытается добавить новый путь.

        Без общего замка add() успевает выполниться, пока release ещё "спит"
        внутри clear() (до его исполнения), и наступающий следом
        super().clear() стирает и добавленный путь - test must fail:
        новый путь исчезает бесследно. С общим замком add() блокируется на
        входе в критическую секцию до выхода release из неё, так что путь,
        добавленный после реальной очистки, не теряется.
        """
        release_gate = threading.Event()

        class _GatedClearSet(set):
            """
            Сет для теста: clear() сигналит о начале операции и уступает
            поток перед реальной очисткой - открывает окно для гонки, если
            вызывающий код не защищает эту операцию замком.
            """

            def clear(self):
                release_gate.set()
                time.sleep(0.05)
                super().clear()

        tm = self._make_stub()
        tm._active_virtual_epub_paths = _GatedClearSet({"mem://pre-existing.epub"})

        new_virtual_path = "mem://synthetic/new_chunk.tmp"
        removed_paths = []
        release_errors = []
        normalize_errors = []

        def _release_worker():
            try:
                tm._release_tracked_virtual_epub_paths()
            except Exception as exc:  # noqa: BLE001 - фиксируем саму гонку
                release_errors.append(exc)

        def _normalize_worker():
            # Дожидаемся именно того момента, когда release уже прочитал
            # множество и начал его очищать (но ещё не закончил) - это и
            # есть окно гонки, которое должен закрывать общий замок.
            if not release_gate.wait(timeout=5):
                normalize_errors.append(TimeoutError("release не подал сигнал вовремя"))
                return
            try:
                tm._normalize_payload(("epub", io.BytesIO(b"x")))
            except Exception as exc:  # noqa: BLE001
                normalize_errors.append(exc)

        with mock.patch(
            "gemini_translator.core.task_manager.os.remove",
            side_effect=removed_paths.append,
            create=True,
        ), mock.patch(
            "gemini_translator.core.task_manager.os.write_bytes_to_mem",
            return_value=new_virtual_path,
            create=True,
        ):
            release_thread = threading.Thread(target=_release_worker)
            normalize_thread = threading.Thread(target=_normalize_worker)
            release_thread.start()
            normalize_thread.start()
            release_thread.join(timeout=5)
            normalize_thread.join(timeout=5)

        self.assertFalse(release_thread.is_alive(), "поток release завис")
        self.assertFalse(normalize_thread.is_alive(), "поток normalize завис")
        self.assertEqual(release_errors, [], f"release не должен падать: {release_errors!r}")
        self.assertEqual(normalize_errors, [], f"normalize не должен падать: {normalize_errors!r}")

        self.assertEqual(
            removed_paths,
            ["mem://pre-existing.epub"],
            "release должен освободить ровно то, что было отслежено до его вызова",
        )
        self.assertIn(
            new_virtual_path,
            tm._active_virtual_epub_paths,
            "путь, добавленный normalize ровно в момент release (между чтением и "
            "очисткой множества), не должен теряться - иначе он никогда не "
            "освободится и утечёт в mem_fs до выхода из приложения",
        )


if __name__ == "__main__":
    unittest.main()
