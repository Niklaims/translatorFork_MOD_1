"""What a reference-free quality estimate may look at, and what it may decide."""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from gemini_translator.qa.estimators.base import (
    QualityEstimate,
    QualityEstimateError,
    QualityEstimateRequest,
    SourceTranslationWindow,
    length_weighted_mean,
    percentile_score,
)
from gemini_translator.qa.estimators.cometkiwi_client import (
    SCHEMA_VERSION,
    CometKiwiEstimator,
    CometKiwiRunnerConfig,
)


class _FakeRunner:
    """Stand in for the separate process: record the request, answer as told."""

    def __init__(self, scores=(0.81, 0.63), **overrides) -> None:
        self.scores = scores
        self.overrides = overrides
        self.requests: list[dict] = []
        self.starts = 0

    async def __call__(self, command, payload, *, timeout, cancellation=None):
        self.starts += 1
        request = json.loads(payload)
        self.requests.append(request)
        answer = {
            "schema_version": SCHEMA_VERSION,
            "request_id": request["request_id"],
            "model": request["model"],
            "device": request["device"],
            "scores": list(self.scores),
        }
        answer.update(self.overrides)
        return json.dumps(answer)


def _config(tmp_path, **overrides) -> CometKiwiRunnerConfig:
    runner = tmp_path / "runner.py"
    runner.write_text("print()", encoding="utf-8")
    weights = tmp_path / "weights"
    weights.mkdir(exist_ok=True)
    values = {
        "runner_path": str(runner),
        "model_dir": str(weights),
        "model": "wmt22-cometkiwi-da",
        "device": "cpu",
    }
    values.update(overrides)
    return CometKiwiRunnerConfig(**values)


def _estimator(tmp_path, runner=None, **overrides) -> CometKiwiEstimator:
    return CometKiwiEstimator(
        _config(tmp_path, **overrides.pop("config", {})),
        enabled=overrides.pop("enabled", True),
        license_accepted=overrides.pop("license_accepted", True),
        run_process=runner or _FakeRunner(),
    )


def _request(*pairs) -> QualityEstimateRequest:
    return QualityEstimateRequest(
        chapter_id="chapter-1",
        windows=tuple(
            SourceTranslationWindow(
                window_id=f"gap-{index:020x}",
                source=source,
                translation=translation,
                visible_chars=sum(
                    1 for character in translation if not character.isspace()
                ),
            )
            for index, (source, translation) in enumerate(pairs)
        ),
        source_language="zh",
        target_language="ru",
    )


def test_the_estimator_sends_only_source_and_translation(tmp_path):
    """A reference would turn this into a different metric that we cannot compute."""
    runner = _FakeRunner()
    estimator = _estimator(tmp_path, runner)

    result = asyncio.run(
        estimator.estimate(
            _request(("原文一", "Первый перевод"), ("原文二", "Второй перевод")),
            None,
        )
    )

    payload = runner.requests[0]
    assert set(payload["segments"][0]) == {"source", "translation"}
    assert "reference" not in payload["segments"][0]
    assert result.window_scores == (0.81, 0.63)
    assert result.status == "completed"
    assert not hasattr(result, "auto_fix_allowed")


def test_the_chapter_score_is_weighted_by_the_text_each_window_covers(tmp_path):
    """A one-line window must not outvote a paragraph."""
    runner = _FakeRunner(scores=(1.0, 0.0))
    estimator = _estimator(tmp_path, runner)
    request = _request(("原文一", "к"), ("原文二", "а" * 99))

    result = asyncio.run(estimator.estimate(request, None))

    assert result.chapter_score == pytest.approx(
        length_weighted_mean((1.0, 0.0), (1, 99))
    )
    assert result.minimum_score == 0.0
    assert result.p10_score == 0.0


def test_equal_scores_aggregate_to_the_same_answer_every_time(tmp_path):
    """A score that moves between runs would make the evidence unciteable."""
    estimator = _estimator(tmp_path, _FakeRunner(scores=(0.5, 0.5, 0.5)))
    request = _request(("一", "один"), ("二", "два"), ("三", "три"))

    first = asyncio.run(estimator.estimate(request, None))
    second = asyncio.run(estimator.estimate(request, None))

    assert first.window_scores == second.window_scores
    assert first.chapter_score == second.chapter_score == pytest.approx(0.5)
    assert first.p10_score == second.p10_score == 0.5


@pytest.mark.parametrize(
    "scores",
    [
        [float("nan"), 0.5],
        [float("inf"), 0.5],
        [0.5],
        [0.5, 0.5, 0.5],
        ["0.5", 0.5],
        [1.5, 0.5],
    ],
)
def test_an_unusable_score_list_is_refused_without_a_score(tmp_path, scores):
    """A NaN or a miscounted batch must not become a chapter's quality number."""
    estimator = _estimator(tmp_path, _FakeRunner(scores=scores))

    result = asyncio.run(
        estimator.estimate(_request(("一", "один"), ("二", "два")), None)
    )

    assert result.status == "unavailable"
    assert result.chapter_score is None
    assert result.window_scores == ()


