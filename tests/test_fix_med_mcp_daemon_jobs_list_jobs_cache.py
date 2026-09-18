"""Регресс для perf:cpu-idle-background/3-mcp-jobs-list-unbounded-growth.

Дефект: list_jobs(state_dir) на каждый вызов делает root.glob('*/job.json')
и для КАЖДОГО файла — path.read_text()+json.loads(), без какого-либо
кэширования. Функция вызывается на каждый /status (McpDaemon.status_payload)
— GUI-виджет опрашивает раз в 2.5с, пока выбран провайдер MCP — то есть
стоимость линейно растёт с числом задач, когда-либо созданных за всё время
жизни установки, включая давно завершённые, чей job.json больше никогда не
меняется.

Тест проверяет алгоритмическое свойство: повторный вызов list_jobs() без
изменений на диске не должен заново читать и парсить файлы, чьё содержимое
не менялось (mtime не изменился) — а при изменении одного файла должен
перечитать РОВНО его, не трогая остальные.

Счётчик патчит не сам стандартный модуль json (jobs_mod.json — это тот же
объект, что sys.modules['json'], и правка его атрибута .loads была бы видна
процессно любому другому коду, использующему json.loads в этот момент), а
только module-level имя `json` внутри пространства имён jobs_mod — так
считаются исключительно разборы, сделанные из list_jobs()/load_job(), и
ничей больше код не подменяется.
"""

from __future__ import annotations

import json as real_json
import os
import shutil
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gemini_translator.mcp import jobs as jobs_mod
from gemini_translator.mcp.jobs import create_job, job_path, list_jobs, mark_finished, save_job


