# Content-Filter Fallback Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the main model returns a content block (Prohibited content / SAFETY), reroute that chunk/chapter to a user-chosen fallback provider+model (own temperature/thinking, pool of green keys) instead of failing; on success save normally and continue with the main model.

**Architecture:** A reactive fallback at the single API chokepoint `BaseTaskProcessor._execute_api_call` (covers translation + glossary) plus a twin hook in `consistency_engine._call_api_with_cached_handler`. Both reuse a new `content_filter_fallback.py` helper (green-key pool, exception classifiers, retry/budget loop) and the existing `provider_orchestrator` machinery (`_run_attempt`, `ProviderAttempt`, `_ProviderWorkerProxy`). The UI is a self-contained `ContentFilterFallbackPanel` embedded once in the shared `ModelSettingsWidget`, so it appears in the Translator, Glossary-build, and Consistency windows automatically.

**Tech Stack:** Python 3, PyQt6, asyncio, unittest (offscreen Qt), pytest as runner.

---

## Context the engineer needs

- **Chokepoint (translation + glossary):** `gemini_translator/core/worker_helpers/taskers/base_processor.py:63` `_execute_api_call`. Every translation/glossary chunk flows through it.
- **Consistency uses a separate path:** `gemini_translator/core/consistency_engine.py:2090` `_call_api_with_cached_handler` calls `handler.execute_api_call` directly; `_call_api` (2143) delegates to it; config comes from `consistency_checker._get_current_config()` → `model_settings_widget.get_settings()`.
- **Reusable orchestration:** `gemini_translator/core/worker_helpers/provider_orchestrator.py` — `ProviderAttempt` (dataclass), `_ProviderWorkerProxy` (overrides per-attempt attrs, proxies the rest of the worker via `__getattr__`), `_run_attempt(worker, attempt, prompt, log_prefix, call_kwargs) -> ProviderAttemptResult` (returns `.ok/.text/.exception/.error`, never raises), `_resolve_model(provider_id, model_name) -> (display_name, model_config)`.
- **Exceptions:** `gemini_translator/api/errors.py` — `ContentFilterError(Exception)` (no attrs); `PartialGenerationError(message, partial_text, reason)` has `.reason`; `NetworkError`, `TemporaryRateLimitError`, `RateLimitExceededError`. A content block = `ContentFilterError` OR `PartialGenerationError` with `reason ∈ {SAFETY, PROHIBITED_CONTENT}`.
- **Green key predicate:** key for a provider is "green" when `not settings_manager.is_key_limit_active(key_info, model_id)`. Key statuses come from `settings_manager.load_key_statuses()` → list of `{"key", "provider", "status_by_model"}`.
- **Settings → worker:** `worker.py:209-211` copies every session param into `self.<key>`, so any key added to `model_settings_widget.get_settings()` becomes `worker.<key>` automatically.
- **How handlers read thinking** (e.g. `api/handlers/gemini.py:56-82`): `worker.model_config.get("min_thinking_budget")`, `getattr(worker, 'thinking_enabled', False)`, `getattr(worker, 'thinking_level', None)`, `getattr(worker, 'thinking_budget', 0)`. So the fallback proxy must override `thinking_*` (today it only overrides `temperature`).
- **UI model/thinking facts:** providers enumerate via `api_config.api_providers().items()` → `p_data['display_name']`, `userData=p_id`; a provider's models via `api_config.api_providers()[pid]["models"]` (`{display_name: cfg}`, `cfg["id"]`); thinking support via `model_cfg.get("thinkingLevel")` (list → level combo) and `model_cfg.get("min_thinking_budget")` (`is not False` → budget). `api_config.all_models()` is a flat `{display_name: cfg}` map.
- **Test convention:** `unittest.TestCase`; `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`; `cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])`. Run with `python -m pytest`.

## File Structure

- **Create** `gemini_translator/core/worker_helpers/content_filter_fallback.py` — pool + classifiers + sync loop + async worker runner.
- **Modify** `gemini_translator/core/worker_helpers/provider_orchestrator.py` — `ProviderAttempt` thinking fields + proxy override.
- **Modify** `gemini_translator/core/worker_helpers/taskers/base_processor.py` — wrap `_execute_api_call`.
- **Modify** `gemini_translator/core/consistency_engine.py` — wrap content block in `_call_api_with_cached_handler`.
- **Create** `gemini_translator/ui/widgets/content_filter_fallback_panel.py` — `ContentFilterFallbackPanel`.
- **Modify** `gemini_translator/ui/widgets/model_settings_widget.py` — embed panel; merge config in get/set.
- **Create** tests: `tests/test_content_filter_fallback_pool.py`, `tests/test_provider_proxy_thinking.py`, `tests/test_content_filter_fallback_run.py`, `tests/test_base_processor_fallback_hook.py`, `tests/test_consistency_fallback.py`, `tests/test_content_filter_fallback_panel.py`.
- **Extend** existing test: `tests/test_model_settings_widget.py` (add one round-trip method to `ModelSettingsWidgetTests`, reusing its `_create_widget()` harness — that is the supported way to construct `ModelSettingsWidget`, which needs `app.event_bus` + `app.get_settings_manager`).

---

### Task 1: Core helper — pool, classifiers, sync loop

**Files:**
- Create: `gemini_translator/core/worker_helpers/content_filter_fallback.py`
- Test: `tests/test_content_filter_fallback_pool.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_content_filter_fallback_pool.py
import unittest

from gemini_translator.api.errors import (
    ContentFilterError,
    NetworkError,
    PartialGenerationError,
    RateLimitExceededError,
)
from gemini_translator.core.worker_helpers import content_filter_fallback as cff


class FakeSettings:
    def __init__(self, statuses, blocked_keys=()):
        self._statuses = statuses
        self._blocked = set(blocked_keys)

    def load_key_statuses(self):
        return list(self._statuses)

    def is_key_limit_active(self, key_info, model_id):
        return key_info["key"] in self._blocked


class GreenPoolTests(unittest.TestCase):
    def test_filters_by_provider_and_excludes_blocked(self):
        settings = FakeSettings(
            statuses=[
                {"key": "g1", "provider": "gemini"},
                {"key": "g2", "provider": "gemini"},
                {"key": "n1", "provider": "nvidia"},
                {"key": "g3", "provider": "gemini"},
            ],
            blocked_keys=["g2"],
        )
        pool = cff.green_keys_for_provider(settings, "gemini", "model-x")
        self.assertEqual(pool, ["g1", "g3"])

    def test_empty_when_no_settings_manager(self):
        self.assertEqual(cff.green_keys_for_provider(None, "gemini", "m"), [])

    def test_empty_when_no_keys_for_provider(self):
        settings = FakeSettings(statuses=[{"key": "n1", "provider": "nvidia"}])
        self.assertEqual(cff.green_keys_for_provider(settings, "gemini", "m"), [])


class ClassifierTests(unittest.TestCase):
    def test_content_block_detection(self):
        self.assertTrue(cff.is_content_block_exception(ContentFilterError("x")))
        self.assertTrue(
            cff.is_content_block_exception(PartialGenerationError("x", "", "SAFETY"))
        )
        self.assertTrue(
            cff.is_content_block_exception(
                PartialGenerationError("x", "", "prohibited_content")
            )
        )
        self.assertFalse(
            cff.is_content_block_exception(PartialGenerationError("x", "tail", "OTHER"))
        )
        self.assertFalse(cff.is_content_block_exception(NetworkError("x")))

    def test_transient_detection(self):
        self.assertTrue(cff.is_transient_exception(NetworkError("x")))
        self.assertTrue(cff.is_transient_exception(RateLimitExceededError("x")))
        self.assertFalse(cff.is_transient_exception(ContentFilterError("x")))

    def test_decision(self):
        self.assertEqual(cff.fallback_decision(ContentFilterError("x")), "block")
        self.assertEqual(cff.fallback_decision(NetworkError("x")), "transient")
        self.assertEqual(cff.fallback_decision(ValueError("x")), "fatal")


class SyncLoopTests(unittest.TestCase):
    def test_returns_first_success(self):
        calls = []

        def call_for_key(key):
            calls.append(key)
            return f"ok:{key}"

        out = cff.run_sync_fallback_loop(pool=["a", "b"], call_for_key=call_for_key)
        self.assertEqual(out, "ok:a")
        self.assertEqual(calls, ["a"])

    def test_content_block_raises_immediately(self):
        def call_for_key(key):
            raise ContentFilterError("blocked")

        with self.assertRaises(ContentFilterError):
            cff.run_sync_fallback_loop(pool=["a", "b"], call_for_key=call_for_key)

    def test_transient_rotates_then_succeeds(self):
        calls = []

        def call_for_key(key):
            calls.append(key)
            if len(calls) == 1:
                raise NetworkError("temp")
            return "recovered"

        out = cff.run_sync_fallback_loop(pool=["a", "b"], call_for_key=call_for_key)
        self.assertEqual(out, "recovered")
        self.assertEqual(calls, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_content_filter_fallback_pool.py -q`
