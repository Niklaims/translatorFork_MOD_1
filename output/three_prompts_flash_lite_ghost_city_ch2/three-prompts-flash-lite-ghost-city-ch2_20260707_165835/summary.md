# Benchmark: three-prompts-flash-lite-ghost-city-ch2

- Created: 2026-07-07T16:58:35.369026+00:00
- Prompt-only: False
- Runs: 3

## Ranking

| Prompt | Model | Runs | OK | Errors | Avg score | Avg latency ms | Avg input tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| basic-translation | gemini-3.1-flash-lite | 1 | 1 | 0 | 90.0 | 10634.0 | 5827.0 |
| basic-translation-short | gemini-3.1-flash-lite | 1 | 1 | 0 | 75.0 | 9955.0 | 11053.0 |
| legacy-default | gemini-3.1-flash-lite | 1 | 1 | 0 | 75.0 | 11194.0 | 4792.0 |

## Issues

- `ghost-city-chapter-00002-2218chars` / `legacy-default` / `gemini-3.1-flash-lite`: html tag count changed: {"p": -8}
- `ghost-city-chapter-00002-2218chars` / `basic-translation` / `gemini-3.1-flash-lite`: html tag count changed: {"p": -2}
- `ghost-city-chapter-00002-2218chars` / `basic-translation-short` / `gemini-3.1-flash-lite`: html tag count changed: {"p": -10}
