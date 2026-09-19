# -*- coding: utf-8 -*-

import functools
import hashlib
import json
import ntpath
import os
import posixpath
import re
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict, deque

from PyQt6.QtCore import QThread, pyqtSignal

from .language_tools import LanguageDetector, get_chinese_script_variants, normalize_glossary_search_text

try:
    from bs4 import BeautifulSoup, UnicodeDammit
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


# 4: счёт термина больше не зависит от остальных терминов глоссария. Кэши
# версии 3 посчитаны старым способом, где длинные термины забирали текст у
# коротких, — их нужно пересчитать, а не показывать.
TERM_FREQUENCY_CACHE_VERSION = 4
VIRTUAL_PATH_PREFIX = "mem://"


def collect_glossary_originals(glossary_source):
    originals = []
    for entry in glossary_source or []:
        if isinstance(entry, str):
            original = entry
        else:
            original = entry.get("original", "")

        original = str(original or "").strip()
        if original:
            originals.append(original)

    return sorted(set(originals), key=lambda item: item.lower())


def get_epub_signature(epub_path):
    normalized_path = _normalize_signature_path(epub_path)
    if not normalized_path:
        return {"path": None, "exists": False}

    if str(normalized_path).startswith(VIRTUAL_PATH_PREFIX):
        exists = False
        exists_func = getattr(os.path, "exists", None)
        if callable(exists_func):
            try:
                exists = bool(exists_func(normalized_path))
            except Exception:
                exists = False
        return {
            "path": normalized_path,
            "exists": exists,
            "virtual": True,
        }

    try:
        stat_result = os.stat(normalized_path)
    except OSError:
        return {"path": normalized_path, "exists": False}

    return {
        "path": normalized_path,
        "exists": True,
        "size": int(stat_result.st_size),
        "mtime_ns": int(getattr(stat_result, "st_mtime_ns", stat_result.st_mtime * 1_000_000_000)),
    }


def _epub_source_exists(epub_path):
    if not epub_path:
        return False

    path_text = str(epub_path)
    if path_text.startswith(VIRTUAL_PATH_PREFIX):
        return True

    try:
        os.stat(_normalize_signature_path(path_text))
        return True
    except OSError:
        return False


def _normalize_signature_path(path):
    if not path:
        return None

    path_text = str(path)
    if path_text.startswith(VIRTUAL_PATH_PREFIX):
        return path_text

    native_path = ntpath if os.name == "nt" else posixpath
    try:
        return native_path.normcase(native_path.abspath(path_text))
    except Exception:
        return path_text


