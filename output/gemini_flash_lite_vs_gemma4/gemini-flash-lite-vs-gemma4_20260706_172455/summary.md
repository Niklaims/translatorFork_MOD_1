# Benchmark: gemini-flash-lite-vs-gemma4

- Created: 2026-07-06T17:24:55.252526+00:00
- Prompt-only: False
- Runs: 6

## Ranking

| Prompt | Model | Runs | OK | Errors | Avg score | Avg latency ms | Avg input tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| project-default | gemini-3.1-flash-lite | 3 | 3 | 0 | 90.0 | 1802.7 | 3302.7 |
| project-default | gemma-4-31b | 3 | 1 | 2 | 9.4 | 21229.3 | 3302.7 |

## Issues

- `zh-dialogue-glossary` / `project-default` / `gemini-3.1-flash-lite`: missing required terms: Секта Лазурного Облака; html tag count changed: {"p": 1}
- `zh-dialogue-glossary` / `project-default` / `gemma-4-31b`: found forbidden terms: 青云宗; html tag count changed: {"p": 16}; CJK residue chars: 68; length ratio out of range: 200.059; reference similarity below 0.20: 0.035
- `html-link-preservation` / `project-default` / `gemma-4-31b`: run failed: PartialGenerationError; PartialGenerationError: Генерация прервана (причина: MALFORMED_RESPONSE)
- `zh-style-and-term` / `project-default` / `gemini-3.1-flash-lite`: length ratio out of range: 5.161
- `zh-style-and-term` / `project-default` / `gemma-4-31b`: run failed: NetworkError; NetworkError: Ошибка сервера (500): Internal error encountered.
