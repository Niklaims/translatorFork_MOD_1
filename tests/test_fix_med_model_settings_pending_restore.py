"""Регресс: сохранённая модель не должна теряться при восстановлении настроек.

Находка группы ui_widgets_model_settings_widget: ``ModelSettingsWidget.set_settings``
применял модель через ``model_combo.findText``. Если к этому моменту список
моделей ещё не соответствовал сохранённому провайдеру (комбобокс пуст или в нём
модели другого провайдера), выбор молча подменялся индексом 0 — «выбранная
модель не сохраняется»: при следующем сохранении уходила уже чужая модель.

Фикс: выбранная модель запоминается (``_pending_model_name``) и применяется,
когда ``set_available_models`` наполняет список; ручной выбор пользователя
(сигнал ``activated``) отложенное восстановление отменяет.
"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GT_DISABLE_LOCAL_MODEL_DISCOVERY", "1")

from PyQt6 import QtCore, QtWidgets

from gemini_translator.api import config as api_config
from gemini_translator.ui.widgets.model_settings_widget import ModelSettingsWidget


class _DummyBus(QtCore.QObject):
    event_posted = QtCore.pyqtSignal(dict)


_MISSING = object()


def _restore_attr(obj, name, previous):
    if previous is _MISSING:
        if hasattr(obj, name):
            delattr(obj, name)
    else:
        setattr(obj, name, previous)


class _WidgetSettingsStub:
    def __init__(self, config_dir):
        self.config_dir = config_dir
        self._system_prompts = {}
        self._last_settings = {}
        self._full_session_settings = {}

    def load_system_prompts(self):
        return dict(self._system_prompts)

    def save_system_prompts(self, prompts):
        self._system_prompts = dict(prompts or {})
        return True

    def get_last_system_prompt_text(self):
        return ""

    def get_last_system_prompt_preset_name(self):
        return ""

    def save_last_system_prompt_preset_name(self, preset_name):
        return True

    def get_last_project_folder(self):
        return self.config_dir

    def load_full_session_settings(self):
        return dict(self._full_session_settings)

    def get_last_settings(self):
        return dict(self._last_settings)


def _providers_with_models(min_models=2):
    """Провайдеры, у которых есть модели: [(provider_id, [display_name, ...])]."""
    result = []
    for provider_id, provider_config in api_config.api_providers().items():
        models = list((provider_config.get("models") or {}).keys())
        if len(models) >= min_models:
            result.append((provider_id, models))
    return result


class SavedModelRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.event_bus = _DummyBus()

    def _create_widget(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        settings = _WidgetSettingsStub(temp_dir.name)
        previous_getter = getattr(self.app, "get_settings_manager", _MISSING)
        self.app.get_settings_manager = lambda settings=settings: settings
        self.addCleanup(_restore_attr, self.app, "get_settings_manager", previous_getter)
        widget = ModelSettingsWidget(settings_manager=settings)
        self.addCleanup(widget.close)
        return widget

    def setUp(self):
        api_config.initialize_configs()
        providers = _providers_with_models()
        self.assertTrue(providers, "нет провайдера с моделями для теста")
        self.provider_id, self.model_names = providers[0]
        # Берём последнюю модель: она заведомо не первая, поэтому подмена
        # индексом 0 проявится как расхождение.
        self.target_model = self.model_names[-1]

    def test_saved_model_survives_empty_model_list_during_restore(self):
        widget = self._create_widget()
        self.assertEqual(widget.model_combo.count(), 0)

        widget.set_settings({"provider": self.provider_id, "model": self.target_model})
        widget.set_available_models(self.provider_id, fetch_async=False)

        self.assertEqual(widget.model_combo.currentText(), self.target_model)

    def test_saved_model_survives_provider_mismatch_during_restore(self):
        other = [
            (provider_id, names)
            for provider_id, names in _providers_with_models()
            if provider_id != self.provider_id
            and self.target_model not in names
        ]
        if not other:
            self.skipTest("нет второго провайдера с другими моделями")
        other_provider, _ = other[0]

        widget = self._create_widget()
        widget.set_available_models(other_provider, fetch_async=False)
        widget.set_settings({"provider": self.provider_id, "model": self.target_model})
        widget.set_available_models(self.provider_id, fetch_async=False)

        self.assertEqual(widget.model_combo.currentText(), self.target_model)

    def test_round_trip_get_settings_then_set_settings_keeps_model(self):
        first = self._create_widget()
        first.set_available_models(self.provider_id, fetch_async=False)
        index = first.model_combo.findText(self.target_model)
        self.assertNotEqual(index, -1)
        first.model_combo.setCurrentIndex(index)
        saved = first.get_settings()
        self.assertEqual(saved["model"], self.target_model)

        second = self._create_widget()
        second.set_settings({"provider": self.provider_id, **saved})
        second.set_available_models(self.provider_id, fetch_async=False)

        self.assertEqual(second.model_combo.currentText(), self.target_model)
        self.assertEqual(second.get_settings()["model"], self.target_model)

    def test_manual_selection_cancels_pending_restore(self):
        widget = self._create_widget()
        widget.set_settings({"provider": self.provider_id, "model": self.target_model})
        self.assertEqual(widget._pending_model_name, self.target_model)

        widget._on_model_combo_activated(0)

        self.assertIsNone(widget._pending_model_name)


if __name__ == "__main__":
    unittest.main()
