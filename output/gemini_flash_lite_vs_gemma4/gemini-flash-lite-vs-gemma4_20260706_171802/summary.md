# Benchmark: gemini-flash-lite-vs-gemma4

- Created: 2026-07-06T17:18:02.134792+00:00
- Prompt-only: False
- Runs: 6

## Ranking

| Prompt | Model | Runs | OK | Errors | Avg score | Avg latency ms | Avg input tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| project-default | gemini-3.1-flash-lite | 3 | 3 | 0 | 90.0 | 1509.0 | 3302.7 |
| project-default | gemma-4-31b | 3 | 2 | 1 | 31.95 | 12953.0 | 3302.7 |

## Issues

- `zh-dialogue-glossary` / `project-default` / `gemini-3.1-flash-lite`: missing required terms: Секта Лазурного Облака; html tag count changed: {"p": 1}
- `zh-dialogue-glossary` / `project-default` / `gemma-4-31b`: run failed: NetworkError; NetworkError: Ошибка сервера (500): Internal error encountered.
- `html-link-preservation` / `project-default` / `gemma-4-31b`: html tag count changed: {"a": 3, "p": 3}; length ratio out of range: 21.093; reference similarity below 0.20: 0.105
- `zh-style-and-term` / `project-default` / `gemini-3.1-flash-lite`: length ratio out of range: 5.355
- `zh-style-and-term` / `project-default` / `gemma-4-31b`: found forbidden terms: 林澈, 玉符; html tag count changed: {"p": 4}; CJK residue chars: 72; length ratio out of range: 81.323; reference similarity below 0.20: 0.086