Expected: FAIL — `ModuleNotFoundError: gemini_translator.core.worker_helpers.content_filter_fallback`.

- [ ] **Step 3: Write minimal implementation**

```python
# gemini_translator/core/worker_helpers/content_filter_fallback.py
"""Reactive fallback when the main model returns a content block.

On a content block (ContentFilterError, or PartialGenerationError with a
SAFETY/PROHIBITED_CONTENT reason) the blocked chunk/chapter is re-sent to a
user-chosen fallback provider+model, drawing from the pool of green (non-
exhausted) keys for that provider. A content block from the fallback is
terminal (task goes to error, as before). Transient errors rotate through
the green pool within the same budget the main model uses.
"""

from gemini_translator.api.errors import (
    ContentFilterError,
    NetworkError,
    PartialGenerationError,
    RateLimitExceededError,
    TemporaryRateLimitError,
)

# Content-block reasons reported by handlers via PartialGenerationError.reason.
SAFETY_REASONS = {"SAFETY", "PROHIBITED_CONTENT"}

# Transient errors during a fallback attempt get the same overall budget as the
# main model. Mirrors gemini_translator.core.worker_helpers.error_analyzer
# .ErrorAnalyzer.TOTAL_ATTEMPTS_LIMIT (kept as a local constant to avoid an
# import cycle through the worker stack).
TRANSIENT_RETRY_BUDGET = 4

_TRANSIENT_TYPES = (NetworkError, TemporaryRateLimitError, RateLimitExceededError)


class NoFallbackKeysError(Exception):
    """Raised when the chosen fallback provider has no green (active) keys."""


def is_content_block_exception(exc) -> bool:
    if isinstance(exc, ContentFilterError):
        return True
    if isinstance(exc, PartialGenerationError):
        return str(getattr(exc, "reason", "") or "").upper() in SAFETY_REASONS
    return False


def is_transient_exception(exc) -> bool:
    return isinstance(exc, _TRANSIENT_TYPES)


def fallback_decision(exc) -> str:
    """Return 'block' | 'transient' | 'fatal' for a fallback-attempt error."""
    if is_content_block_exception(exc):
        return "block"
    if is_transient_exception(exc):
        return "transient"
    return "fatal"


def green_keys_for_provider(settings_manager, provider_id, model_id) -> list:
    """All green (non-limit-active) keys for provider_id, in stored order."""
    if settings_manager is None or not provider_id:
        return []
    try:
        statuses = settings_manager.load_key_statuses()
    except Exception:
        return []
    pool = []
    for key_info in statuses or []:
        if str(key_info.get("provider")) != str(provider_id):
            continue
        key = str(key_info.get("key") or "").strip()
        if not key:
            continue
        try:
            blocked = settings_manager.is_key_limit_active(key_info, model_id)
        except Exception:
            blocked = False
        if not blocked:
            pool.append(key)
    return pool


def run_sync_fallback_loop(*, pool, call_for_key, log=None):
    """Run a synchronous fallback over a green-key pool.

    call_for_key(api_key) -> str, may raise. Content block -> reraise (terminal);
    transient -> rotate within TRANSIENT_RETRY_BUDGET; anything else -> reraise.
    """
    last_exc = None
    for index in range(TRANSIENT_RETRY_BUDGET):
        api_key = pool[index % len(pool)]
        try:
            return call_for_key(api_key)
        except Exception as exc:  # noqa: BLE001 - classified below
            decision = fallback_decision(exc)
            if decision == "block" or decision == "fatal":
                raise
            last_exc = exc
            if callable(log):
                log(f"🛡️🔁 Временная ошибка резерва ({type(exc).__name__}), ротация ключа…")
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Fallback produced no result.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_content_filter_fallback_pool.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/core/worker_helpers/content_filter_fallback.py tests/test_content_filter_fallback_pool.py
git commit -m "feat(fallback): green-key pool + content-block classifiers + sync loop

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Fallback thinking on the provider proxy

**Files:**
- Modify: `gemini_translator/core/worker_helpers/provider_orchestrator.py:48-99` (`ProviderAttempt`, `_ProviderWorkerProxy`)
- Test: `tests/test_provider_proxy_thinking.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provider_proxy_thinking.py
import unittest

from gemini_translator.core.worker_helpers.provider_orchestrator import (
    ProviderAttempt,
    _ProviderWorkerProxy,
)


class BaseWorker:
    thinking_enabled = False
    thinking_budget = 0
    thinking_level = "minimal"
    temperature = 1.0
    temperature_override_enabled = True
    worker_id = "w"


def _attempt(**over):
    base = dict(
        provider_id="gemini",
        model_name="m",
        model_config={"id": "m"},
        api_key="k",
        label="content-filter-fallback",
    )
    base.update(over)
    return ProviderAttempt(**base)


