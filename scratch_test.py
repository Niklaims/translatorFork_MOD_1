from gemini_translator.api.config import initialize_configs, refresh_dynamic_models, api_providers
from unittest.mock import patch
from types import SimpleNamespace

class _D:
    def __init__(self, d): self.d = d
    def json(self): return self.d

def fake_get(url, **kwargs):
    if 'v1/models' in url:
        return _D({'data': [{'id': 'deepseek-reasoner', 'max_context_length': 128000}]})
    return _D({})

initialize_configs()
with patch('gemini_translator.api.config.requests', SimpleNamespace(get=fake_get, post=lambda *a,**k: _D({}))):
    refresh_dynamic_models('free_deepseek')
    print(api_providers()['free_deepseek']['models']['DeepSeek Reasoner (FreeDeepseekAPI)'])