def build_term_frequency_fingerprint(glossary_source, epub_path):
    fingerprint_source = {
        "version": TERM_FREQUENCY_CACHE_VERSION,
        "terms": collect_glossary_originals(glossary_source),
        "epub": get_epub_signature(epub_path),
    }
    serialized = json.dumps(
        fingerprint_source,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(serialized.encode("utf-8"), usedforsecurity=False).hexdigest()


def is_term_frequency_payload_valid(payload, glossary_source, epub_path):
    if not isinstance(payload, dict):
        return False
    if payload.get("version") != TERM_FREQUENCY_CACHE_VERSION:
        return False
    return payload.get("fingerprint") == build_term_frequency_fingerprint(glossary_source, epub_path)


def build_term_frequency_payload(glossary_source, epub_path, term_stats):
    glossary_terms = collect_glossary_originals(glossary_source)
    prepared_terms = {}

    for term in glossary_terms:
        stats = term_stats.get(term, {}) if isinstance(term_stats, dict) else {}
        prepared_terms[term] = {
            "count": int(stats.get("count", 0) or 0),
            "files": sorted(set(stats.get("files", []))),
        }

    return {
        "version": TERM_FREQUENCY_CACHE_VERSION,
        "fingerprint": build_term_frequency_fingerprint(glossary_terms, epub_path),
        "generated_at": int(time.time()),
        "epub_signature": get_epub_signature(epub_path),
        "terms": prepared_terms,
    }


def get_term_frequency_map(payload):
    if not isinstance(payload, dict):
        return {}
    terms = payload.get("terms", {})
    return terms if isinstance(terms, dict) else {}


def get_term_frequency_range(payload):
    frequency_map = get_term_frequency_map(payload)
    if not frequency_map:
        return 0, 0

    counts = [
        int(stats.get("count", 0) or 0)
        for stats in frequency_map.values()
        if isinstance(stats, dict)
    ]
    if not counts:
        return 0, 0

    return min(counts), max(counts)


def _decode_epub_html(raw_content):
    if raw_content is None:
        return ""
    if isinstance(raw_content, str):
        return raw_content

    if BS4_AVAILABLE:
        decoded = UnicodeDammit(raw_content, is_html=True)
        if decoded.unicode_markup is not None:
            return decoded.unicode_markup

    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1251", "gb18030", "big5", "shift_jis", "euc-kr"):
        try:
            return raw_content.decode(encoding)
        except UnicodeError:
            continue

    return raw_content.decode("utf-8", errors="replace")


def _extract_text_from_html(raw_content):
    raw_content = _decode_epub_html(raw_content)
    if BS4_AVAILABLE:
        soup = BeautifulSoup(raw_content, "html.parser")
        return soup.get_text(separator=" ")
    return re.sub(r"<[^>]+>", " ", raw_content)


def _last_word_variants(word):
    variants = {word}
    lower_word = word.casefold()
    if len(word) < 3 or not re.fullmatch(r"[A-Za-z]+", word):
        return variants

    variants.add(f"{word}'s")

    if lower_word.endswith("y") and len(word) > 3:
        plural = f"{word[:-1]}ies"
    elif lower_word.endswith(("s", "x", "z")) or lower_word.endswith(("ch", "sh")):
        plural = f"{word}es"
    else:
        plural = f"{word}s"

    variants.add(plural)
    variants.add(f"{plural}'")
    return variants


def _alpha_frequency_surfaces(term):
    normalized = normalize_glossary_search_text(term).strip()
    if not normalized or LanguageDetector.is_cjk_text(normalized):
        return set()
    if not re.search(r"[A-Za-z]", normalized):
        return set()

    match = re.search(r"([A-Za-z]+)$", normalized)
    if not match:
        return {normalized}

    prefix = normalized[:match.start(1)]
    last_word = match.group(1)
    variants = {f"{prefix}{variant}" for variant in _last_word_variants(last_word)}

    if prefix.strip() and len(last_word) >= 4:
        variants.add(f"{prefix}{last_word}y")

    return variants


_CJK_NOISE_RE = re.compile(r"\W+", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def _cjk_search_text(text):
    """Иероглифы ищутся в тексте без пробелов и знаков препинания, как в
    GlossaryRegexService: «《林峰》» и «林·峰» находят «林峰»."""
    return _CJK_NOISE_RE.sub("", normalize_glossary_search_text(text))


def _alpha_search_text(text):
    return _WHITESPACE_RE.sub(" ", normalize_glossary_search_text(text)).casefold()


@functools.lru_cache(maxsize=None)
def _is_word_char(char):
    """Буква, цифра или _ алфавитного письма: вплотную к такому символу слово
    не начинается и не кончается. Иероглифы, кана и хангыль — граница: в
    китайском тексте латиница и числа стоят вплотную к ним без пробела."""
    if char == "_" or char.isalnum() or unicodedata.category(char).startswith("M"):
        return not LanguageDetector.is_cjk_text(char)
    return False


class _TermOccurrenceIndex:
    """Ахо–Корасик по написаниям терминов: за один проход по тексту находит
    все вхождения всех терминов, в том числе вложенные и пересекающиеся.

    Каждый термин считается отдельно, поэтому его счёт не зависит от
    остальных терминов глоссария и не меняется, когда их удаляют."""

    class _Node:
        __slots__ = ("children", "fail", "outputs")

        def __init__(self):
            self.children = {}
            self.fail = None
            self.outputs = ()

    def __init__(self, surface_terms, *, word_boundaries):
        root = self._Node()
        for surface, terms in surface_terms.items():
            node = root
            for char in surface:
                node = node.children.setdefault(char, self._Node())
            # (длина, термины, проверять ли начало, проверять ли конец):
            # граница нужна только там, где у написания край — буква или
            # цифра. «[ARMAMENTARIUM]» и «Dr.» стоят вплотную к чему угодно.
            node.outputs = ((
                len(surface),
                tuple(sorted(terms)),
                word_boundaries and _is_word_char(surface[0]),
                word_boundaries and _is_word_char(surface[-1]),
            ),)

        root.fail = root
        queue = deque()
        for child in root.children.values():
            child.fail = root
            queue.append(child)

        while queue:
            current = queue.popleft()
            for char, child in current.children.items():
                fail_state = current.fail
                while fail_state is not root and char not in fail_state.children:
                    fail_state = fail_state.fail
                candidate = fail_state.children.get(char, root)
                child.fail = candidate if candidate is not child else root
                if child.fail.outputs:
                    child.outputs = child.outputs + child.fail.outputs
                queue.append(child)

        self._root = root

    def count_into(self, text, counts):
        """Прибавляет к counts вхождения терминов в text. Пересекающиеся
        вхождения одного термина считаются один раз, как в str.count."""
        root = self._root
        node = root
        text_length = len(text)
        last_end = {}
        for index, char in enumerate(text):
            while node is not root and char not in node.children:
                node = node.fail
            node = node.children.get(char, root)
            if not node.outputs:
                continue

            end = index + 1
            for length, terms, check_start, check_end in node.outputs:
                start = end - length
                if check_start and start > 0 and _is_word_char(text[start - 1]):
                    continue
                if check_end and end < text_length and _is_word_char(text[end]):
                    continue
                for term in terms:
                    if start >= last_end.get(term, 0):
                        counts[term] += 1
                        last_end[term] = end


class GlossaryTermCounter:
    """Считает вхождения терминов глоссария в тексте главы.

    Иероглифические термины ищутся в упрощённом и традиционном написании по
    тексту без знаков препинания. Остальные — целыми словами без учёта
    регистра, вместе с английским множественным числом и притяжательной
    формой последнего слова («Rune masters», «traditionalist's»)."""

    def __init__(self, glossary_terms):
        cjk_surfaces = defaultdict(set)
        alpha_surfaces = defaultdict(set)
        for term in glossary_terms or []:
            normalized = normalize_glossary_search_text(term).strip()
            if not normalized:
                continue
            if LanguageDetector.is_cjk_text(normalized):
                for variant in get_chinese_script_variants(normalized):
                    surface = _CJK_NOISE_RE.sub("", variant)
                    if surface:
                        cjk_surfaces[surface].add(term)
            else:
                for variant in {normalized} | _alpha_frequency_surfaces(term):
                    surface = _alpha_search_text(variant).strip()
                    if surface:
                        alpha_surfaces[surface].add(term)

        self._cjk_index = (
            _TermOccurrenceIndex(cjk_surfaces, word_boundaries=False) if cjk_surfaces else None
        )
        self._alpha_index = (
            _TermOccurrenceIndex(alpha_surfaces, word_boundaries=True) if alpha_surfaces else None
        )

    def count(self, text):
        counts = Counter()
        if self._cjk_index is not None:
            self._cjk_index.count_into(_cjk_search_text(text), counts)
        if self._alpha_index is not None:
            self._alpha_index.count_into(_alpha_search_text(text), counts)
        return counts


def calculate_term_frequency_payload(
    epub_path,
    glossary_data,
    *,
    progress_callback=None,
    should_continue=None,
):
    glossary_terms = collect_glossary_originals(glossary_data)

    if not _epub_source_exists(epub_path):
        raise FileNotFoundError(f"Файл не найден: {epub_path}")

    if not glossary_terms:
        return build_term_frequency_payload(glossary_terms, epub_path, {})

    term_counter = GlossaryTermCounter(glossary_terms)
    term_occurrences = Counter()
    term_distribution = defaultdict(set)

    with zipfile.ZipFile(epub_path, "r") as archive:
        html_files = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".html", ".xhtml", ".htm"))
            and not name.startswith("__MACOSX")
        ]
        total_files = len(html_files)

        for index, filename in enumerate(html_files):
            if should_continue is not None and not should_continue():
                return None

            if progress_callback is not None:
                progress_callback(index + 1, total_files, os.path.basename(filename))

            try:
                raw_content = archive.read(filename)
                clean_text = _extract_text_from_html(raw_content)
                for term, count in term_counter.count(clean_text).items():
                    term_occurrences[term] += count
                    term_distribution[term].add(filename)
            except Exception as exc:
                print(f"[FreqAnalyzer] Ошибка чтения {filename}: {exc}")
                continue

    return build_term_frequency_payload(
        glossary_terms,
        epub_path,
        {
            term: {"count": count, "files": term_distribution[term]}
            for term, count in term_occurrences.items()
        },
    )


class GlossaryFrequencyWorker(QThread):
    """Фоновый анализатор частоты терминов по EPUB."""

    progress_update = pyqtSignal(int, int, str)
    analysis_finished = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, epub_path, glossary_data, parent=None):
        super().__init__(parent)
        self.epub_path = epub_path
        self.glossary_terms = collect_glossary_originals(glossary_data)
        self._is_running = True

    def run(self):
        try:
            payload = calculate_term_frequency_payload(
                self.epub_path,
                self.glossary_terms,
                progress_callback=self.progress_update.emit,
                should_continue=lambda: self._is_running,
            )
            if payload is not None:
                self.analysis_finished.emit(payload)
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def stop(self):
        self._is_running = False