class _CountingJsonProxy:
    """Прокси на месте jobs_mod.json: считает вызовы loads(), остальное
    (dumps и т.д.) форвардит в настоящий модуль json без изменений."""

    def __init__(self, calls: dict):
        self._calls = calls

    def loads(self, *args, **kwargs):
        self._calls["n"] += 1
        return real_json.loads(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(real_json, name)


class ListJobsAvoidsReparsingUnchangedFilesTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)

    def _count_json_loads(self):
        """Возвращает (счётчик вызовов, отменить патч). Патчит только имя
        `json` внутри jobs_mod, не сам стандартный модуль json."""
        calls = {"n": 0}
        real_json_name = jobs_mod.json
        jobs_mod.json = _CountingJsonProxy(calls)

        def undo():
            jobs_mod.json = real_json_name

        return calls, undo

    def test_second_call_does_not_reparse_unchanged_job_files(self):
        job_a = create_job(self.state_dir, "translation", ["a"], project=None, epub=None)
        job_b = create_job(self.state_dir, "translation", ["b"], project=None, epub=None)
        job_c = create_job(self.state_dir, "translation", ["c"], project=None, epub=None)

        first = list_jobs(self.state_dir)
        self.assertEqual({job.id for job in first}, {job_a.id, job_b.id, job_c.id})

        calls, undo = self._count_json_loads()
        self.addCleanup(undo)

        second = list_jobs(self.state_dir)

        self.assertEqual(
            calls["n"],
            0,
            "list_jobs() перечитал job.json файлов, которые не менялись на диске",
        )
        # Данные при этом должны остаться корректными (не пустой список,
        # не устаревшее содержимое).
        self.assertEqual({job.id for job in second}, {job_a.id, job_b.id, job_c.id})
        self.assertEqual(
            {job.id: job.status for job in second},
            {job_a.id: "queued", job_b.id: "queued", job_c.id: "queued"},
        )

    def test_only_the_changed_job_file_is_reparsed(self):
        job_a = create_job(self.state_dir, "translation", ["a"], project=None, epub=None)
        job_b = create_job(self.state_dir, "translation", ["b"], project=None, epub=None)

        list_jobs(self.state_dir)  # прогреваем кэш

        # Меняем содержимое job_b и явно отодвигаем mtime вперёд на секунды,
        # чтобы проверка не зависела от разрешения часов файловой системы.
        mark_finished(job_b, status="succeeded", exit_code=0)
        save_job(self.state_dir, job_b)
        path_b = job_path(self.state_dir, job_b.id)
        bumped_ns = path_b.stat().st_mtime_ns + 5_000_000_000
        os.utime(path_b, ns=(bumped_ns, bumped_ns))

        calls, undo = self._count_json_loads()
        self.addCleanup(undo)

        result = list_jobs(self.state_dir)

        self.assertEqual(calls["n"], 1, "должен быть перечитан ровно один изменившийся файл")
        by_id = {job.id: job for job in result}
        self.assertEqual(by_id[job_a.id].status, "queued")
        self.assertEqual(by_id[job_b.id].status, "succeeded")

        # Контроль: то, что вернула функция, совпадает с тем, что реально
        # лежит на диске (кэш не «застревает» на устаревших данных).
        raw_b = real_json.loads(path_b.read_text(encoding="utf-8"))
        self.assertEqual(by_id[job_b.id].status, raw_b["status"])

    def test_returned_records_are_private_and_mutation_does_not_poison_cache(self):
        """Регресс для major-замечания рецензента: до фикса кэш хранил
        разобранный JobRecord и раздавал ОДИН И ТОТ ЖЕ изменяемый инстанс
        всем вызывающим list_jobs(). Боевой путь (_pipeline_allows_start ->
        mark_finished в daemon.py) правит запись НА МЕСТЕ ДО save_job — если
        бы кэш отдавал общий инстанс, такая мутация была бы видна всем
        остальным вызовам НАВСЕГДА, даже если последующий save_job падает
        (OSError, права, диск) и не успевает записать изменения на диск."""
        job_a = create_job(self.state_dir, "translation", ["a"], project=None, epub=None)

        first = list_jobs(self.state_dir)
        second = list_jobs(self.state_dir)
        rec1 = next(job for job in first if job.id == job_a.id)
        rec2 = next(job for job in second if job.id == job_a.id)
        self.assertIsNot(
            rec1,
            rec2,
            "list_jobs() раздаёт один и тот же изменяемый инстанс JobRecord нескольким вызовам",
        )

        # Мутируем запись ровно так, как это делает mark_finished в боевом
        # коде, и намеренно НЕ вызываем save_job — эмулируем сценарий, когда
        # запись на диск после этого падает.
        mark_finished(rec1, status="cancelled", exit_code=None, error="boom")

        third = list_jobs(self.state_dir)
        rec3 = next(job for job in third if job.id == job_a.id)
        self.assertEqual(
            rec3.status,
            "queued",
            "мутация записи, вернувшейся из list_jobs(), без save_job отравила кэш и результат следующего вызова",
        )

    def test_cache_drops_entries_for_removed_job_directories(self):
        """Регресс для minor-замечания рецензента: кэш не должен держать в
        памяти записи задач, чей job.json уже удалён с диска — иначе он
        растёт монотонно вместе со всей историей jobs/ за весь срок жизни
        демона (демон живёт сутками), просто перенося исходную проблему
        «jobs/ копится бессрочно» с диска в память процесса."""
        job_a = create_job(self.state_dir, "translation", ["a"], project=None, epub=None)
        job_b = create_job(self.state_dir, "translation", ["b"], project=None, epub=None)

        list_jobs(self.state_dir)  # прогреваем кэш обеими записями
        path_a = str(job_path(self.state_dir, job_a.id).resolve())
        path_b = str(job_path(self.state_dir, job_b.id).resolve())
        with jobs_mod._LIST_JOBS_CACHE_LOCK:
            self.assertIn(path_a, jobs_mod._LIST_JOBS_CACHE)
            self.assertIn(path_b, jobs_mod._LIST_JOBS_CACHE)

        shutil.rmtree(job_path(self.state_dir, job_a.id).parent)

        remaining = list_jobs(self.state_dir)

        self.assertEqual({job.id for job in remaining}, {job_b.id})
        with jobs_mod._LIST_JOBS_CACHE_LOCK:
            self.assertNotIn(
                path_a,
                jobs_mod._LIST_JOBS_CACHE,
                "кэш держит запись задачи, чья директория уже удалена с диска",
            )
            self.assertIn(path_b, jobs_mod._LIST_JOBS_CACHE)


if __name__ == "__main__":
    unittest.main()
