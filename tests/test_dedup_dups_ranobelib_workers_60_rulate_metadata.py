"""Дедуп dups-ranobelib_workers-60 (duplicate-rulate-metadata-fetch).

RulateToRanobeMetadataWorker.run и RulateToRanobeCreateWorker._read_rulate_metadata
независимо повторяли одну процедуру: persistent-контекст на
QIDIAN_RULATE_PROFILE_DIR -> первая страница -> goto(edit/info) -> пауза ->
evaluate(_RULATE_MEDIA_EXTRACT_SCRIPT) -> _merge_public_rulate_cover ->
_normalize_rulate_media_payload. Общая часть вынесена в
_fetch_rulate_edit_metadata; единственное различие (в каком поле воркер
держит браузер для stop()) передаётся колбэком on_browser, а закрытие
браузера остаётся на вызывающем, как и было.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

TESTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
RANOBELIB_DIR = os.path.join(PROJECT_ROOT, "ranobelib")
if RANOBELIB_DIR not in sys.path:
    sys.path.insert(0, RANOBELIB_DIR)

import workers as rl_workers  # noqa: E402  (ranobelib/workers.py как top-level "workers")

EDIT_URL = "https://tl.rulate.ru/book/1/edit/info"
PUBLIC_URL = "https://tl.rulate.ru/book/1"


class _FakePage:
    def __init__(self):
        self.calls = []

    def goto(self, url, **kwargs):
        self.calls.append(("goto", url, kwargs))

    def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))

    def evaluate(self, script):
        self.calls.append(("evaluate", script))
        return {"raw": True}


class _FakeBrowser:
    def __init__(self, page):
        self.pages = [page]
        self.closed = False

    def new_page(self):
        raise AssertionError("должна использоваться уже открытая первая страница")

    def close(self):
        self.closed = True


class _FakePlaywright:
    def __enter__(self):
        return "pw"

    def __exit__(self, *args):
        return False


class FetchRulateEditMetadataCharacterizationTests(unittest.TestCase):
    def test_sequence_matches_both_former_copies(self):
        page = _FakePage()
        browser = _FakeBrowser(page)
        log = mock.Mock()
        seen = []
        with mock.patch.object(rl_workers, "_launch_persistent_chromium_context", return_value=browser) as launch, \
                mock.patch.object(rl_workers, "_merge_public_rulate_cover",
                                  side_effect=lambda p, raw, url, lg: {**raw, "merged": url}) as merge, \
                mock.patch.object(rl_workers, "_normalize_rulate_media_payload",
                                  side_effect=lambda raw, src: {"title_ru": "T", "raw": raw, "src": src}) as norm:
            result = rl_workers._fetch_rulate_edit_metadata(
                "pw", rulate_edit_url=EDIT_URL, rulate_url=PUBLIC_URL, log=log, on_browser=seen.append,
            )
        launch.assert_called_once_with(
            "pw",
            user_data_dir=str(rl_workers.QIDIAN_RULATE_PROFILE_DIR),
            viewport={"width": 1280, "height": 900},
            log_callback=log,
        )
        self.assertEqual(seen, [browser])
        self.assertEqual(page.calls, [
            ("goto", EDIT_URL, {"wait_until": "domcontentloaded", "timeout": 60000}),
            ("wait", 2500),
            ("evaluate", rl_workers._RULATE_MEDIA_EXTRACT_SCRIPT),
        ])
        merge.assert_called_once_with(page, {"raw": True}, PUBLIC_URL, log)
        norm.assert_called_once_with({"raw": True, "merged": PUBLIC_URL}, EDIT_URL)
        self.assertEqual(result["title_ru"], "T")
        self.assertFalse(browser.closed, "закрытие браузера остаётся на вызывающем")
        self.assertEqual(log.call_args_list[0].args[0], "INFO")


class RoutingTests(unittest.TestCase):
    def test_metadata_worker_run_routes_through_helper(self):
        worker = rl_workers.RulateToRanobeMetadataWorker(PUBLIC_URL)
        received = []
        worker.metadata_ready.connect(received.append)
        browser = _FakeBrowser(_FakePage())

        def fake_fetch(playwright, *, rulate_edit_url, rulate_url, log, on_browser=None):
            on_browser(browser)
            return {"title_ru": "T"}

        with mock.patch.object(rl_workers, "sync_playwright", return_value=_FakePlaywright()), \
                mock.patch.object(rl_workers, "_fetch_rulate_edit_metadata", side_effect=fake_fetch) as fetch:
            rl_workers.RulateToRanobeMetadataWorker.run(worker)

        fetch.assert_called_once()
        kwargs = fetch.call_args.kwargs
        self.assertEqual(kwargs["rulate_edit_url"], worker.rulate_edit_url)
        self.assertEqual(kwargs["rulate_url"], worker.rulate_url)
        self.assertEqual(received, [{"title_ru": "T"}])
        self.assertTrue(browser.closed, "finally воркера закрывает браузер, переданный через on_browser")

    def test_create_worker_read_metadata_routes_through_helper(self):
        worker = rl_workers.RulateToRanobeCreateWorker(PUBLIC_URL, options={})
        browser = _FakeBrowser(_FakePage())

        def fake_fetch(playwright, *, rulate_edit_url, rulate_url, log, on_browser=None):
            on_browser(browser)
            return {"title_ru": "T", "author": "A"}

        with mock.patch.object(rl_workers, "_fetch_rulate_edit_metadata", side_effect=fake_fetch) as fetch:
            metadata = rl_workers.RulateToRanobeCreateWorker._read_rulate_metadata(worker, "pw")

        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs["rulate_edit_url"], worker.rulate_edit_url)
        self.assertEqual(metadata["title_ru"], "T")
        self.assertTrue(browser.closed)
        self.assertIsNone(worker._rulate_browser)


if __name__ == "__main__":
    unittest.main()
