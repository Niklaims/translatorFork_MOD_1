import unittest
from types import SimpleNamespace

from gemini_translator.api.handlers.openrouter import OpenRouterApiHandler


def _make_handler(model_config, provider_config=None):
    worker = SimpleNamespace(
        provider_config=provider_config or {"is_async": True},
        model_config=model_config,
    )
    return OpenRouterApiHandler(worker)


class OpenRouterHandlerTests(unittest.TestCase):
    def test_model_without_reasoning_config_leaves_payload_unchanged(self):
        handler = _make_handler({"id": "translator"})
        payload = {"model": "translator"}

        handler._apply_openai_reasoning_options(payload)

        self.assertEqual(payload, {"model": "translator"})

    def test_model_reasoning_effort_is_added_to_payload(self):
        handler = _make_handler({"id": "translator", "reasoning_effort": "high"})
        payload = {"model": "translator"}

        handler._apply_openai_reasoning_options(payload)

        self.assertEqual(payload["reasoning_effort"], "high")

    def test_provider_reasoning_effort_is_used_as_fallback(self):
        handler = _make_handler(
            {"id": "translator"},
            {"is_async": True, "default_reasoning_effort": "HIGH"},
        )
        payload = {"model": "translator"}

        handler._apply_openai_reasoning_options(payload)

        self.assertEqual(payload["reasoning_effort"], "high")

    def test_model_access_denied_error_is_detected(self):
        response_text = (
            '{"error":{"message":"model gemini-3.5-flash-extra-low is not allowed '
            'for this API key","type":"qroute_error"}}'
        )

        self.assertTrue(
            OpenRouterApiHandler._is_model_access_denied_error(403, response_text)
        )

    def test_generic_key_error_is_not_model_access_denied(self):
        response_text = '{"error":{"message":"invalid api key","type":"auth_error"}}'

        self.assertFalse(
            OpenRouterApiHandler._is_model_access_denied_error(403, response_text)
        )


if __name__ == "__main__":
    unittest.main()
