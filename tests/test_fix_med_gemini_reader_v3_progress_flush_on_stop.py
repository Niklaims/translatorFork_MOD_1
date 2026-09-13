"""Регресс для gemini-reader/bugs/5-progress-throttle-drops-last-w.

До фикса GeminiWorker.main_loop не гарантировал запись последней достигнутой
позиции при остановке посреди главы: bm.save_progress троттлит реальную
запись на диск не чаще раза в READER_PROGRESS_SAVE_INTERVAL_SEC секунд, а
единственный вызов save_progress внутри main_loop передавал force=True
только когда глава полностью завершена. Если пользователь останавливал
чтение ровно в момент, когда очередной прогресс попадал в двухсекундное
окно троттлинга, эта последняя позиция терялась — при следующем запуске
воркер начинал с более старой сохранённой позиции.

Тест гоняет РЕАЛЬНОЕ тело GeminiWorker.main_loop на минимальном харнессе
(сетевой обмен с Gemini подменён фейковым сборщиком аудио) и проверяет
итог на настоящем BookManager.save_progress/load_progress (файл на диске
во временной директории), а не на моках.
"""
import asyncio
import os
import queue
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gemini_reader_v3 as reader
from gemini_reader_v3 import BookManager, GeminiWorker


class _SignalSpy:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _ChapterQueueOnce:
    """Отдаёт единственный номер главы, затем всегда queue.Empty — как реальная
    manager_chapter_queue после того, как все главы разобраны воркерами."""

    def __init__(self, chapter_index):
        self._chapter_index = chapter_index
        self._served = False

    def get_nowait(self):
        if self._served:
            raise queue.Empty()
        self._served = True
        return self._chapter_index


class _FakeChapter:
    def __init__(self, sentences):
        self.flat_sentences = list(sentences)
        self.paragraphs = []
        self.raw_text = ""


class _MainLoopHarness:
    """Реальное тело main_loop + сопутствующих боевых методов воркера;
    сеть (клиент Gemini, сборка аудио) подменена, чтобы тест не зависел от
    google-genai и не ходил в сеть."""

    main_loop = GeminiWorker.main_loop
    _cached_chapter_segments = GeminiWorker._cached_chapter_segments
    _invalidate_chapter_segments_cache = GeminiWorker._invalidate_chapter_segments_cache
    _chapter_segments = GeminiWorker._chapter_segments
    _emit_worker_progress = GeminiWorker._emit_worker_progress
    _commit_live_audio_bytes = GeminiWorker._commit_live_audio_bytes
    _emit_finished = GeminiWorker._emit_finished
    _join_segments_for_request = GeminiWorker._join_segments_for_request

    def __init__(self, bm, manager_chapter_queue):
        self.worker_id = 0
        self.api_key = "fake-key"
        self.bm = bm
        self.audio_queue = None
        self.model_id = "models/fake"
        self.voice = "Puck"
        self.style_prompt = ""
        self.speed = "Normal"
        self.record = False
        self.fast = True
        self.chunk = 1
        self.segment_mode = "sentences"
        self.voice_mode = "single"
        self.secondary_voice = self.voice
        self.tertiary_voice = self.voice
        self.manager_chapter_queue = manager_chapter_queue
        self.c_idx = -1
        self.s_idx = 0
        self._is_running = True
        self.buffer_lock = threading.Lock()
        self.audio_chunks = []
        self._last_progress_emit_payload = None
        self._last_progress_emit_at = 0.0
        self._segments_cache_chapter_idx = None
        self._segments_cache = None
        self.error_signal = _SignalSpy()
        self.chapter_done_ui_signal = _SignalSpy()
        self.change_chapter_signal = _SignalSpy()
        self.worker_progress = _SignalSpy()
        self.finished_signal = _SignalSpy()
        self._finished_emitted = False

    async def _wait_before_worker_start(self, stagger_seconds):
        return None

    def _live_voice_descriptor(self):
        return self.voice

    def _reset_live_mp3_autosave(self):
        pass

    def _build_live_request_payload(self, text):
        prepared = (text or "").strip()
        if not prepared:
            return None
        return {"text": prepared, "config": None}

    async def save_file(self, final=False):
        return None


class GeminiReaderProgressFlushOnStopTests(unittest.TestCase):
    def test_stop_mid_chapter_flushes_last_progress_past_throttle_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bm = BookManager()
            bm.book_dir = temp_dir
            bm.chapters = [_FakeChapter(["Раз.", "Два.", "Три.", "Четыре."])]

            harness = _MainLoopHarness(bm, _ChapterQueueOnce(0))

            call_count = {"n": 0}

            async def fake_collect_raw_audio(client, config, text_to_send, on_chunk=None):
                call_count["n"] += 1
                if call_count["n"] == 2:
                    # Пользователь жмёт "Стоп" сразу после того, как второй батч
                    # уже получен от Gemini -- ровно сценарий из failure_scenario.
                    harness._is_running = False
                return b"audio-bytes"

            harness._collect_live_request_raw_audio = fake_collect_raw_audio

            with mock.patch.object(reader, "genai", object()), \
                 mock.patch.object(reader, "genai_types", object()), \
                 mock.patch.object(reader, "_make_genai_client", return_value=object()):
                asyncio.run(harness.main_loop())

            # Второй save_progress (0, 2) попадает в двухсекундное окно троттлинга
            # сразу после первого настоящего диска-write (0, 1) -- без фикса это
            # значение осталось бы только в памяти и потерялось при остановке.
            self.assertEqual(bm.load_progress(), (0, 2))
            self.assertFalse(harness._is_running)
            self.assertEqual(harness.c_idx, 0)
            self.assertEqual(harness.s_idx, 2)
            self.assertEqual(call_count["n"], 2)

    def test_finished_chapter_does_not_spuriously_flush_after_reset(self):
        """Если глава уже полностью завершена и c_idx сброшен в -1 (воркер
        уходит на _emit_finished/break из-за пустой очереди), финальный flush
        в finally должен промолчать -- иначе он перезаписал бы progress_v19.json
        мусорным значением (chapter=-1, sentence=0) поверх честного (0, 1)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bm = BookManager()
            bm.book_dir = temp_dir
            bm.chapters = [_FakeChapter(["Раз."])]

            harness = _MainLoopHarness(bm, _ChapterQueueOnce(0))

            async def fake_collect_raw_audio(client, config, text_to_send, on_chunk=None):
                return b"audio-bytes"

            harness._collect_live_request_raw_audio = fake_collect_raw_audio

            with mock.patch.object(reader, "genai", object()), \
                 mock.patch.object(reader, "genai_types", object()), \
                 mock.patch.object(reader, "_make_genai_client", return_value=object()):
                asyncio.run(harness.main_loop())

            self.assertTrue(bm.is_chapter_done(0))
            self.assertEqual(harness.c_idx, -1)
            self.assertEqual(bm.load_progress(), (0, 1))


if __name__ == "__main__":
    unittest.main()
