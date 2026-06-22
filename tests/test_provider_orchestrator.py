import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gemini_translator.core.worker_helpers import provider_orchestrator as orchestrator


class _ApiHandlerStub:
    async def execute_api_call(self, prompt, log_prefix, **kwargs):
        return "synthesis"


class ProviderOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_strategy_is_not_overridden_by_multi_pass_default(self):
        attempts = [
            orchestrator.ProviderAttempt(
                provider_id="primary",
                model_name="Primary",
                model_config={"id": "primary-model"},
                api_key="primary-key",
                label="primary",
            ),
            orchestrator.ProviderAttempt(
                provider_id="secondary",
                model_name="Secondary",
                model_config={"id": "secondary-model"},
                api_key="secondary-key",
                label="secondary",
            ),
        ]
        results_by_label = {
            "primary": orchestrator.ProviderAttemptResult(
                attempt=attempts[0],
                text="short",
            ),
            "secondary": orchestrator.ProviderAttemptResult(
                attempt=attempts[1],
                text="longer translated chapter text",
            ),
        }
        worker = SimpleNamespace(
            parallel_provider_strategy="best_score",
            multi_pass_strategy="merge",
            multi_pass_enabled=False,
            multi_pass_chapter_translation=False,
            api_handler_instance=_ApiHandlerStub(),
            _post_event=lambda *_args, **_kwargs: None,
        )

        async def fake_run_attempt(_worker, attempt, _prompt, _log_prefix, _call_kwargs):
            return results_by_label[attempt.label]

        with patch.object(orchestrator, "_build_attempts", return_value=attempts), \
             patch.object(orchestrator, "_run_attempt", side_effect=fake_run_attempt), \
             patch.object(orchestrator, "_save_attempt_results"):
            result = await orchestrator.execute_orchestrated_api_call(
                worker,
                "prompt",
                "[Test]",
                task_info=("task-1", ("epub",)),
                operation_context={"task_type": "epub", "action": "translate_chapter"},
                call_kwargs={},
            )

        self.assertEqual(result, "longer translated chapter text")


if __name__ == "__main__":
    unittest.main()