def test_a_disabled_or_unlicensed_estimator_never_starts_the_process(tmp_path):
    """Neither an unchecked box nor an unread licence may spend the user's machine."""
    off = _FakeRunner()
    unlicensed = _FakeRunner()

    disabled_result = asyncio.run(
        _estimator(tmp_path, off, enabled=False).estimate(
            _request(("一", "один")), None
        )
    )
    unlicensed_result = asyncio.run(
        _estimator(tmp_path, unlicensed, license_accepted=False).estimate(
            _request(("一", "один")), None
        )
    )

    assert (disabled_result.status, off.starts) == ("disabled", 0)
    assert (unlicensed_result.status, unlicensed.starts) == ("disabled", 0)


def test_an_unconfigured_runner_or_model_reports_what_is_missing(tmp_path):
    """"Unavailable" without a reason is indistinguishable from a silent failure."""
    runner = _FakeRunner()
    missing_model = CometKiwiEstimator(
        _config(tmp_path, model=""),
        license_accepted=True,
        run_process=runner,
    )
    missing_runner = CometKiwiEstimator(
        _config(tmp_path, runner_path=str(tmp_path / "nope.py")),
        license_accepted=True,
        run_process=runner,
    )

    first = asyncio.run(missing_model.estimate(_request(("一", "один")), None))
    second = asyncio.run(missing_runner.estimate(_request(("一", "один")), None))

    assert first.metadata["reason"] == "model_missing"
    assert second.metadata["reason"] == "runner_not_found"
    assert runner.starts == 0


def test_an_estimate_never_carries_a_score_it_did_not_measure():
    """The three non-completed states are the only ones allowed to be empty."""
    with pytest.raises(QualityEstimateError):
        QualityEstimate(
            estimator="cometkiwi",
            model="m",
            window_scores=(0.5,),
            status="unavailable",
        )
    with pytest.raises(QualityEstimateError):
        QualityEstimate(estimator="cometkiwi", model="m", status="completed")


def test_a_percentile_of_one_score_is_that_score():
    """p10 must be defined for a chapter of a single passage."""
    assert percentile_score((0.42,), 0.10) == 0.42
    assert percentile_score((0.9, 0.1, 0.5), 0.10) == 0.1
    assert not math.isnan(percentile_score((0.9, 0.1), 1.0))


# --- who is allowed to start the process ------------------------------------


def _verified_candidate(decision: str):
    """A minimal verified candidate, shaped exactly as the cascade produces one."""
    import hashlib

    from gemini_translator.qa.foreign_text_filter import ForeignTextFilter
    from gemini_translator.qa.llm.schemas import OmissionVerdict
    from gemini_translator.qa.models import (
        AlignmentSpan,
        CandidateContext,
        GapCandidate,
        VerifiedCandidate,
    )

    candidate_id = "gap-" + hashlib.sha256(b"window").hexdigest()[:20]
    left = AlignmentSpan(("s0",), ("t0",), 0.95, "1:1")
    right = AlignmentSpan(("s2",), ("t1",), 0.95, "1:1")
    candidate = GapCandidate(
        candidate_id, "source", ("s1",), (), left, right, True, ("missing_in_target",)
    )
    context = CandidateContext(
        candidate_id=candidate_id,
        source_text="原文二",
        target_text="",
        source_before="原文一",
        source_after="原文三",
        target_before="Первый перевод",
        target_after="Третий перевод",
        source_language="zh",
        target_language="ru",
        candidate_language="zh",
    )
    return VerifiedCandidate(
        candidate=candidate,
        context=context,
        verdict=OmissionVerdict(
            decision=decision,
            confidence=0.9,
            source_unit_ids=("s1",),
            missing_facts=("Потеряно.",) if decision == "missing_content" else (),
            explanation="Проверка.",
        ),
        foreign_text_decision=ForeignTextFilter().classify(candidate, context),
        eligible_for_repair=decision == "missing_content",
        status="verified",
    )


def _chapter_result(*verified):
    from gemini_translator.qa.models import RiskLevel
    from gemini_translator.qa.service import ChapterQaResult

    return ChapterQaResult(
        chapter_id="chapter-1",
        risk_level=RiskLevel.LOW if not verified else RiskLevel.MEDIUM,
        may_continue_translation=True,
        coverage_mode="semantic_alignment",
        verified=tuple(verified),
    )


