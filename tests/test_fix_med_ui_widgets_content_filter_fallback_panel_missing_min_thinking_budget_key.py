"""Регресс на находку ui-widgets-b/bugs/4-fallback-panel-thinking-suppor.

`_update_model_dependent_controls` трактовал ОТСУТСТВИЕ ключа
`min_thinking_budget` в конфиге модели как поддержку thinking (fail-open):
`min_budget is not False` истинно и для `None` (ключ не задан), и для любого
явного числа. В конфиге реально существуют модели (openrouter/perplexica/
omniroute), которые вообще не объявляют этот ключ и thinking не
поддерживают — панель должна оставлять чекбокс 'Thinking' выключенным для
них, как для моделей с явным `min_thinking_budget: False`.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.api import config as api_config
from gemini_translator.ui.widgets.content_filter_fallback_panel import (
    ContentFilterFallbackPanel,
)


class FakeSettings:
    def __init__(self, keys=None):
        self.keys = keys if keys is not None else [
            {"provider": "openrouter", "key": "green-openrouter-key"},
        ]

    def load_key_statuses(self):
        return list(self.keys)

    def is_key_limit_active(self, key_info, model_id):
        return False


class MissingMinThinkingBudgetKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        # Модель без thinkingLevel и БЕЗ ключа min_thinking_budget вообще
        # (как реальные модели openrouter, не поддерживающие thinking).
        self.providers = {
            "openrouter": {
                "display_name": "OpenRouter",
                "models": {
                    "NoThinkingKey": {
                        "id": "no-thinking-key-model",
                        "provider": "openrouter",
                        # ключ min_thinking_budget намеренно отсутствует
                    },
                },
            },
        }
        self.all_models = {
            name: model
            for provider in self.providers.values()
            for name, model in provider["models"].items()
        }
        self.patches = [
            patch.object(api_config, "api_providers_view", return_value=self.providers),
            patch.object(api_config, "all_models_view", return_value=self.all_models),
            patch.object(api_config, "ensure_dynamic_provider_models"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _create_panel(self, settings_manager=None):
        panel = ContentFilterFallbackPanel(settings_manager=settings_manager)
        self.addCleanup(panel.close)
        return panel

    def test_model_without_min_thinking_budget_key_disables_thinking(self):
        panel = self._create_panel(FakeSettings())

        panel.set_config(
            {
                "content_filter_fallback_enabled": True,
                "content_filter_fallback_provider": "openrouter",
                "content_filter_fallback_model": "NoThinkingKey",
                "content_filter_fallback_thinking_enabled": True,
                "content_filter_fallback_thinking_budget": 2048,
                "content_filter_fallback_thinking_level": "HIGH",
            }
        )

        config = panel.get_config()

        # Ключа min_thinking_budget в конфиге модели вообще нет — модель
        # не заявляет поддержку thinking, значит панель обязана вести себя
        # так же, как для модели с явным min_thinking_budget: False.
        self.assertFalse(panel.thinking_checkbox.isEnabled())
        self.assertFalse(panel.thinking_checkbox.isChecked())
        self.assertFalse(config["content_filter_fallback_thinking_enabled"])
        self.assertIsNone(config["content_filter_fallback_thinking_budget"])
        self.assertIsNone(config["content_filter_fallback_thinking_level"])


if __name__ == "__main__":
    unittest.main()
