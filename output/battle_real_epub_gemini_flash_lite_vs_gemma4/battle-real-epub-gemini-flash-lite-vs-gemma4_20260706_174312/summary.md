# Benchmark: battle-real-epub-gemini-flash-lite-vs-gemma4

- Created: 2026-07-06T17:43:12.638287+00:00
- Prompt-only: False
- Runs: 2

## Ranking

| Prompt | Model | Runs | OK | Errors | Avg score | Avg latency ms | Avg input tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| project-default-real | gemini-3.1-flash-lite | 1 | 1 | 0 | 95.0 | 10897.0 | 4726.0 |
| project-default-real | gemma-4-31b | 1 | 1 | 0 | 50.0 | 112353.0 | 4726.0 |

## Issues

- `real-epub-chapter-00001-2143chars` / `project-default-real` / `gemini-3.1-flash-lite`: html tag count changed: {"p": -1}
- `real-epub-chapter-00001-2143chars` / `project-default-real` / `gemma-4-31b`: html tag count changed: {"h1": 3, "p": 2}; CJK residue chars: 43
