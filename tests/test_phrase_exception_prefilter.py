"""Exception phrases must cost nothing on chapters that do not contain them.

The untranslated-word detector ran every exception phrase as its own
case-insensitive regex over every chapter: 116 substitutions per chapter and
more than half of the validation window's CPU time on a 1253-chapter book. A
phrase that cannot occur in the text is now skipped, and nothing else may
change: whatever the sequential substitutions produced, the detector produces.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gemini_translator.ui.dialogs.validation_dialogs.untranslated_detector import (
    WordExceptionMatcher,
)


class _CountingPattern:
    """A compiled phrase pattern that records every substitution it performs."""

    def __init__(self, pattern, calls):
        self._pattern = pattern
        self._calls = calls

    def sub(self, replacement, text):
        self._calls.append(self._pattern.pattern)
        return self._pattern.sub(replacement, text)


def _count_substitutions(matcher):
    calls = []
    matcher._phrase_patterns = [
        (phrase, _CountingPattern(pattern, calls))
        for phrase, pattern in matcher._phrase_patterns
    ]
    return calls


def _sequential(matcher, text):
    """The detector's original behaviour: every phrase pattern, one after another."""
    result = text
    for _phrase, pattern in matcher._phrase_patterns:
        result = pattern.sub(" ", result)
    return result


def test_phrases_absent_from_the_text_run_no_substitution():
    matcher = WordExceptionMatcher({"Harry Potter", "New York", "Hogwarts Express"})
    calls = _count_substitutions(matcher)

    result = matcher.remove_phrase_exceptions("Гарри шёл по Москве. New York был далеко.")

    assert result == "Гарри шёл по Москве.   был далеко."
    assert len(calls) == 1


def test_turkish_dotless_and_dotted_i_still_match_as_the_regex_does():
    matcher = WordExceptionMatcher({"Istanbul Airport"})

    assert matcher.remove_phrase_exceptions("Рейс в ıstanbul aırport задержан") == "Рейс в   задержан"
    assert matcher.remove_phrase_exceptions("Рейс в İSTANBUL AİRPORT задержан") == "Рейс в   задержан"


_PHRASE_LETTERS = "abcdefghijklmnopqrstuvwxyz"
# Characters Python's re treats as equal to an ASCII letter under IGNORECASE
# although str.lower() or str.casefold() disagree: the cases a substring
# shortcut would get wrong first.
_REGEX_EQUIVALENTS = {"i": "İı", "s": "ſ", "k": "K"}
_FILLER = st.sampled_from(
    ["Гарри", "шёл", "по", "Москве", "魔法", "straße", "İnci", "ſo", "Kelvin", "kiss", "—"]
)
_SEPARATORS = st.sampled_from([" ", "  ", ". ", ", ", "\n", "-", ""])

PROPERTY_SETTINGS = settings(
    max_examples=250,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@st.composite
def _cased_like_the_regex_allows(draw, phrase):
    return "".join(
        draw(st.sampled_from([char, char.upper(), *_REGEX_EQUIVALENTS.get(char, "")]))
        for char in phrase
    )


@st.composite
def _chapter_with_exceptions(draw):
    phrases = draw(
        st.lists(
            st.lists(st.text(alphabet=_PHRASE_LETTERS, min_size=1, max_size=5), min_size=2, max_size=3)
            .map(" ".join),
            min_size=1,
            max_size=6,
            unique=True,
        )
    )
    pieces = draw(
        st.lists(
            st.one_of(st.sampled_from(phrases).flatmap(_cased_like_the_regex_allows), _FILLER),
            max_size=12,
        )
    )
    separators = draw(st.lists(_SEPARATORS, min_size=len(pieces), max_size=len(pieces)))
    return set(phrases), "".join(piece + separator for piece, separator in zip(pieces, separators))


@PROPERTY_SETTINGS
@given(_chapter_with_exceptions())
def test_skipping_absent_phrases_never_changes_the_result(case):
    exceptions, text = case
    matcher = WordExceptionMatcher(exceptions)

    assert matcher.remove_phrase_exceptions(text) == _sequential(matcher, text)
