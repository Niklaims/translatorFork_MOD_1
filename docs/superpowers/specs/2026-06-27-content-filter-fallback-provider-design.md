# Резервный провайдер/модель при блокировке контента — дизайн

**Дата:** 2026-06-27
**Статус:** утверждён к реализации (Вариант 1)

## Проблема

Когда основная модель возвращает блокировку контента (Prohibited content / SAFETY),
глава/чанк после исчерпания попыток помечается как `filtered` и уходит в ошибку
(`error_analyzer._log_and_fail_permanently`, `worker.py:704`). Пользователь хочет
вместо ухода в ошибку автоматически переотправлять заблокированный чанк/главу на
**резервного провайдера и модель**, и при успешном переводе сохранять результат как
обычно, после чего очередь продолжает работать **основной** моделью.

## Цель

Добавить в настройки модели опциональный «резерв при блокировке контента»:
галочка включения, выбор провайдера (пул берётся из всех «зелёных» ключей этого
провайдера), выбор модели, температура и режим thinking (если модель поддерживает).
Фича должна работать в трёх окнах: **Переводчик EPUB**, **Сборка глоссария**,
**Согласованность** — все три используют общий `ModelSettingsWidget`.

## Текущее поведение (база)

- Все процессоры задач вызывают единый чокпоинт
  `BaseTaskProcessor._execute_api_call` (`core/worker_helpers/taskers/base_processor.py:63`),
  который либо оркеструет параллельных провайдеров, либо зовёт
  `worker.api_handler_instance.execute_api_call`.
- Блокировка контента приходит как `ContentFilterError` (а также как
  `PartialGenerationError` с `reason ∈ {SAFETY, PROHIBITED_CONTENT}`, когда его кидает
  хендлер) и классифицируется в `ErrorAnalyzer._classify_exception` →
  `ErrorType.CONTENT_FILTER`.
- Уже существует развитая инфраструктура `core/worker_helpers/provider_orchestrator.py`
  (`ProviderAttempt`, `_ProviderWorkerProxy`, `_run_attempt`, `_resolve_model`,
  `_api_key_for_provider`, пул ключей по провайдерам) — переиспользуем её.
- Согласованность ходит в API **отдельным** путём:
  `core/consistency_engine.py:_call_api_with_cached_handler` (~стр. 2135) зовёт
  `handler.execute_api_call` напрямую, минуя `_execute_api_call`.
- Сборка глоссария идёт через процессор (`GlossaryBatchProcessor.execute` →
  `self._execute_api_call`, `glossary_batch_processor.py:187`) — то есть через общий чокпоинт.
- Настройки сессии копируются в атрибуты воркера (`worker.py:209-211` — `setattr(self, key, value)`
  для всех ключей `params`), поэтому любые новые ключи из `get_settings()` автоматически
  становятся атрибутами воркера.
- «Зелёный» ключ = ключ, который для пары провайдер/модель **не** помечен исчерпанным:
  `not settings_manager.is_key_limit_active(key_info, model_id)`. Источник истины —
  `api_keys_with_status` (`utils/settings.py`), та же логика, что за кнопкой «Добавить все
  зелёные» в `KeyManagementWidget`.

## Выбранный подход (Вариант 1)

Реактивный fallback в точке `_execute_api_call`: ловим блокировку ровно там, где
получен ответ API, и переотправляем **тот же промпт** на резервного провайдера,
переиспользуя машинерию `provider_orchestrator`. Для Согласованности — такой же по
смыслу хук в её собственной точке вызова API. UI — один раз в общий `ModelSettingsWidget`.

Отклонены: Вариант 2 (повесить fallback на оркестратор параллельных провайдеров —
смешивает две фичи); Вариант 3 (повтор всей задачи на уровне воркера — инвазивнее,
риск двойных вызовов основной модели).

## Дизайн

### 1. UI — `ui/widgets/model_settings_widget.py`

Новая под-секция «Резерв при блокировке контента» внутри `ModelSettingsWidget`
(появляется во всех окнах-потребителях автоматически):

- **Чекбокс** «Включить резерв при блокировке (Prohibited content)» — гейтит
  (enable/disable) все остальные контролы секции.
- **Combo провайдера** (`fallback_provider_combo`) — список провайдеров. Рядом —
  индикатор/предупреждение о «зелёных» ключах: при выборе провайдера без зелёных
  ключей показываем «Нет зелёных ключей для этого провайдера». Пул собирается
  автоматически, отдельного выбора ключей в UI нет.
