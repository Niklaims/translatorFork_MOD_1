# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# Вспомогательные утилиты
# ---------------------------------------------------------------------------
# Этот файл содержит небольшие, но полезные классы и функции общего
# назначения, используемые в разных частях проекта.
# - format_size: форматирование размера файла.
# - TokenCounter: подсчет токенов и оценка стоимости.
# - ErrorAnalyzer: анализ ошибок API.
# ---------------------------------------------------------------------------

import math
import re
import time
from typing import Any

from . import cjk_ranges

GEMINI_ASCII_CHARS_PER_TOKEN = 4.0
GEMINI_CYRILLIC_CHARS_PER_TOKEN = 2.2
GEMINI_CJK_CHARS_PER_TOKEN = 1.5
GEMINI_OTHER_CHARS_PER_TOKEN = 2.5

OPENROUTER_ASCII_CHARS_PER_TOKEN = 3.5
OPENROUTER_CYRILLIC_CHARS_PER_TOKEN = 1.0
OPENROUTER_CJK_CHARS_PER_TOKEN = 1.0
OPENROUTER_OTHER_CHARS_PER_TOKEN = 1.5

_ASCII_RUN_PATTERN = re.compile(r'[\x00-\x7f]+')
_CYRILLIC_RUN_PATTERN = re.compile(r'[\u0400-\u04ff]+')
# cluster-32 dedup: диапазон (Ext-A + Unified + кана + хангыль) теперь
# живёт в gemini_translator.utils.cjk_ranges.CJK_WITH_EXT_A_RUN_RE — то же
# самое множество символов, что и раньше, один источник истины.


def as_list(value: Any, *, sort_sets: bool = False) -> list:
    """Приводит значение к списку.

    Каноническая реализация для cluster-50:
    - ``None`` -> ``[]``.
    - ``list`` возвращается как есть (без копирования).
    - ``tuple`` разворачивается в список своих элементов.
    - ``set``: по умолчанию (``sort_sets=False``) набор целиком оборачивается
      как единственный элемент (``[value]``). Передайте ``sort_sets=True``,
      чтобы получить ``sorted(value)``.
    - любой другой скаляр оборачивается в список из одного элемента.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        if sort_sets:
            return sorted(value)
        return [value]
    return [value]


def safe_int(
    value: Any,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Безопасно приводит значение к ``int`` с опциональным клампом.

    Каноническая реализация для finding-core-b/design/3:
    - ``value`` парсится через ``int()``; при ``TypeError``/``ValueError``
      подставляется ``default``.
    - ``minimum``/``maximum`` по умолчанию ``None`` — без них функция ничего
      не клампает.
    - Если ``minimum`` передан, результат клампится к нему — причём клампу
      подвергается и ``default``, если ``value`` не распарсилось.
    - ``maximum``, если передан, клампит результат сверху.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _count_chars(pattern, text):
    # Считаем длины непрерывных серий вместо findall по одному символу
    return sum(m.end() - m.start() for m in pattern.finditer(text))


def estimate_gemini_tokens(text):
    """Estimate Gemini input tokens without an API round trip."""
    if not text:
        return 0

    text = str(text)
    ascii_like_chars = _count_chars(_ASCII_RUN_PATTERN, text)
    cyrillic_chars = _count_chars(_CYRILLIC_RUN_PATTERN, text)
    cjk_chars = _count_chars(cjk_ranges.CJK_WITH_EXT_A_RUN_RE, text)
    other_chars = max(0, len(text) - ascii_like_chars - cyrillic_chars - cjk_chars)

    total_tokens = (
        (ascii_like_chars / GEMINI_ASCII_CHARS_PER_TOKEN)
        + (cyrillic_chars / GEMINI_CYRILLIC_CHARS_PER_TOKEN)
        + (cjk_chars / GEMINI_CJK_CHARS_PER_TOKEN)
        + (other_chars / GEMINI_OTHER_CHARS_PER_TOKEN)
    )
    return max(1, int(math.ceil(total_tokens)))


def estimate_openrouter_tokens(text):
    """Estimate tokens for OpenRouter, OpenAI, and other standard providers."""
    if not text:
        return 0

    text = str(text)
    ascii_like_chars = len(re.findall(r'[\x00-\x7f]', text))
    cyrillic_chars = len(re.findall(r'[\u0400-\u04ff]', text))
    cjk_chars = len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', text))
    other_chars = max(0, len(text) - ascii_like_chars - cyrillic_chars - cjk_chars)

    total_tokens = (
        (ascii_like_chars / OPENROUTER_ASCII_CHARS_PER_TOKEN)
        + (cyrillic_chars / OPENROUTER_CYRILLIC_CHARS_PER_TOKEN)
        + (cjk_chars / OPENROUTER_CJK_CHARS_PER_TOKEN)
        + (other_chars / OPENROUTER_OTHER_CHARS_PER_TOKEN)
    )
    return max(1, int(math.ceil(total_tokens)))


# --- Добавляем глобальную проверку BeautifulSoup, так как она нужна в main.py ---
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    print("WARNING: beautifulsoup4 library not found. EPUB/HTML processing will be disabled.")
    print("Install it using: pip install beautifulsoup4")


def format_size(size_bytes):
    """Converts bytes to a human-readable format (KB, MB, GB)."""
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024))) if size_bytes > 0 else 0
    i = min(i, len(size_name) - 1)
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


def format_compact_number(value) -> str:
    """Компактно форматирует число: 1_234 -> '1.2K', 2_500_000 -> '2.5M'."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def format_thousands(value) -> str:
    """Форматирует целое число с разделением тысяч пробелом: 1234567 -> '1 234 567'."""
    if value is None:
        return "0"
    return f"{int(value):,}".replace(",", " ")