def _coordinator_with(estimator, result):
    from gemini_translator.core.chapter_qa_coordinator import (
        ChapterQaCoordinator,
        TranslationReadyEvent,
    )

    class _Service:
        attached: list = []

        async def check_chapter(self, request, options, cancellation):
            return result

        def attach_quality_estimate(self, chapter_result, estimate):
            self.attached.append(estimate)
            return chapter_result

        def attach_suggestion_scores(self, chapter_id, scores):
            self.scored.append((chapter_id, dict(scores)))
            return len(scores)

    service = _Service()
    service.attached = []
    service.scored = []
    coordinator = ChapterQaCoordinator(
        service=service,
        task_manager=None,
        request_builder=lambda event: event.chapter_id,
        quality_estimator=estimator,
    )
    event = TranslationReadyEvent(
        task_id="task-1",
        chapter_id="chapter-1",
        source_path="OEBPS/chapter-1",
        translated_path="/tmp/chapter-1",
        source_language="zh",
        target_language="ru",
    )
    return coordinator, service, event


class _CountingEstimator:
    def __init__(self) -> None:
        self.starts = 0
        self.requests = []

    async def estimate(self, request, cancellation=None):
        self.starts += 1
        self.requests.append(request)
        from gemini_translator.qa.estimators.base import aggregate

        return aggregate("cometkiwi", "wmt22-cometkiwi-da", request, (0.7,) * len(request.windows))


def _windowed_result(count: int):
    """A checked chapter whose completeness check aligned ``count`` passages."""
    from gemini_translator.qa.models import RiskLevel
    from gemini_translator.qa.service import ChapterQaResult

    return ChapterQaResult(
        chapter_id="chapter-1",
        risk_level=RiskLevel.LOW,
        may_continue_translation=True,
        coverage_mode="semantic_alignment",
        quality_windows=tuple(
            SourceTranslationWindow(
                window_id=f"span-{index}",
                source=f"原文{index}",
                translation=f"Перевод {index}",
                visible_chars=8,
            )
            for index in range(count)
        ),
    )


def _run_check(coordinator, event):
    from gemini_translator.qa.service import QaOptions

    return asyncio.run(coordinator._check_one(event, QaOptions()))


def test_a_clean_chapter_is_scored_over_every_aligned_passage():
    """Оценка шла только по спорным местам, и на чистой главе CometKiwi молчал."""
    estimator = _CountingEstimator()
    coordinator, service, event = _coordinator_with(estimator, _windowed_result(3))

    _run_check(coordinator, event)

    assert estimator.starts == 1
    assert [window.window_id for window in estimator.requests[0].windows] == [
        "span-0",
        "span-1",
        "span-2",
    ]
    assert service.attached[0].status == "completed"


def test_a_chapter_with_nothing_aligned_starts_nothing():
    """Без проверки полноты окон нет, и ПК не получает пустых запросов."""
    estimator = _CountingEstimator()
    coordinator, service, event = _coordinator_with(
        estimator, _chapter_result(_verified_candidate("ambiguous"))
    )

    _run_check(coordinator, event)

    assert estimator.starts == 0
    assert service.attached == []


def test_a_long_chapter_is_scored_in_requests_the_server_accepts():
    """Сервер на ПК принимает до 512 фрагментов: длинная глава идёт частями, а оценка у неё одна."""
    estimator = _CountingEstimator()
    coordinator, service, event = _coordinator_with(estimator, _windowed_result(1100))

    _run_check(coordinator, event)

    assert [len(request.windows) for request in estimator.requests] == [512, 512, 76]
    assert len(service.attached) == 1
    assert len(service.attached[0].window_scores) == 1100
    assert service.attached[0].status == "completed"


def test_a_long_chapter_whose_part_fails_gets_no_score_but_keeps_the_reason():
    """Оценка по части фрагментов выглядела бы оценкой всей главы."""
    from gemini_translator.qa.estimators.base import unavailable

    class _FailsSecondPart(_CountingEstimator):
        async def estimate(self, request, cancellation=None):
            if self.starts == 1:
                self.starts += 1
                self.requests.append(request)
                return unavailable("cometkiwi", "wmt22-cometkiwi-da", "timeout")
            return await super().estimate(request, cancellation)

    estimator = _FailsSecondPart()
    coordinator, service, event = _coordinator_with(estimator, _windowed_result(1100))

    _run_check(coordinator, event)

    assert [len(request.windows) for request in estimator.requests] == [512, 512]
    assert len(service.attached) == 1
    assert service.attached[0].status == "unavailable"
    assert service.attached[0].metadata["reason"] == "timeout"


def test_a_scored_chapter_lets_go_of_its_text():
    """Проход держит результаты всех глав до конца, а окна несут весь текст главы."""
    estimator = _CountingEstimator()
    coordinator, _service, event = _coordinator_with(estimator, _windowed_result(3))

    result = _run_check(coordinator, event)

    assert estimator.starts == 1
    assert result.quality_windows == ()


