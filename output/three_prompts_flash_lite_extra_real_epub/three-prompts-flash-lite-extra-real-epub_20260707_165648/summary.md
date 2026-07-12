# Benchmark: three-prompts-flash-lite-extra-real-epub

- Created: 2026-07-07T16:56:48.752722+00:00
- Prompt-only: False
- Runs: 6

## Ranking

| Prompt | Model | Runs | OK | Errors | Avg score | Avg latency ms | Avg input tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| basic-translation | gemini-3.1-flash-lite | 2 | 1 | 1 | 75.0 | 7047.0 | 6253.5 |
| legacy-default | gemini-3.1-flash-lite | 2 | 1 | 1 | 75.0 | 8958.5 | 5219.5 |
| basic-translation-short | gemini-3.1-flash-lite | 2 | 1 | 1 | 75.0 | 12155.0 | 11480.5 |

## Issues

- `weird-apocalypse-chapter-00003-2152chars` / `legacy-default` / `gemini-3.1-flash-lite`: run failed: ContentFilterError; ContentFilterError: Блокировка на уровне промпта: PROHIBITED_CONTENT
- `weird-apocalypse-chapter-00003-2152chars` / `basic-translation` / `gemini-3.1-flash-lite`: run failed: ContentFilterError; ContentFilterError: Блокировка на уровне промпта: PROHIBITED_CONTENT
- `weird-apocalypse-chapter-00003-2152chars` / `basic-translation-short` / `gemini-3.1-flash-lite`: run failed: PartialGenerationError; PartialGenerationError: Генерация прервана (причина: PROHIBITED_CONTENT)
- `ghost-city-chapter-00001-3611chars` / `legacy-default` / `gemini-3.1-flash-lite`: html tag count changed: {"p": -34}
- `ghost-city-chapter-00001-3611chars` / `basic-translation` / `gemini-3.1-flash-lite`: html tag count changed: {"p": -16}
- `ghost-city-chapter-00001-3611chars` / `basic-translation-short` / `gemini-3.1-flash-lite`: html tag count changed: {"p": -18}