class ProxyThinkingTests(unittest.TestCase):
    def test_attempt_thinking_overrides_base(self):
        attempt = _attempt(
            thinking_enabled=True, thinking_budget=2048, thinking_level="HIGH"
        )
        proxy = _ProviderWorkerProxy(BaseWorker(), attempt, {"handler_class": "X"})
        self.assertTrue(proxy.thinking_enabled)
        self.assertEqual(proxy.thinking_budget, 2048)
        self.assertEqual(proxy.thinking_level, "HIGH")

    def test_none_attempt_thinking_falls_back_to_base(self):
        attempt = _attempt()
        proxy = _ProviderWorkerProxy(BaseWorker(), attempt, {"handler_class": "X"})
        self.assertFalse(proxy.thinking_enabled)
        self.assertEqual(proxy.thinking_budget, 0)
        self.assertEqual(proxy.thinking_level, "minimal")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_provider_proxy_thinking.py -q`
Expected: FAIL — `TypeError: ProviderAttempt.__init__() got an unexpected keyword argument 'thinking_enabled'`.

- [ ] **Step 3: Write minimal implementation**

In `provider_orchestrator.py`, add three fields to the `ProviderAttempt` dataclass (after `temperature_override_enabled`):

```python
    temperature: float | None = None
    temperature_override_enabled: bool | None = None
    thinking_enabled: bool | None = None
    thinking_budget: int | None = None
    thinking_level: str | None = None
    prompt_prefix: str = ""
