import sys
from unittest.mock import Mock, patch
from tests.test_local_model_discovery import LocalModelDiscoveryTests
from gemini_translator.api import config

original_fetch = config._fetch_local_models_json

def logging_fetch(url, *args, **kwargs):
    res = original_fetch(url, *args, **kwargs)
    print(f"FETCHED {url} -> {res[0]}")
    return res

t = LocalModelDiscoveryTests('test_free_deepseek_provider_discovers_openai_compatible_models')
t.setUp()
t.assertEqual = Mock()
t.assertTrue = Mock()

with patch('gemini_translator.api.config._fetch_local_models_json', side_effect=logging_fetch):
    try:
        t.test_free_deepseek_provider_discovers_openai_compatible_models()
    except KeyError:
        print("KeyError occurred as expected.")