- **Combo модели** (`fallback_model_combo`) — модели выбранного провайдера; та же
  логика наполнения, что у основного `model_combo` (через `api_config`/`_resolve_model`).
- **Температура** (`fallback_temperature_spin` + `fallback_temperature_override_checkbox`),
  по образцу основной температуры.
- **Thinking** (`fallback_thinking_checkbox` + бюджет/уровни) — показывается/прячется
  по той же логике, что в `_on_model_changed` (`model_settings_widget.py:1522`):
  `supports_thinking = (thinking_levels is not None) or (min_thinking_budget is not False)`.
  Уровни (`thinking_levels`) → combo уровней; иначе → спин бюджета; иначе скрыто.

Сигналы контролов подключаются к `_emit_settings_changed` (как у существующих).
Смена `fallback_provider_combo` обновляет модели; смена `fallback_model_combo` обновляет
видимость thinking-контролов.

### 2. Схема настроек — `get_settings()` / `set_settings()`

Добавляются ключи (по образцу существующих `thinking_*`, `temperature_*`,
`skip_content_filter_retry`):

```
content_filter_fallback_enabled: bool
content_filter_fallback_provider: str            # id провайдера
content_filter_fallback_model: str               # display-имя модели
content_filter_fallback_temperature: float
content_filter_fallback_temperature_override: bool
content_filter_fallback_thinking_enabled: bool
content_filter_fallback_thinking_budget: int | None
content_filter_fallback_thinking_level: str | None
```

Они попадают в `params` сессии → `worker.py:209-211` делает их атрибутами воркера
(`worker.content_filter_fallback_*`). Для Согласованности тот же словарь доступен
движку через `settings_manager` / переданный config.

### 3. Пул «зелёных» ключей — новый хелпер

Функция собирает зелёные ключи fallback-провайдера:

- Источник: `settings_manager` → `api_keys_with_status`, фильтр `provider == fallback_provider`.
- Зелёный предикат: `not settings_manager.is_key_limit_active(key_info, fallback_model_id)`
  (плюс исключение явно приостановленных, по аналогии с менеджером ключей).
- Если пул пуст → специальное исключение/сигнал «нет зелёных ключей» → глава в ошибку
  с понятным сообщением в лог.

Переиспользуем существующий `_api_key_for_provider` / `_active_keys_by_provider` из
`provider_orchestrator.py` как основу, но источник — именно зелёные ключи из статусов,
а не только активные ключи сессии.

### 4. Резервный прогон — новый модуль `core/worker_helpers/content_filter_fallback.py`

Главная функция (async), вызывается из `_execute_api_call` при блокировке:

1. Прочитать конфиг резерва с воркера (`content_filter_fallback_*`); если выключен — не вмешиваться.
2. Собрать пул зелёных ключей fallback-провайдера; пусто → пробросить ошибку «нет ключей».
3. Построить `ProviderAttempt` (провайдер/модель/ключ/температура) и прогнать **тот же
   промпт** через `_run_attempt` (прокси-воркер подменяет провайдера/модель/температуру;
   thinking-настройки fallback пробрасываются через расширение `_ProviderWorkerProxy`/attempt),
   те же `call_kwargs`.
4. Обработка результата:
   - **Успех** → вернуть текст вызывающему `_execute_api_call`; далее тот же процессор
     парсит/валидирует/сохраняет как обычно; следующий чанк — основной моделью.
   - **Блокировка во fallback** (`ContentFilterError` / safety-partial) → пробросить как
     content-filter → глава в ошибку (как сейчас). Ретраев по блокировке нет.
   - **Временная ошибка** (`NetworkError`, `TemporaryRateLimitError`, `RateLimitExceededError`,
     прочий API-сбой) → ротация на следующий зелёный ключ и повтор в рамках **того же
     бюджета**, что у основной модели (`ErrorAnalyzer.FAILURE_RULES` / `TOTAL_ATTEMPTS_LIMIT`).
     По исчерпании бюджета — пробросить последнюю ошибку (далее стандартная машинерия воркера).

### 5. Интеграция — перевод и глоссарий

В `BaseTaskProcessor._execute_api_call` (`base_processor.py:63`) обернуть существующий
вызов в `try/except`:

```
try:
    <existing orchestrate-or-normal call>
except (ContentFilterError, PartialGenerationError) as exc:
    if _is_content_block(exc) and fallback_enabled(self.worker):
        return await run_content_filter_fallback(self.worker, prompt, log_prefix,
                                                 task_info=task_info,
                                                 operation_context=context_payload,
                                                 call_kwargs=kwargs)
    raise
```

`_is_content_block` = `ContentFilterError`, либо `PartialGenerationError` с
`reason ∈ {SAFETY, PROHIBITED_CONTENT}`. Покрывает перевод (epub/chunk/raw) и сборку
глоссария «бесплатно».

### 6. Интеграция — Согласованность

В `consistency_engine._call_api_with_cached_handler` (~2135) обернуть
`handler.execute_api_call` в такой же `try/except`. При блокировке и включённом резерве —
выполнить резервный прогон (тот же `content_filter_fallback`, адаптированный под
вызов из движка: провайдер/модель/ключи берутся из конфига резерва и зелёных ключей через
`settings_manager`). Бюджет/ротация/правила те же.

## Матрица поведения

| Событие в основной модели | Резерв выкл | Резерв вкл |
|---|---|---|
| Успех | сохранить | сохранить |
| Блокировка контента | как сейчас (ретраи/skip → `filtered`/ошибка) | прогон fallback |
| Прочие ошибки | как сейчас | как сейчас (резерв не трогает) |

| Событие во fallback | Действие |
|---|---|
| Успех | сохранить результат, продолжить основной моделью |
| Блокировка контента | в ошибку (как сейчас) |
| Временная ошибка (сеть/limit/исчерпан ключ) | ротация зелёного ключа, повтор в бюджете основной |
| Нет зелёных ключей провайдера | ошибка «нет ключей» → глава в ошибку |

Приоритет: при включённом резерве он имеет приоритет над `skip_content_filter_retry`
для случая блокировки (сначала пробуем резерв).

## Стратегия тестирования (TDD)

- `green_keys_pool`: фильтрация зелёных ключей по провайдеру/модели; пустой пул.
- `_execute_api_call`: при `ContentFilterError` и включённом резерве вызывается fallback,
  его текст возвращается процессору; при выключенном — пробрасывается исходная ошибка.
- Fallback успешен → результат сохраняется обычным путём процессора.
- Fallback тоже заблокирован → content-filter → задача в ошибку.
- Временная ошибка во fallback → ротация ключей, повтор в бюджете, затем проброс.
- Нет зелёных ключей → понятная ошибка.
- Persist: `get_settings()/set_settings()` round-trip новых ключей.
- UI smoke (pytest-qt): контролы появляются, гейтятся чекбоксом, thinking показывается
  только для поддерживающих моделей.
- Согласованность: хук в движке вызывает fallback при блокировке.

## Файлы к изменению

- `gemini_translator/ui/widgets/model_settings_widget.py` — UI секции + `get_settings`/`set_settings` + логика провайдер/модель/thinking.
- `gemini_translator/core/worker_helpers/content_filter_fallback.py` — **новый** модуль (пул ключей + резервный прогон).
- `gemini_translator/core/worker_helpers/taskers/base_processor.py` — `try/except` в `_execute_api_call`.
- `gemini_translator/core/consistency_engine.py` — `try/except` вокруг прямого `execute_api_call`.
- `gemini_translator/core/worker_helpers/provider_orchestrator.py` — при необходимости расширить `_ProviderWorkerProxy`/`ProviderAttempt` для проброса thinking-настроек fallback (переиспользование `_run_attempt`).
- `tests/` — новые тесты по списку выше.

## Границы (вне скоупа)

- Поздно-детектируемые safety-обрывы, всплывающие уже при пост-парсинге ответа (не на
  самом ответе API), остаются текущим поведением (→ ошибка). Основной кейс «пришёл ответ
  с блокировкой» покрыт.
- `ModelSettingsWidget` общий, поэтому контролы появятся и в окнах Fixer/Correction/Qidian;
  исполнение там подхватится автоматически только если путь идёт через `_execute_api_call`.
  Явная провязка делается для трёх запрошенных окон: Перевод, Сборка глоссария, Согласованность.
- Цепочка из нескольких резервных провайдеров не предусмотрена — один резервный
  провайдер/модель на окно.