```

In `_ProviderWorkerProxy.__init__`, after the existing `temperature_override_enabled` block, add:

```python
        self.thinking_enabled = (
            attempt.thinking_enabled
            if attempt.thinking_enabled is not None
            else getattr(base_worker, "thinking_enabled", False)
        )
        self.thinking_budget = (
            attempt.thinking_budget
            if attempt.thinking_budget is not None
            else getattr(base_worker, "thinking_budget", 0)
        )
        self.thinking_level = (
            attempt.thinking_level
            if attempt.thinking_level is not None
            else getattr(base_worker, "thinking_level", None)
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_provider_proxy_thinking.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the orchestrator's existing tests to check for regressions**

Run: `python -m pytest tests/ -q -k "orchestrat or provider or parallel or multi_pass"`
Expected: PASS (no regressions). If a test references `ProviderAttempt` positionally, the new optional fields keep backward compatibility.

- [ ] **Step 6: Commit**

```bash
git add gemini_translator/core/worker_helpers/provider_orchestrator.py tests/test_provider_proxy_thinking.py
git commit -m "feat(fallback): per-attempt thinking override on provider proxy

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Async worker fallback runner

**Files:**
- Modify: `gemini_translator/core/worker_helpers/content_filter_fallback.py` (append)
- Test: `tests/test_content_filter_fallback_run.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_content_filter_fallback_run.py
import asyncio
import unittest

from gemini_translator.api.errors import ContentFilterError, NetworkError
from gemini_translator.core.worker_helpers import content_filter_fallback as cff
from gemini_translator.core.worker_helpers.provider_orchestrator import (
    ProviderAttemptResult,
)


class FakeSettings:
    def load_key_statuses(self):
        return [
            {"key": "g1", "provider": "gemini"},
            {"key": "g2", "provider": "gemini"},
        ]

    def is_key_limit_active(self, key_info, model_id):
        return False


class FakeWorker:
    def __init__(self):
        self.settings_manager = FakeSettings()
        self.content_filter_fallback_enabled = True
        self.content_filter_fallback_provider = "gemini"
        self.content_filter_fallback_model = "gemini-2.0-flash"
        self.content_filter_fallback_temperature = 0.4
        self.content_filter_fallback_temperature_override = True
        self.content_filter_fallback_thinking_enabled = False
        self.content_filter_fallback_thinking_budget = None
        self.content_filter_fallback_thinking_level = None
        self.logs = []

    def _post_event(self, name, payload):
        self.logs.append((name, payload.get("message")))


def _run(coro):
    return asyncio.run(coro)


class RunFallbackTests(unittest.TestCase):
    def setUp(self):
        self._orig_resolve = cff._resolve_model
        self._orig_run = cff._run_attempt
        cff._resolve_model = lambda pid, name: (name, {"id": name, "provider": pid})

    def tearDown(self):
        cff._resolve_model = self._orig_resolve
        cff._run_attempt = self._orig_run

    def test_no_green_keys_raises(self):
        worker = FakeWorker()
        worker.settings_manager.load_key_statuses = lambda: []

        async def fake_run(*a, **k):
            raise AssertionError("should not be called")

        cff._run_attempt = fake_run
        with self.assertRaises(cff.NoFallbackKeysError):
            _run(self._call(worker))

    def test_success_returns_text(self):
        worker = FakeWorker()
        seen = {}

        async def fake_run(w, attempt, prompt, log_prefix, call_kwargs):
            seen["attempt"] = attempt
            return ProviderAttemptResult(attempt=attempt, text="TRANSLATED")

        cff._run_attempt = fake_run
        out = _run(self._call(worker))
        self.assertEqual(out, "TRANSLATED")
        self.assertEqual(seen["attempt"].provider_id, "gemini")
        self.assertEqual(seen["attempt"].api_key, "g1")
        self.assertAlmostEqual(seen["attempt"].temperature, 0.4)

    def test_fallback_block_reraises(self):
        worker = FakeWorker()

        async def fake_run(w, attempt, prompt, log_prefix, call_kwargs):
            return ProviderAttemptResult(
                attempt=attempt, error="blocked", exception=ContentFilterError("x")
            )

        cff._run_attempt = fake_run
        with self.assertRaises(ContentFilterError):
            _run(self._call(worker))

    def test_transient_rotates_then_succeeds(self):
        worker = FakeWorker()
        calls = []

        async def fake_run(w, attempt, prompt, log_prefix, call_kwargs):
            calls.append(attempt.api_key)
            if len(calls) == 1:
                return ProviderAttemptResult(
                    attempt=attempt, error="net", exception=NetworkError("temp")
                )
            return ProviderAttemptResult(attempt=attempt, text="OK")

        cff._run_attempt = fake_run
        out = _run(self._call(worker))
        self.assertEqual(out, "OK")
        self.assertEqual(calls, ["g1", "g2"])

    def _call(self, worker):
        return cff.run_content_filter_fallback(
            worker,
            "PROMPT",
            "[Test]",
            task_info=("tid", ("epub_chunk",)),
            operation_context={},
            call_kwargs={"use_stream": False},
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_content_filter_fallback_run.py -q`
Expected: FAIL — `AttributeError: module 'content_filter_fallback' has no attribute 'run_content_filter_fallback'` (and `_resolve_model`/`_run_attempt` not yet imported into the module).

- [ ] **Step 3: Write minimal implementation**

Append to `content_filter_fallback.py`:

```python
from gemini_translator.core.worker_helpers.provider_orchestrator import (  # noqa: E402
    ProviderAttempt,
    _resolve_model,
    _run_attempt,
)


def fallback_enabled(worker) -> bool:
    return bool(getattr(worker, "content_filter_fallback_enabled", False))


def _post(worker, message: str) -> None:
    fn = getattr(worker, "_post_event", None)
    if callable(fn):
        fn("log_message", {"message": message})


def _fallback_temperature(worker):
    if not bool(getattr(worker, "content_filter_fallback_temperature_override", True)):
        return None
    try:
        return float(getattr(worker, "content_filter_fallback_temperature", None))
    except (TypeError, ValueError):
        return None


async def run_content_filter_fallback(
    worker, prompt, log_prefix, *, task_info, operation_context, call_kwargs
):
    """Re-run a content-blocked prompt against the configured fallback provider.

    Returns the fallback translation text. Raises the content-block exception if
    the fallback is also blocked, NoFallbackKeysError if the provider has no
    green keys, or the last transient exception after the budget is exhausted.
    """
    provider_id = str(getattr(worker, "content_filter_fallback_provider", "") or "").strip()
    model_name = str(getattr(worker, "content_filter_fallback_model", "") or "").strip()
    if not provider_id:
        raise NoFallbackKeysError("Резервный провайдер не выбран.")

    resolved_name, model_config = _resolve_model(provider_id, model_name)
    model_id = model_config.get("id") or resolved_name
    pool = green_keys_for_provider(getattr(worker, "settings_manager", None), provider_id, model_id)
    if not pool:
        raise NoFallbackKeysError(f"Нет зелёных ключей для провайдера '{provider_id}'.")

    attempt_kwargs = dict(
        provider_id=provider_id,
        model_name=resolved_name,
        model_config=model_config,
        label="content-filter-fallback",
        temperature=_fallback_temperature(worker),
        temperature_override_enabled=bool(
            getattr(worker, "content_filter_fallback_temperature_override", True)
        ),
        thinking_enabled=bool(getattr(worker, "content_filter_fallback_thinking_enabled", False)),
        thinking_budget=getattr(worker, "content_filter_fallback_thinking_budget", None),
        thinking_level=getattr(worker, "content_filter_fallback_thinking_level", None),
    )

    _post(
        worker,
        f"🛡️➡️ Контент заблокирован. Резерв: {provider_id}/{model_id} "
        f"({len(pool)} зелёных ключей).",
    )

    last_exc = None
    for index in range(TRANSIENT_RETRY_BUDGET):
        api_key = pool[index % len(pool)]
        attempt = ProviderAttempt(api_key=api_key, **attempt_kwargs)
        result = await _run_attempt(worker, attempt, prompt, log_prefix, call_kwargs)
        if result.ok:
            _post(worker, f"🛡️✅ Резерв перевёл заблокированный фрагмент ({provider_id}/{model_id}).")
            return result.text
        exc = result.exception or RuntimeError(result.error or "fallback failed")
        decision = fallback_decision(exc)
        if decision == "block":
            _post(worker, "🛡️❌ Резерв тоже вернул блокировку — задача уходит в ошибку.")
            raise exc
        if decision == "fatal":
            raise exc
        last_exc = exc
        _post(worker, f"🛡️🔁 Временная ошибка резерва ({type(exc).__name__}), ротация ключа…")
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Резерв не дал результата.")
```

> Note: the `import` is placed at the end of the module (with `# noqa: E402`) on purpose — `provider_orchestrator` is a heavier import and keeping it after the pure helpers avoids any import-time surprises while still exposing `_resolve_model`/`_run_attempt` as module globals that tests can monkeypatch.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_content_filter_fallback_run.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/core/worker_helpers/content_filter_fallback.py tests/test_content_filter_fallback_run.py
git commit -m "feat(fallback): async worker fallback runner with key rotation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Hook the translation/glossary chokepoint

**Files:**
- Modify: `gemini_translator/core/worker_helpers/taskers/base_processor.py:1-79`
- Test: `tests/test_base_processor_fallback_hook.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_base_processor_fallback_hook.py
import asyncio
import unittest
from contextlib import contextmanager

from gemini_translator.api.errors import ContentFilterError
from gemini_translator.core.worker_helpers.taskers import base_processor
from gemini_translator.core.worker_helpers.taskers.base_processor import BaseTaskProcessor


class FakeHandler:
    def __init__(self, exc):
        self._exc = exc

    async def execute_api_call(self, prompt, log_prefix, **kwargs):
        raise self._exc


class FakeWorker:
    def __init__(self, *, enabled, exc):
        self.api_handler_instance = FakeHandler(exc)
        self.content_filter_fallback_enabled = enabled
        self.parallel_providers_enabled = False
        self.multi_pass_enabled = False
        self.multi_pass_chapter_translation = False
        self.project_manager = None
        self.output_folder = None
        self.file_path = None

    @contextmanager
    def debug_operation_context(self, ctx):
        yield


def _run(coro):
    return asyncio.run(coro)


class FallbackHookTests(unittest.TestCase):
    def tearDown(self):
        base_processor.run_content_filter_fallback = self._orig

    def setUp(self):
        self._orig = base_processor.run_content_filter_fallback

    def test_content_block_routes_to_fallback_when_enabled(self):
        async def fake_fallback(worker, prompt, log_prefix, **kwargs):
            return "FROM_FALLBACK"

        base_processor.run_content_filter_fallback = fake_fallback
        worker = FakeWorker(enabled=True, exc=ContentFilterError("blocked"))
        proc = BaseTaskProcessor(worker)
        out = _run(
            proc._execute_api_call("P", "[L]", task_info=("t", ("epub_chunk",)), use_stream=False)
        )
        self.assertEqual(out, "FROM_FALLBACK")

    def test_content_block_reraises_when_disabled(self):
        worker = FakeWorker(enabled=False, exc=ContentFilterError("blocked"))
        proc = BaseTaskProcessor(worker)
        with self.assertRaises(ContentFilterError):
            _run(
                proc._execute_api_call("P", "[L]", task_info=("t", ("epub_chunk",)), use_stream=False)
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_base_processor_fallback_hook.py -q`
Expected: FAIL — `AttributeError: module base_processor has no attribute 'run_content_filter_fallback'`.

- [ ] **Step 3: Write minimal implementation**

Replace the top imports of `base_processor.py` (lines 1-5):

```python
from gemini_translator.api.errors import (
    ContentFilterError,
    PartialGenerationError,
    ValidationFailedError,
)
from gemini_translator.core.worker_helpers.content_filter_fallback import (
    fallback_enabled,
    is_content_block_exception,
    run_content_filter_fallback,
)
from gemini_translator.core.worker_helpers.provider_orchestrator import (
    execute_orchestrated_api_call,
    should_orchestrate_api_call,
)
```

Replace the body of `_execute_api_call` (the current lines 63-79) with:

```python
    async def _execute_api_call(self, prompt, log_prefix, *, task_info, operation_context: dict | None = None, **kwargs):
        context_payload = operation_context or self._build_operation_context(task_info)
        try:
            if should_orchestrate_api_call(self.worker, context_payload):
                return await execute_orchestrated_api_call(
                    self.worker,
                    prompt,
                    log_prefix,
                    task_info=task_info,
                    operation_context=context_payload,
                    call_kwargs=kwargs,
                )
            with self.worker.debug_operation_context(context_payload):
                return await self.worker.api_handler_instance.execute_api_call(
                    prompt,
                    log_prefix,
                    **kwargs,
                )
        except (ContentFilterError, PartialGenerationError) as exc:
            if fallback_enabled(self.worker) and is_content_block_exception(exc):
                return await run_content_filter_fallback(
                    self.worker,
                    prompt,
                    log_prefix,
                    task_info=task_info,
                    operation_context=context_payload,
                    call_kwargs=kwargs,
                )
            raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_base_processor_fallback_hook.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/core/worker_helpers/taskers/base_processor.py tests/test_base_processor_fallback_hook.py
git commit -m "feat(fallback): reroute content blocks at the processor chokepoint

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Hook the Consistency engine

**Files:**
- Modify: `gemini_translator/core/consistency_engine.py` (imports near top; `_call_api_with_cached_handler` ~2090-2141; add `_run_consistency_content_filter_fallback`)
- Test: `tests/test_consistency_fallback.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_consistency_fallback.py
import unittest

from gemini_translator.api.errors import ContentFilterError, NetworkError
from gemini_translator.core import consistency_engine as ce
from gemini_translator.core.consistency_engine import ConsistencyEngine


class FakeSettings:
    def load_key_statuses(self):
        return [
            {"key": "g1", "provider": "nvidia"},
            {"key": "g2", "provider": "nvidia"},
        ]

    def is_key_limit_active(self, key_info, model_id):
        return False


class FakeEngine:
    """Minimal stand-in exposing only what the fallback method touches."""

    def __init__(self):
        self.settings_manager = FakeSettings()
        self.logs = []
        self.calls = []
        self._script = []

    def _log(self, msg):
        self.logs.append(msg)

    def _call_api_with_cached_handler(self, prompt, config, api_key):
        self.calls.append((api_key, config.get("_is_fallback_attempt")))
        action = self._script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


class ConsistencyFallbackTests(unittest.TestCase):
    def setUp(self):
        self._orig = ce._load_providers_config
        ce._load_providers_config = lambda: {
            "nvidia": {"handler_class": "X", "models": {"big": {"id": "big"}}}
        }

    def tearDown(self):
        ce._load_providers_config = self._orig

    def _config(self):
        return {
            "content_filter_fallback_enabled": True,
            "content_filter_fallback_provider": "nvidia",
            "content_filter_fallback_model": "big",
            "content_filter_fallback_temperature": 0.3,
        }

    def test_success_returns_text_with_guard_flag(self):
        eng = FakeEngine()
        eng._script = ["FALLBACK_OK"]
        out = ConsistencyEngine._run_consistency_content_filter_fallback(
            eng, "PROMPT", self._config()
        )
        self.assertEqual(out, "FALLBACK_OK")
        self.assertEqual(eng.calls, [("g1", True)])

    def test_fallback_block_reraises(self):
        eng = FakeEngine()
        eng._script = [ContentFilterError("blocked")]
        with self.assertRaises(ContentFilterError):
            ConsistencyEngine._run_consistency_content_filter_fallback(
                eng, "PROMPT", self._config()
            )

    def test_transient_rotates(self):
        eng = FakeEngine()
        eng._script = [NetworkError("temp"), "RECOVERED"]
        out = ConsistencyEngine._run_consistency_content_filter_fallback(
            eng, "PROMPT", self._config()
        )
        self.assertEqual(out, "RECOVERED")
        self.assertEqual([c[0] for c in eng.calls], ["g1", "g2"])

    def test_no_keys_raises(self):
        eng = FakeEngine()
        eng.settings_manager.load_key_statuses = lambda: []
        with self.assertRaises(ce.NoFallbackKeysError):
            ConsistencyEngine._run_consistency_content_filter_fallback(
                eng, "PROMPT", self._config()
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_consistency_fallback.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'NoFallbackKeysError'` / `_run_consistency_content_filter_fallback`.

- [ ] **Step 3: Write minimal implementation**

`consistency_engine.py:21` already has `from ..api.errors import NetworkError, RateLimitExceededError, TemporaryRateLimitError`. Extend it to:

```python
from ..api.errors import (
    ContentFilterError,
    NetworkError,
    PartialGenerationError,
    RateLimitExceededError,
    TemporaryRateLimitError,
)
```

And add (near the other `from gemini_translator...`/`from ..` imports):

```python
from .worker_helpers.content_filter_fallback import (
    NoFallbackKeysError,
    green_keys_for_provider,
    is_content_block_exception,
    run_sync_fallback_loop,
)
```

> `_load_providers_config` and `get_api_handler_class` are already imported in this module (used near lines 2159/2166) — do not re-import. The `from ... import NoFallbackKeysError` above binds it as a module global, so the test's `ce.NoFallbackKeysError` resolves.

In `_call_api_with_cached_handler`, replace the final `try/except` (currently around lines 2134-2141):

```python
        try:
            response = handler.execute_api_call(prompt, "[Consistency]", use_stream=False)
            if inspect.isawaitable(response):
                response = self._run_handler_awaitable(response)
            return response
        except (ContentFilterError, PartialGenerationError) as exc:
            self._invalidate_cached_handler(cache_key, handler)
            if (
                not config.get("_is_fallback_attempt")
                and config.get("content_filter_fallback_enabled")
                and is_content_block_exception(exc)
            ):
                return self._run_consistency_content_filter_fallback(prompt, config)
            raise
        except Exception:
            self._invalidate_cached_handler(cache_key, handler)
            raise
```

Add the new method to the `ConsistencyEngine` class (next to `_call_api_with_cached_handler`):

```python
    def _run_consistency_content_filter_fallback(self, prompt: str, config: Dict[str, Any]) -> str:
        """Re-run a content-blocked consistency prompt against the fallback provider."""
        provider_id = str(config.get("content_filter_fallback_provider") or "").strip()
        model_name = str(config.get("content_filter_fallback_model") or "").strip()
        if not provider_id:
            raise NoFallbackKeysError("Резервный провайдер не выбран.")

        provider_info = (_load_providers_config().get(provider_id) or {})
        model_config = (provider_info.get("models", {}) or {}).get(model_name, {})
        model_id = model_config.get("id", model_name)

        pool = green_keys_for_provider(self.settings_manager, provider_id, model_id)
        if not pool:
            raise NoFallbackKeysError(f"Нет зелёных ключей для провайдера '{provider_id}'.")

        fb_config = {
            "provider": provider_id,
            "model": model_name,
            "temperature": config.get("content_filter_fallback_temperature", 0.3),
            "temperature_override_enabled": bool(
                config.get("content_filter_fallback_temperature_override", True)
            ),
            "thinking_enabled": bool(config.get("content_filter_fallback_thinking_enabled", False)),
            "thinking_budget": config.get("content_filter_fallback_thinking_budget", 0),
            "thinking_level": config.get("content_filter_fallback_thinking_level", "minimal"),
            "proxy_settings": config.get("proxy_settings"),
            "_is_fallback_attempt": True,
        }

        self._log(
            f"🛡️➡️ [Consistency] Контент заблокирован. Резерв: "
            f"{provider_id}/{model_id} ({len(pool)} ключей)."
        )
        return run_sync_fallback_loop(
            pool=pool,
            call_for_key=lambda key: self._call_api_with_cached_handler(prompt, fb_config, key),
            log=self._log,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_consistency_fallback.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the existing consistency tests for regressions**

Run: `python -m pytest tests/ -q -k "consistency"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gemini_translator/core/consistency_engine.py tests/test_consistency_fallback.py
git commit -m "feat(fallback): content-block fallback in the consistency engine

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Fallback UI panel

**Files:**
- Create: `gemini_translator/ui/widgets/content_filter_fallback_panel.py`
- Test: `tests/test_content_filter_fallback_panel.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_content_filter_fallback_panel.py
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.api import config as api_config
from gemini_translator.ui.widgets.content_filter_fallback_panel import (
    ContentFilterFallbackPanel,
)

PROVIDERS = {
    "gemini": {
        "display_name": "Gemini",
        "models": {
            "Flash": {"id": "gemini-flash", "thinkingLevel": ["LOW", "HIGH"]},
            "Pro": {"id": "gemini-pro", "min_thinking_budget": 128},
        },
    },
    "nvidia": {
        "display_name": "NVIDIA",
        "models": {"Big": {"id": "big-1", "min_thinking_budget": False}},
    },
}

ALL_MODELS = {
    "Flash": {"id": "gemini-flash", "provider": "gemini", "thinkingLevel": ["LOW", "HIGH"]},
    "Pro": {"id": "gemini-pro", "provider": "gemini", "min_thinking_budget": 128},
    "Big": {"id": "big-1", "provider": "nvidia", "min_thinking_budget": False},
}


class FakeSettings:
    def load_key_statuses(self):
        return [{"key": "g1", "provider": "gemini"}]

    def is_key_limit_active(self, key_info, model_id):
        return False


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _panel(self):
        patcher_p = patch.object(api_config, "api_providers", return_value=PROVIDERS)
        patcher_m = patch.object(api_config, "all_models", return_value=ALL_MODELS)
        patcher_e = patch.object(api_config, "ensure_dynamic_provider_models", return_value=None)
        patcher_p.start(); patcher_m.start(); patcher_e.start()
        self.addCleanup(patcher_p.stop)
        self.addCleanup(patcher_m.stop)
        self.addCleanup(patcher_e.stop)
        panel = ContentFilterFallbackPanel(settings_manager=FakeSettings())
        self.addCleanup(panel.close)
        return panel

    def test_disabled_by_default_and_config_shape(self):
        panel = self._panel()
        cfg = panel.get_config()
        self.assertFalse(cfg["content_filter_fallback_enabled"])
        for key in (
            "content_filter_fallback_provider",
            "content_filter_fallback_model",
            "content_filter_fallback_temperature",
            "content_filter_fallback_temperature_override",
            "content_filter_fallback_thinking_enabled",
            "content_filter_fallback_thinking_budget",
            "content_filter_fallback_thinking_level",
        ):
            self.assertIn(key, cfg)

    def test_set_then_get_round_trips_level_model(self):
        panel = self._panel()
        panel.set_config({
            "content_filter_fallback_enabled": True,
            "content_filter_fallback_provider": "gemini",
            "content_filter_fallback_model": "Flash",
            "content_filter_fallback_temperature": 0.5,
            "content_filter_fallback_temperature_override": True,
            "content_filter_fallback_thinking_enabled": True,
            "content_filter_fallback_thinking_level": "HIGH",
        })
        cfg = panel.get_config()
        self.assertTrue(cfg["content_filter_fallback_enabled"])
        self.assertEqual(cfg["content_filter_fallback_provider"], "gemini")
        self.assertEqual(cfg["content_filter_fallback_model"], "Flash")
        self.assertAlmostEqual(cfg["content_filter_fallback_temperature"], 0.5)
        self.assertTrue(cfg["content_filter_fallback_thinking_enabled"])
        self.assertEqual(cfg["content_filter_fallback_thinking_level"], "HIGH")

    def test_non_thinking_model_disables_thinking(self):
        panel = self._panel()
        panel.set_config({
            "content_filter_fallback_enabled": True,
            "content_filter_fallback_provider": "nvidia",
            "content_filter_fallback_model": "Big",
            "content_filter_fallback_thinking_enabled": True,
        })
        cfg = panel.get_config()
        self.assertFalse(cfg["content_filter_fallback_thinking_enabled"])

    def test_green_key_indicator_counts(self):
        panel = self._panel()
        panel.set_config({
            "content_filter_fallback_enabled": True,
            "content_filter_fallback_provider": "gemini",
            "content_filter_fallback_model": "Flash",
        })
        self.assertIn("1", panel.keys_label.text())

    def test_no_keys_indicator(self):
        panel = self._panel()
        panel.settings_manager = type("S", (), {"load_key_statuses": lambda self: [], "is_key_limit_active": lambda self, k, m: False})()
        panel.set_config({
            "content_filter_fallback_enabled": True,
            "content_filter_fallback_provider": "nvidia",
            "content_filter_fallback_model": "Big",
        })
        self.assertIn("Нет зелёных", panel.keys_label.text())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_content_filter_fallback_panel.py -q`
Expected: FAIL — `ModuleNotFoundError: ...content_filter_fallback_panel`.

- [ ] **Step 3: Write minimal implementation**

```python
# gemini_translator/ui/widgets/content_filter_fallback_panel.py
"""Self-contained UI for the content-block fallback provider/model.

Embedded once inside ModelSettingsWidget, so it appears in every window that
reuses it (Translator, Glossary build, Consistency). Collects its config under
`content_filter_fallback_*` keys; execution lives in the core helper.
"""

from PyQt6 import QtWidgets
from PyQt6.QtCore import pyqtSignal

from gemini_translator.api import config as api_config
from gemini_translator.core.worker_helpers.content_filter_fallback import (
    green_keys_for_provider,
)
from gemini_translator.ui import theme_manager  # module; call theme_manager.color(...)
from gemini_translator.ui.widgets.common_widgets import (
    NoScrollComboBox,
    NoScrollDoubleSpinBox,
    NoScrollSpinBox,
)


class ContentFilterFallbackPanel(QtWidgets.QGroupBox):
    config_changed = pyqtSignal()

    def __init__(self, settings_manager=None, parent=None):
        super().__init__("Резерв при блокировке контента", parent)
        self.settings_manager = settings_manager
        self._build_ui()
        self._populate_providers()
        self._wire_signals()
        self._on_provider_changed()
        self._update_enabled_state()

    # ----- UI -----
    def _build_ui(self):
        layout = QtWidgets.QGridLayout(self)

        self.enable_checkbox = QtWidgets.QCheckBox(
            "Включить резерв при блокировке (Prohibited content)"
        )
        self.enable_checkbox.setToolTip(
            "Если основная модель вернула блокировку контента, перевести этот "
            "чанк/главу резервным провайдером и моделью, затем продолжить основной."
        )
        layout.addWidget(self.enable_checkbox, 0, 0, 1, 3)

        layout.addWidget(QtWidgets.QLabel("Провайдер:"), 1, 0)
        self.provider_combo = NoScrollComboBox()
        layout.addWidget(self.provider_combo, 1, 1, 1, 2)

        layout.addWidget(QtWidgets.QLabel("Модель:"), 2, 0)
        self.model_combo = NoScrollComboBox()
        layout.addWidget(self.model_combo, 2, 1, 1, 2)

        self.keys_label = QtWidgets.QLabel("")
        self.keys_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(self.keys_label, 3, 1, 1, 2)

        layout.addWidget(QtWidgets.QLabel("Температура:"), 4, 0)
        self.temp_override_checkbox = QtWidgets.QCheckBox("Override")
        self.temp_spin = NoScrollDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(1.0)
        self.temp_spin.setEnabled(False)
        temp_row = QtWidgets.QHBoxLayout()
        temp_row.addWidget(self.temp_override_checkbox)
        temp_row.addWidget(self.temp_spin)
        temp_row.addStretch()
        layout.addLayout(temp_row, 4, 1, 1, 2)

        layout.addWidget(QtWidgets.QLabel("Thinking:"), 5, 0)
        self.thinking_checkbox = QtWidgets.QCheckBox()
        self.thinking_budget_spin = NoScrollSpinBox()
        self.thinking_budget_spin.setRange(-1, 32768)
        self.thinking_budget_spin.setValue(-1)
        self.thinking_level_combo = NoScrollComboBox()
        self.thinking_level_combo.setVisible(False)
        thinking_row = QtWidgets.QHBoxLayout()
        thinking_row.addWidget(self.thinking_checkbox)
        thinking_row.addWidget(self.thinking_budget_spin)
        thinking_row.addWidget(self.thinking_level_combo)
        thinking_row.addStretch()
        layout.addLayout(thinking_row, 5, 1, 1, 2)

    def _emit_changed(self, *_):
        self.config_changed.emit()

    def _sync_temp_enabled(self, *_):
        self.temp_spin.setEnabled(
            self.enable_checkbox.isChecked() and self.temp_override_checkbox.isChecked()
        )

    def _wire_signals(self):
        # Population slots stay pure (no emit). Interactive signals drive
        # config_changed via _emit_changed so set_config can repopulate without
        # spamming the parent during load.
        self.enable_checkbox.stateChanged.connect(self._update_enabled_state)
        self.enable_checkbox.stateChanged.connect(self._emit_changed)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_combo.currentIndexChanged.connect(self._emit_changed)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.model_combo.currentIndexChanged.connect(self._emit_changed)
        self.temp_override_checkbox.stateChanged.connect(self._sync_temp_enabled)
        self.temp_override_checkbox.stateChanged.connect(self._emit_changed)
        self.temp_spin.valueChanged.connect(self._emit_changed)
        self.thinking_checkbox.stateChanged.connect(self._emit_changed)
        self.thinking_budget_spin.valueChanged.connect(self._emit_changed)
        self.thinking_level_combo.currentTextChanged.connect(self._emit_changed)

    # ----- population -----
    def _populate_providers(self):
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        for p_id, p_data in api_config.api_providers().items():
            self.provider_combo.addItem(p_data.get("display_name", p_id), userData=p_id)
        self.provider_combo.blockSignals(False)

    def _on_provider_changed(self, *_):
        provider_id = self.provider_combo.currentData()
        prev_blocked = self.model_combo.signalsBlocked()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        if provider_id:
            try:
                api_config.ensure_dynamic_provider_models(provider_id)
            except Exception:
                pass
            models = api_config.api_providers().get(provider_id, {}).get("models", {})
            for display_name, cfg in models.items():
                self.model_combo.addItem(display_name, userData=cfg.get("id"))
        self.model_combo.blockSignals(prev_blocked)
        self._on_model_changed()

    def _on_model_changed(self, *_):
        model_name = self.model_combo.currentText()
        model_cfg = api_config.all_models().get(model_name, {})
        thinking_levels = model_cfg.get("thinkingLevel")
        min_budget = model_cfg.get("min_thinking_budget")
        supports = (thinking_levels is not None) or (min_budget is not False)

        self.thinking_checkbox.setEnabled(supports and self.enable_checkbox.isChecked())
        if not supports:
            self.thinking_checkbox.setChecked(False)
            self.thinking_level_combo.setVisible(False)
            self.thinking_budget_spin.setVisible(True)
        elif thinking_levels and isinstance(thinking_levels, list):
            self.thinking_budget_spin.setVisible(False)
            self.thinking_level_combo.setVisible(True)
            self.thinking_level_combo.blockSignals(True)
            self.thinking_level_combo.clear()
            self.thinking_level_combo.addItems([str(l).upper() for l in thinking_levels])
            self.thinking_level_combo.blockSignals(False)
        else:
            self.thinking_level_combo.setVisible(False)
            self.thinking_budget_spin.setVisible(True)

        self._update_keys_indicator()

    def _update_keys_indicator(self):
        provider_id = self.provider_combo.currentData()
        model_id = self.model_combo.currentData()
        count = len(green_keys_for_provider(self.settings_manager, provider_id, model_id))
        if count:
            self.keys_label.setText(f"Зелёных ключей: {count}")
            self.keys_label.setStyleSheet(
                f"color: {theme_manager.color('success')}; font-size: 10px;"
            )
        else:
            self.keys_label.setText("Нет зелёных ключей для этого провайдера")
            self.keys_label.setStyleSheet(
                f"color: {theme_manager.color('danger')}; font-size: 10px;"
            )

    def _update_enabled_state(self, *_):
        on = self.enable_checkbox.isChecked()
        for widget in (
            self.provider_combo,
            self.model_combo,
            self.temp_override_checkbox,
            self.thinking_checkbox,
            self.keys_label,
        ):
            widget.setEnabled(on)
        self.temp_spin.setEnabled(on and self.temp_override_checkbox.isChecked())
        self._on_model_changed()

    # ----- config -----
    def get_config(self) -> dict:
        thinking_enabled = self.thinking_checkbox.isEnabled() and self.thinking_checkbox.isChecked()
        thinking_level = None
        thinking_budget = None
        if thinking_enabled:
            # isHidden() reflects the explicit setVisible() state regardless of
            # whether the widget tree is shown (unlike isVisible()), so it is
            # reliable in offscreen tests and before the window is displayed.
            if not self.thinking_level_combo.isHidden():
                thinking_level = self.thinking_level_combo.currentText()
            else:
                thinking_budget = self.thinking_budget_spin.value()
        return {
            "content_filter_fallback_enabled": self.enable_checkbox.isChecked(),
            "content_filter_fallback_provider": self.provider_combo.currentData() or "",
            "content_filter_fallback_model": self.model_combo.currentText(),
            "content_filter_fallback_temperature": self.temp_spin.value(),
            "content_filter_fallback_temperature_override": self.temp_override_checkbox.isChecked(),
            "content_filter_fallback_thinking_enabled": bool(thinking_enabled),
            "content_filter_fallback_thinking_budget": thinking_budget,
            "content_filter_fallback_thinking_level": thinking_level,
        }

    def set_config(self, settings: dict):
        # Block child signals while we drive population manually, saving prior
        # state so nesting inside ModelSettingsWidget.set_settings (which already
        # blocks children) is preserved on restore.
        children = self.findChildren(QtWidgets.QWidget)
        prior = [(w, w.signalsBlocked()) for w in children]
        for w, _state in prior:
            w.blockSignals(True)
        try:
            self.enable_checkbox.setChecked(
                bool(settings.get("content_filter_fallback_enabled", False))
            )
            provider_id = settings.get("content_filter_fallback_provider")
            if provider_id:
                idx = self.provider_combo.findData(provider_id)
                if idx != -1:
                    self.provider_combo.setCurrentIndex(idx)
            self._on_provider_changed()

            model_name = settings.get("content_filter_fallback_model")
            if model_name:
                idx = self.model_combo.findText(model_name)
                if idx != -1:
                    self.model_combo.setCurrentIndex(idx)
            self._on_model_changed()

            self.temp_override_checkbox.setChecked(
                bool(settings.get("content_filter_fallback_temperature_override", False))
            )
            self.temp_spin.setValue(
                float(settings.get("content_filter_fallback_temperature", 1.0))
            )
            self.thinking_checkbox.setChecked(
                bool(settings.get("content_filter_fallback_thinking_enabled", False))
            )
            budget = settings.get("content_filter_fallback_thinking_budget")
            if budget is not None:
                self.thinking_budget_spin.setValue(int(budget))
            level = settings.get("content_filter_fallback_thinking_level")
            if level:
                idx = self.thinking_level_combo.findText(str(level))
                if idx != -1:
                    self.thinking_level_combo.setCurrentIndex(idx)
        finally:
            for w, state in prior:
                w.blockSignals(state)
        self._update_enabled_state()
```

> If `common_widgets` does not export `NoScrollDoubleSpinBox`/`NoScrollSpinBox`/`NoScrollComboBox` under these names, check the imports at the top of `model_settings_widget.py:15` (it imports exactly these) and copy that import line.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_content_filter_fallback_panel.py -q`
Expected: PASS (6 tests). Verified-good color tokens: `'success'`, `'danger'`, `'warning'`, `'text_muted'`.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/ui/widgets/content_filter_fallback_panel.py tests/test_content_filter_fallback_panel.py
git commit -m "feat(fallback): ContentFilterFallbackPanel UI widget

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Embed the panel in ModelSettingsWidget

**Files:**
- Modify: `gemini_translator/ui/widgets/model_settings_widget.py` (import; `_init_ui` right column ~773; `get_settings` ~1138-1169; `set_settings` ~1240; signal wiring ~447)
- Test: `tests/test_model_settings_widget.py` (add one method to the existing `ModelSettingsWidgetTests`)

> Reuse the existing `_create_widget()` harness in that file — it sets `cls.app.event_bus` and `app.get_settings_manager`, which `ModelSettingsWidget.__init__` requires. The panel degrades gracefully when the stub lacks `load_key_statuses` (the green-pool helper swallows the AttributeError and reports 0 keys), so no stub changes are needed.

- [ ] **Step 1: Write the failing test**

Add this method to the `ModelSettingsWidgetTests` class in `tests/test_model_settings_widget.py` (it uses the real `api_config` providers already imported at the top of that file):

```python
    def test_content_filter_fallback_round_trips_and_defaults_off(self):
        widget = self._create_widget()

        self.assertTrue(hasattr(widget, "fallback_panel"))
        self.assertIn("content_filter_fallback_enabled", widget.get_settings())
        self.assertFalse(widget.get_settings()["content_filter_fallback_enabled"])

        provider_id, model_name = "", ""
        for pid, pdata in api_config.api_providers().items():
            models = pdata.get("models", {})
            if models:
                provider_id, model_name = pid, next(iter(models))
                break
        self.assertTrue(provider_id, "no provider with models available in api_config")

        widget.set_settings({
            "content_filter_fallback_enabled": True,
            "content_filter_fallback_provider": provider_id,
            "content_filter_fallback_model": model_name,
            "content_filter_fallback_temperature": 0.6,
            "content_filter_fallback_temperature_override": True,
        })

        out = widget.get_settings()
        self.assertTrue(out["content_filter_fallback_enabled"])
        self.assertEqual(out["content_filter_fallback_provider"], provider_id)
        self.assertEqual(out["content_filter_fallback_model"], model_name)
        self.assertAlmostEqual(out["content_filter_fallback_temperature"], 0.6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_model_settings_widget.py::ModelSettingsWidgetTests::test_content_filter_fallback_round_trips_and_defaults_off -q`
Expected: FAIL — `AttributeError: 'ModelSettingsWidget' object has no attribute 'fallback_panel'`.

- [ ] **Step 3: Write minimal implementation**

Add the import near the other widget imports at the top of `model_settings_widget.py` (alongside line 15):

```python
from .content_filter_fallback_panel import ContentFilterFallbackPanel
```

In `_init_ui`, after the `misc_group` is added to `right_layout` (after line ~773, following `right_layout.addWidget(misc_group)` — if that exact line isn't present, add the panel right after the misc group block), insert:

```python
        self.fallback_panel = ContentFilterFallbackPanel(settings_manager=self.settings_manager)
        right_layout.addWidget(self.fallback_panel)
```

In the signals block of `__init__` (near line 447 where other checkboxes connect to `_emit_settings_changed`), add:

```python
        self.fallback_panel.config_changed.connect(self._emit_settings_changed)
```

In `get_settings`, change the trailing `return { ... }` so the dict is built then extended. Replace `return {` with `settings = {` and, immediately after the closing `}` of that dict literal (currently line ~1169), add:

```python
        settings.update(self.fallback_panel.get_config())
        return settings
```

In `set_settings`, inside the `try:` block (after the existing restores, e.g. after line ~1240 `self.skip_filter_retry_checkbox.setChecked(...)`), add:

```python
            self.fallback_panel.set_config(settings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_model_settings_widget.py::ModelSettingsWidgetTests::test_content_filter_fallback_round_trips_and_defaults_off -q`
Expected: PASS (1 test).

- [ ] **Step 5: Run the broader UI/settings tests for regressions**

Run: `python -m pytest tests/ -q -k "model_settings or setup or translation_options or settings_save"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gemini_translator/ui/widgets/model_settings_widget.py tests/test_model_settings_widget.py
git commit -m "feat(fallback): embed fallback panel in shared ModelSettingsWidget

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS (all green, including the 7 new test files). Investigate and fix any regression before proceeding.

- [ ] **Step 2: Import smoke check**

Run: `python -c "import gemini_translator.core.worker_helpers.content_filter_fallback as m; import gemini_translator.ui.widgets.content_filter_fallback_panel as p; print('ok')"`
Expected: prints `ok` with no ImportError (guards against a circular import via the orchestrator).

- [ ] **Step 3: Manual smoke (optional but recommended)**

Launch the app (see RUN.md / run.sh). In the Translator window, open model settings → confirm the "Резерв при блокировке контента" group is present, the enable checkbox gates the controls, choosing a provider lists its models and the green-key indicator updates, and a non-thinking model disables the thinking control. Repeat the visual check in the Glossary-build and Consistency windows (same widget).

- [ ] **Step 4: Final commit (if any manual fixes were needed)**

```bash
git add -A
git commit -m "test(fallback): full-suite verification fixes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review notes (for the executor)

- **Spec coverage:** UI in shared widget (Task 6-7) → all three windows; translation+glossary execution (Task 4); consistency execution (Task 5); green-key pool (Task 1); fallback-also-blocked → error (Tasks 3/5); transient budget + rotation (Tasks 1/3/5); thinking per fallback model (Tasks 2/6); persistence (Tasks 6-7).
- **Boundary (from spec):** content blocks detected only during post-parse validation (not at the API response) are *not* rerouted — they keep current behavior. No task changes that; do not add one.
- **Naming consistency:** the settings keys `content_filter_fallback_*` are identical across panel `get_config`/`set_config`, worker reads (`run_content_filter_fallback`), and consistency reads (`_run_consistency_content_filter_fallback`). The green-pool helper `green_keys_for_provider(settings_manager, provider_id, model_id)` is called with the same argument order everywhere.
