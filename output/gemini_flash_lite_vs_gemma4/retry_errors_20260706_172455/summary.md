# Benchmark: gemini-flash-lite-vs-gemma4

- Created: 2026-07-06T17:41:03.719332+00:00
- Prompt-only: False
- Runs: 2

## Ranking

| Prompt | Model | Runs | OK | Errors | Avg score | Avg latency ms | Avg input tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| project-default | gemma-4-31b | 2 | 2 | 0 | 31.53 | 26716.0 | 3298.5 |

## Issues

- `html-link-preservation` / `project-default` / `gemma-4-31b`: html tag count changed: {"a": 5, "p": 5}; length ratio out of range: 30.148; reference similarity below 0.20: 0.069
- `zh-style-and-term` / `project-default` / `gemma-4-31b`: found forbidden terms: 林澈, 玉符; html tag count changed: {"p": 3}; CJK residue chars: 67; length ratio out of range: 101.710; reference similarity below 0.20: 0.076
