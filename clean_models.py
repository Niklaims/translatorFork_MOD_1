import json

with open('config/api_providers.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for provider, p_data in data.items():
    if 'models' in p_data:
        to_delete = []
        for m_name, m_cfg in p_data['models'].items():
            if '(generativelanguage.googleapis.com)' in m_name or '(api.openmodel.ai)' in m_name:
                to_delete.append(m_name)
            elif m_cfg.get('server_discovered'):
                if 'googleapis.com' in m_name or '.ai' in m_name or '.com' in m_name:
                    to_delete.append(m_name)
        for m_name in to_delete:
            del p_data['models'][m_name]

with open('config/api_providers.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