class TokenUsageTrackerMixin:
    """Учёт токенов текущей сессии + подпись/тултип с компактными числами."""

    _token_usage_tooltip_scope = "текущий сеанс"

    def _reset_token_usage(self):
        self._token_input_total = 0
        self._token_output_total = 0
        self._token_total = 0
        self._update_token_usage_label()

    def _accumulate_token_usage(self, payload: dict) -> None:
        try:
            input_tokens = int((payload or {}).get('input_tokens', 0) or 0)
            output_tokens = int((payload or {}).get('output_tokens', 0) or 0)
            total_tokens = int((payload or {}).get('total_tokens', input_tokens + output_tokens) or 0)
        except (TypeError, ValueError):
            return
        self._token_input_total += max(0, input_tokens)
        self._token_output_total += max(0, output_tokens)
        self._token_total += max(0, total_tokens)
        self._update_token_usage_label()

    def _update_token_usage_label(self):
        total = format_compact_number(self._token_total)
        input_tokens = format_compact_number(self._token_input_total)
        output_tokens = format_compact_number(self._token_output_total)
        self.token_usage_label.setText(f"Токены: ~{total}")
        self.token_usage_label.setToolTip(
            f"Оценка токенов за {self._token_usage_tooltip_scope}: всего ~{total}, "
            f"вход ~{input_tokens}, выход ~{output_tokens}."
        )


