"""Регресс для gemini-reader/bugs/6-chapter-segments-recomputed-pe.

До фикса GeminiWorker.main_loop вычислял список сегментов текущей главы
заново на каждой итерации внешнего while-цикла (то есть на каждый батч,
отправляемый в Live API) ДВУМЯ отдельными вызовами self._chapter_segments:
один -- только чтобы получить total_sent, второй -- чтобы получить сами
сегменты для нарезки запроса. Для voice_mode == "author_gender" это означает
повторное чтение TTS-сценария главы с диска и его повторный разбор на
каждый запрос; для segment_mode == "paragraphs" -- повторный регэксп-разбор
всех абзацев главы. Фикс кэширует сегменты один раз на главу
(_cached_chapter_segments) и переиспользует кэш до смены главы.

Тест проверяет алгоритмическое свойство (число обращений к дорогому
_chapter_segments за всю обработку главы), а не секунды: гоняет РЕАЛЬНОЕ
тело main_loop на минимальном харнессе с несколькими батчами внутри одной
главы и считает реальные вызовы _chapter_segments.
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


class GeminiReaderChapterSegmentsCacheTests(unittest.TestCase):
    def test_chapter_taken_once_computes_segments_only_once_for_whole_chapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bm = BookManager()
            bm.book_dir = temp_dir
            sentences = ["Раз.", "Два.", "Три.", "Четыре."]
            bm.chapters = [_FakeChapter(sentences)]

            harness = _MainLoopHarness(bm, _ChapterQueueOnce(0))

            # Оборачиваем боевой _chapter_segments счётчиком вызовов, не подменяя
            # его поведение -- считаем именно обращения к дорогому вычислению.
            calls = []
            real_chapter_segments = harness._chapter_segments

            def counting_chapter_segments(chapter_index):
                calls.append(chapter_index)
                return real_chapter_segments(chapter_index)

            harness._chapter_segments = counting_chapter_segments

            async def fake_collect_raw_audio(client, config, text_to_send, on_chunk=None):
                return b"audio-bytes"

            harness._collect_live_request_raw_audio = fake_collect_raw_audio

            with mock.patch.object(reader, "genai", object()), \
                 mock.patch.object(reader, "genai_types", object()), \
                 mock.patch.object(reader, "_make_genai_client", return_value=object()):
                asyncio.run(harness.main_loop())

            # Глава из 4 предложений при chunk=1 -- это 4 батча (4 обращения к
            # Live API), то есть до фикса было бы минимум 2*4-1 = 7 вызовов
            # _chapter_segments (total_sent и segments на каждой итерации, кроме
            # самой первой, где total_sent считается при взятии главы). После
            # фикса -- ровно один вызов на всю главу.
            self.assertEqual(calls, [0])
            self.assertTrue(bm.is_chapter_done(0))
            self.assertEqual(harness.s_idx, len(sentences))

    def test_cache_recomputes_after_new_chapter_is_taken(self):
        """Кэш не должен «залипать» на старой главе: как только воркер берёт
        новую главу (даже с тем же индексом после возврата в очередь), сегменты
        обязаны быть пересчитаны заново."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bm = BookManager()
            bm.book_dir = temp_dir
            bm.chapters = [_FakeChapter(["Раз.", "Два."]), _FakeChapter(["Три.", "Четыре.", "Пять."])]

            class _TwoChapterQueue:
                def __init__(self):
                    self._items = [0, 1]

                def get_nowait(self):
                    if not self._items:
                        raise queue.Empty()
                    return self._items.pop(0)

            harness = _MainLoopHarness(bm, _TwoChapterQueue())

            calls = []
            real_chapter_segments = harness._chapter_segments

            def counting_chapter_segments(chapter_index):
                calls.append(chapter_index)
                return real_chapter_segments(chapter_index)

            harness._chapter_segments = counting_chapter_segments

            async def fake_collect_raw_audio(client, config, text_to_send, on_chunk=None):
                return b"audio-bytes"

            harness._collect_live_request_raw_audio = fake_collect_raw_audio

            with mock.patch.object(reader, "genai", object()), \
                 mock.patch.object(reader, "genai_types", object()), \
                 mock.patch.object(reader, "_make_genai_client", return_value=object()):
                asyncio.run(harness.main_loop())

            # Один пересчёт на каждую из двух глав -- кэш не путает главы между
            # собой и не пропускает пересчёт при смене c_idx.
            self.assertEqual(calls, [0, 1])
            self.assertTrue(bm.is_chapter_done(0))
            self.assertTrue(bm.is_chapter_done(1))


if __name__ == "__main__":
    unittest.main()
