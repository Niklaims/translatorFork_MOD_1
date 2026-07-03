import json

with open('config/api_providers.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

models = d['openmodel']['models']
for m_name, m_data in models.items():
    # Set default context length and max output tokens if not present
    if 'context_length' not in m_data:
        m_data['context_length'] = 128000
    if 'max_output_tokens' not in m_data:
        m_data['max_output_tokens'] = 8192
        
    # Some models have known higher limits
    if 'gemini' in m_name.lower():
        m_data['context_length'] = 1000000
    elif 'deepseek' in m_name.lower() and 'flash' not in m_name.lower():
        m_data['context_length'] = 128000
    elif 'gpt-4' in m_name.lower() or 'gpt-5' in m_name.lower():
        m_data['context_length'] = 128000

with open('config/api_providers.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=4, ensure_ascii=False)