class TokenCounter:
    """Подсчет токенов для отслеживания использования API"""
    def __init__(self, provider="gemini"):
        self.provider = provider
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.tokens_per_minute = []
        self.session_start_time = time.time()
        self.last_minute_check = time.time()
        self.chapters_stats = []

    def estimate_tokens(self, text):
        """
        Оценивает количество токенов в тексте, учитывая разные алфавиты.
        """
        if not text:
            return 0
        if self.provider == "gemini":
            return estimate_gemini_tokens(text)
        return estimate_openrouter_tokens(text)

    def estimate_cost(self, input_tokens, output_tokens, model_name="gemini-2.5-pro"):
        """Оценивает стоимость в USD"""
        pricing = {
            "gemini-2.5-pro": {"input": 0.00025, "output": 0.001},
            "gemini-2.5-flash": {"input": 0.000025, "output": 0.0001},
            "gemini-2.0-flash": {"input": 0.000015, "output": 0.00006}
        }
        model_key = "gemini-2.5-pro"
        for key in pricing.keys():
            if key in model_name.lower():
                model_key = key
                break
        rates = pricing[model_key]
        input_cost = (input_tokens / 1000) * rates["input"]
        output_cost = (output_tokens / 1000) * rates["output"]
        return input_cost + output_cost

    def add_chapter_stats(self, chapter_name, html_size, prompt_size, glossary_size, estimated_output):
        """Добавляет статистику для главы"""
        stats = {
            'chapter': chapter_name,
            'html_tokens': self.estimate_tokens(html_size) if isinstance(html_size, str) else html_size,
            'prompt_tokens': self.estimate_tokens(prompt_size) if isinstance(prompt_size, str) else prompt_size,
            'glossary_tokens': self.estimate_tokens(glossary_size) if isinstance(glossary_size, str) else glossary_size,
            'estimated_output_tokens': estimated_output,
            'total_input': 0,
            'estimated_cost': 0
        }
        stats['total_input'] = stats['html_tokens'] + stats['prompt_tokens'] + stats['glossary_tokens']
        stats['estimated_cost'] = self.estimate_cost(stats['total_input'], stats['estimated_output_tokens'])
        self.chapters_stats.append(stats)
        return stats

    def get_estimation_report(self, num_windows=1):
        """Генерирует отчет с оценкой токенов"""
        if not self.chapters_stats:
            return "Нет данных для оценки"

        total_input = sum(ch['total_input'] for ch in self.chapters_stats)
        total_output = sum(ch['estimated_output_tokens'] for ch in self.chapters_stats)
        total_cost = sum(ch['estimated_cost'] for ch in self.chapters_stats)

        if num_windows > 1:
            chapters_per_window = len(self.chapters_stats) / num_windows
            tokens_per_window = total_input / num_windows
            cost_per_window = total_cost / num_windows
            report = f"""
═══════════════════════════════════════════
📊 ОЦЕНКА ИСПОЛЬЗОВАНИЯ ТОКЕНОВ
═══════════════════════════════════════════

📚 АНАЛИЗ КОНТЕНТА:
• Всего глав: {len(self.chapters_stats)}
• Средний размер главы: {total_input // len(self.chapters_stats):,} токенов

📥 ВХОДЯЩИЕ ТОКЕНЫ:
• HTML контент: {sum(ch['html_tokens'] for ch in self.chapters_stats):,}
• Промпт (на главу): {self.chapters_stats[0]['prompt_tokens'] if self.chapters_stats else 0:,}
• Глоссарий (средний): {sum(ch['glossary_tokens'] for ch in self.chapters_stats) // max(1, len(self.chapters_stats)):,}
• ИТОГО входящих: {total_input:,}

📤 ИСХОДЯЩИЕ ТОКЕНЫ (оценка):
• Ожидаемый выход: {total_output:,}
• Коэффициент: ~1.1x от входа

💰 ОЦЕНКА СТОИМОСТИ:
• Общая стоимость: ${total_cost:.4f}
• На главу: ${total_cost / len(self.chapters_stats):.4f}

🖥️ ПАРАЛЛЕЛЬНЫЙ РЕЖИМ ({num_windows} окон):
• Глав на окно: ~{chapters_per_window:.0f}
• Токенов на окно: ~{tokens_per_window:,.0f}
• Стоимость на окно: ~${cost_per_window:.4f}

⚠️ ЛИМИТЫ (Gemini бесплатный тариф):
• TPM (токенов/мин): 2,000,000
• RPM (запросов/мин): зависит от модели
• Ваша нагрузка: ~{(total_input / 60):,.0f} токенов/мин

═══════════════════════════════════════════"""
        else:
            report = f"""
═══════════════════════════════════════════
📊 ОЦЕНКА ИСПОЛЬЗОВАНИЯ ТОКЕНОВ
═══════════════════════════════════════════

📚 АНАЛИЗ КОНТЕНТА:
• Всего глав: {len(self.chapters_stats)}
• Средний размер главы: {total_input // max(1, len(self.chapters_stats)):,} токенов

📥 ВХОДЯЩИЕ ТОКЕНЫ:
• HTML контент: {sum(ch['html_tokens'] for ch in self.chapters_stats):,}
• Промпт: {self.chapters_stats[0]['prompt_tokens'] if self.chapters_stats else 0:,} на главу
• Глоссарий: ~{sum(ch['glossary_tokens'] for ch in self.chapters_stats) // max(1, len(self.chapters_stats)):,} на главу
• ИТОГО: {total_input:,}

📤 ОЖИДАЕМЫЙ ВЫХОД: {total_output:,}

💰 ОЦЕНКА СТОИМОСТИ: ${total_cost:.4f}

═══════════════════════════════════════════"""
        return report

    def add_request(self, input_text, output_text=None):
        """Добавляет запрос в статистику"""
        current_time = time.time()
        input_tokens = self.estimate_tokens(input_text)
        output_tokens = self.estimate_tokens(output_text) if output_text else 0
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.tokens_per_minute.append((current_time, input_tokens, output_tokens))
        cutoff_time = current_time - 60
        self.tokens_per_minute = [(t, i, o) for t, i, o in self.tokens_per_minute if t > cutoff_time]
        return input_tokens, output_tokens

    def format_statistics(self):
        """Форматирует собранную статистику по токенам в читаемую строку."""
        duration_seconds = time.time() - self.session_start_time
        duration_minutes = duration_seconds / 60
        total_tokens = self.total_input_tokens + self.total_output_tokens
        avg_tpm = total_tokens / duration_minutes if duration_minutes > 0 else 0
        estimated_cost = self.estimate_cost(self.total_input_tokens, self.total_output_tokens)
        report = f"""
    ═══════════════════════════════════════════
    📊 СТАТИСТИКА ТОКЕНОВ СЕССИИ
    ═══════════════════════════════════════════
    • Продолжительность: {duration_minutes:.2f} мин.
    • Входящие токены: {self.total_input_tokens:,.0f}
    • Исходящие токены: {self.total_output_tokens:,.0f}
    • ВСЕГО ТОКЕНОВ: {total_tokens:,.0f}
    • Средняя скорость: {avg_tpm:,.0f} токенов/мин.
    • Примерная стоимость: ${estimated_cost:.4f}
    ═══════════════════════════════════════════"""
        return report.strip()


