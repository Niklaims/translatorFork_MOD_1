# Benchmark: three-prompts-flash-lite-real-epub

- Created: 2026-07-07T16:46:13.627341+00:00
- Prompt-only: False
- Runs: 3

## Ranking

| Prompt | Model | Runs | OK | Errors | Avg score | Avg latency ms | Avg input tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy-default | gemini-3.1-flash-lite | 1 | 1 | 0 | 95.0 | 21906.0 | 4726.0 |
| basic-translation-short | gemini-3.1-flash-lite | 1 | 1 | 0 | 90.0 | 18802.0 | 10987.0 |
| basic-translation | gemini-3.1-flash-lite | 1 | 0 | 1 | None | 13622.0 | 5761.0 |

## Issues

- `real-epub-chapter-00001-2143chars` / `legacy-default` / `gemini-3.1-flash-lite`: html tag count changed: {"p": -1}
- `real-epub-chapter-00001-2143chars` / `basic-translation` / `gemini-3.1-flash-lite`: run failed: PartialGenerationError; PartialGenerationError: Gemini Stream Error: This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.
- `real-epub-chapter-00001-2143chars` / `basic-translation-short` / `gemini-3.1-flash-lite`: html tag count changed: {"p": -2}
