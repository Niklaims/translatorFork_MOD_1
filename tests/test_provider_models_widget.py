import pytest
from unittest.mock import MagicMock, patch
from PyQt6 import QtCore, QtWidgets
from gemini_translator.ui.widgets.provider_models_widget import ProviderModelsWidget, ModelLoaderWorker

@pytest.fixture
def settings_manager_mock():
    mock = MagicMock()
    mock.get_active_models_for_provider.return_value = ["model_1"]
    mock.get_api_keys_for_provider.return_value = ["test_key"]
    return mock

@pytest.fixture
def provider_models_widget(qapp, settings_manager_mock):
    widget = ProviderModelsWidget(settings_manager=settings_manager_mock)
    return widget

def test_provider_models_widget_initialization(provider_models_widget):
    assert provider_models_widget.provider_combo is not None
    assert provider_models_widget.load_models_btn is not None
    assert provider_models_widget.add_custom_model_btn is not None

def test_model_loader_worker():
    worker = ModelLoaderWorker("test_provider", api_key="test_key")
    
    with patch("gemini_translator.ui.widgets.provider_models_widget.api_config.refresh_dynamic_models") as mock_refresh:
        worker.run()
        mock_refresh.assert_called_once_with("test_provider", api_key="test_key")

def test_on_load_models_clicked(provider_models_widget, qtbot):
    provider_models_widget._current_provider_id = "test_provider"
    
    # Чтобы не заморачиваться с реальным QThread в тесте, замокаем QThread.start 
    # и просто вызовем run у воркера напрямую.
    with patch("PyQt6.QtCore.QThread.start") as mock_start:
        def fake_start():
            provider_models_widget.loader_worker.run()
            
        mock_start.side_effect = fake_start
        
        with patch("gemini_translator.ui.widgets.provider_models_widget.api_config.refresh_dynamic_models") as mock_refresh:
            with qtbot.waitSignal(provider_models_widget.active_models_changed, timeout=1000):
                provider_models_widget._on_load_models_clicked()
                
            mock_refresh.assert_called_once_with("test_provider", api_key="test_key")
            
    assert provider_models_widget.load_models_btn.isEnabled()
    assert provider_models_widget.load_models_btn.text() == "Загрузить модели"
