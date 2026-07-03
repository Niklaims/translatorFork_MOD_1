import os
import json
import tempfile
import pytest
from unittest.mock import patch

from gemini_translator.api import config as api_config

@pytest.fixture
def temp_providers_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({"test_provider": {"models": {"model_a": {"id": "model_a"}}}}, f)
    
    from pathlib import Path
    original_file = api_config._PROVIDERS_FILE
    api_config._PROVIDERS_FILE = Path(path)
    
    # Реинициализируем, чтобы подхватить файл
    api_config._API_PROVIDERS = api_config._load_providers_config()
    api_config._ALL_MODELS = api_config._build_all_models(api_config._compose_runtime_providers())
    
    yield path
    
    api_config._PROVIDERS_FILE = original_file
    os.remove(path)


def test_save_models_to_json(temp_providers_file):
    new_models = {
        "model_b": {"id": "model_b", "server_discovered": True}
    }
    success = api_config._save_models_to_json("test_provider", new_models)
    assert success is True
    
    # Проверяем в памяти
    assert "model_b" in api_config._API_PROVIDERS["test_provider"]["models"]
    
    # Проверяем на диске
    with open(temp_providers_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "model_b" in data["test_provider"]["models"]


def test_delete_model_from_json(temp_providers_file):
    success = api_config.delete_model_from_json("test_provider", "model_a")
    assert success is True
    
    # Проверяем в памяти
    assert "model_a" not in api_config._API_PROVIDERS["test_provider"]["models"]
    
    # Проверяем на диске
    with open(temp_providers_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "model_a" not in data["test_provider"]["models"]


def test_clear_dynamic_models(temp_providers_file):
    new_models = {
        "model_dyn": {"id": "model_dyn", "server_discovered": True},
        "model_user": {"id": "model_user", "user_defined": True},
        "model_static": {"id": "model_static"}
    }
    api_config._save_models_to_json("test_provider", new_models)
    
    success = api_config.clear_dynamic_models("test_provider")
    assert success is True
    
    # Проверяем в памяти
    models = api_config._API_PROVIDERS["test_provider"]["models"]
    assert "model_dyn" not in models
    assert "model_user" not in models
    assert "model_static" in models
    
    # Проверяем на диске
    with open(temp_providers_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    disk_models = data["test_provider"]["models"]
    assert "model_dyn" not in disk_models
    assert "model_user" not in disk_models
    assert "model_static" in disk_models