def calculate_potential_output_size(html_content, is_cjk):
    """
    Вычисляет потенциальный размер ответа модели в УСЛОВНЫХ СИМВОЛАХ (где 4 символа ~ 1 токен),
    применяя разные коэффициенты к тегам и тексту.
    """
    try:
        if not BS4_AVAILABLE:
            multiplier = 10 if is_cjk else 3
            return len(html_content) * multiplier

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        
        visible_text = soup.get_text(separator=' ', strip=True)
        
        len_html_total = len(html_content)
        len_text_original = len(visible_text)
        len_tags_and_scripts = len_html_total - len_text_original

        if is_cjk:
            text_expansion_ratio = 2.8 
        else:
            text_expansion_ratio = 1.25

        potential_text_size_chars = len_text_original * text_expansion_ratio
        cyrillic_token_weight = 1.8 
        weighted_text_size = potential_text_size_chars * cyrillic_token_weight
        final_potential_size = len_tags_and_scripts + weighted_text_size
        
        return int(final_potential_size)

    except Exception as e:
        print(f"[WARN] Ошибка в calculate_potential_output_size: {e}. Используется упрощенный расчет.")
        multiplier = 10 if is_cjk else 3
        return len(html_content) * multiplier
        
        
def check_value(etalon, value, min_len=None) -> bool:
    """
    Универсальный валидатор.
    Проверяет, что 'value' имеет тот же тип, что и 'etalon'.
    Если min_len не задан, проверяет на "непустоту".
    Если min_len задан, проверяет, что длина value >= min_len.
    Безопасно обрабатывает типы, не имеющие длины.
    """
    if not isinstance(value, type(etalon)):
        return False
    
    if min_len is None:
        return bool(value)
        
    try:
        return len(value) >= min_len
    except TypeError:
        return False