def _fix_windows(*suggestion_ids):
    from gemini_translator.qa.service import SuggestionWindows

    return tuple(
        SuggestionWindows(
            suggestion_id=suggestion_id,
            before=SourceTranslationWindow(f"{suggestion_id}:before", "原文", "Было так.", 8),
            after=SourceTranslationWindow(f"{suggestion_id}:after", "原文", "Стало так.", 9),
        )
        for suggestion_id in suggestion_ids
    )


class _ScoresByWindow:
    """Answer each window with the score its id asks for, as a runner scores each segment."""

    def __init__(self, score_for) -> None:
        self.score_for = score_for
        self.requests = []

    async def estimate(self, request, cancellation=None):
        from gemini_translator.qa.estimators.base import aggregate

        self.requests.append(request)
        return aggregate(
            "cometkiwi",
            "wmt22-cometkiwi-da",
            request,
            tuple(self.score_for(window.window_id) for window in request.windows),
        )


def _fix_score(before: float, after: float, chapter: float = 0.6):
    def score_for(window_id: str) -> float:
        if window_id.endswith(":before"):
            return before
        if window_id.endswith(":after"):
            return after
        return chapter

    return score_for


def test_refused_fixes_ride_with_the_chapter_but_stay_out_of_its_score():
    """Окна правок уходят тем же запросом, но в оценку главы не входят."""
    from dataclasses import replace

    estimator = _ScoresByWindow(_fix_score(0.2, 0.9))
    result = replace(_windowed_result(2), suggestion_windows=_fix_windows("sg-1"))
    coordinator, service, event = _coordinator_with(estimator, result)

    checked = _run_check(coordinator, event)

    assert [len(request.windows) for request in estimator.requests] == [4]
    assert service.attached[0].chapter_score == pytest.approx(0.6)
    assert service.scored == [("chapter-1", {"sg-1": (0.2, 0.9)})]
    assert checked.suggestion_windows == ()


def test_fixes_are_scored_without_the_completeness_check():
    """Без проверки полноты окон главы нет, но у правки есть свой абзац и оригинал."""
    from dataclasses import replace

    estimator = _ScoresByWindow(_fix_score(0.4, 0.7))
    result = replace(_chapter_result(), suggestion_windows=_fix_windows("sg-1", "sg-2"))
    coordinator, service, event = _coordinator_with(estimator, result)

    checked = _run_check(coordinator, event)

    assert [len(request.windows) for request in estimator.requests] == [4]
    assert service.attached == []
    assert service.scored == [("chapter-1", {"sg-1": (0.4, 0.7), "sg-2": (0.4, 0.7)})]
    assert checked.suggestion_windows == ()


def test_a_failed_estimate_leaves_the_fixes_without_scores():
    from dataclasses import replace

    from gemini_translator.qa.estimators.base import unavailable

    class _Unreachable:
        async def estimate(self, request, cancellation=None):
            return unavailable("cometkiwi", "wmt22-cometkiwi-da", "endpoint_unreachable")

    result = replace(_windowed_result(2), suggestion_windows=_fix_windows("sg-1"))
    coordinator, service, event = _coordinator_with(_Unreachable(), result)

    _run_check(coordinator, event)

    assert service.attached[0].metadata["reason"] == "endpoint_unreachable"
    assert service.scored == []


def test_an_estimator_failure_never_breaks_the_chapter_check():
    """QA is optional twice over: the estimate may fail and the check still stands."""

    class _Broken:
        starts = 0

        async def estimate(self, request, cancellation=None):
            raise RuntimeError("runner exploded")

    coordinator, service, event = _coordinator_with(_Broken(), _windowed_result(2))

    result = asyncio.run(coordinator._check_one(event, __import__(
        "gemini_translator.qa.service", fromlist=["QaOptions"]
    ).QaOptions()))

    assert result is not None
    assert service.attached == []


def test_the_application_never_imports_torch_or_comet_to_run_qa():
    """The whole point of a separate runner is that the app stays light."""
    import subprocess
    import sys

    probe = (
        "import sys\n"
        "class _Blocker:\n"
        "    def find_module(self, name, path=None):\n"
        "        if name.split('.')[0] in {'torch', 'comet', 'pytorch_lightning'}:\n"
        "            raise AssertionError('QA imported ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocker())\n"
        "import gemini_translator.qa.estimators as estimators\n"
        "import gemini_translator.qa.estimators.cometkiwi_client as client\n"
        "import gemini_translator.qa.estimators.cometkiwi_model_manager as manager\n"
        "import gemini_translator.core.chapter_qa_coordinator as coordinator\n"
        "assert estimators and client and manager and coordinator\n"
        "print('clean')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    assert completed.stdout.strip().endswith("clean")
