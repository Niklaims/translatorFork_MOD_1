"""QA embedding requests publish their token usage like chat calls do.

Embedding providers do not go through BaseApiHandler, so nothing counted what
a quality check spent on embeddings. They now publish through
token_usage.publish_token_usage, the function the nolib bridge replaces.
"""

import asyncio

import pytest

from gemini_translator.api import token_usage
from gemini_translator.qa.embeddings import EmbeddingRequest
from gemini_translator.qa.embeddings.factory import EmbeddingHttpError
from gemini_translator.qa.embeddings.gemini import GeminiEmbeddingProvider
from gemini_translator.qa.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from gemini_translator.utils.helpers import estimate_gemini_tokens


class _Response:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return ""


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def post(self, url, *, headers, json, timeout):
        return self._responses.pop(0)


async def _no_sleep(_delay):
    return None


@pytest.fixture
def published(monkeypatch):
    calls = []
    monkeypatch.setattr(
        token_usage, "publish_token_usage", lambda usage, poster=None: calls.append((usage, poster))
    )
    return calls


def _gemini(responses):
    session = _Session(responses)
    return GeminiEmbeddingProvider("gemini-key", lambda: session, 30, retry_sleep=_no_sleep)


def _openai(responses):
    session = _Session(responses)
    return OpenAICompatibleEmbeddingProvider(
        "https://embeddings.example.test/v1", "secret", lambda: session, 30, retry_sleep=_no_sleep
    )


def _gemini_payload(rows):
    return {"embeddings": [{"values": [1.0, float(index)]} for index in range(rows)]}


def _openai_payload(rows, usage=None):
    payload = {"data": [{"index": index, "embedding": [1.0, float(index)]} for index in range(rows)]}
    if usage is not None:
        payload["usage"] = usage
    return payload


def _request(texts, model):
    return EmbeddingRequest(texts=tuple(texts), language="ru", model=model, dimensions=2)


def test_gemini_embeddings_without_usage_publish_an_estimate_from_the_texts(published):
    texts = ["Первое предложение главы.", "Второе предложение главы."]

    asyncio.run(_gemini([_Response(_gemini_payload(2))]).embed(_request(texts, "models/gemini-embedding-001")))

    [(usage, poster)] = published
    assert usage == {
        "input_tokens": sum(estimate_gemini_tokens(text) for text in texts),
        "output_tokens": 0,
        "total_tokens": sum(estimate_gemini_tokens(text) for text in texts),
        "estimated": True,
        "model_id": "gemini-embedding-001",
        "provider": "gemini",
        "operation": "quality_check",
    }
    assert poster is None


def test_gemini_embeddings_publish_the_prompt_token_count_when_the_response_has_one(published):
    payload = dict(_gemini_payload(1), usageMetadata={"promptTokenCount": 17})

    asyncio.run(_gemini([_Response(payload)]).embed(_request(["Одно предложение."], "gemini-embedding-001")))

    [(usage, _poster)] = published
    assert (usage["input_tokens"], usage["output_tokens"], usage["estimated"]) == (17, 0, False)


def test_gemini_publishes_every_batch_request_it_sends(published):
    texts = [f"Предложение номер {index}." for index in range(150)]

    asyncio.run(
        _gemini([_Response(_gemini_payload(100)), _Response(_gemini_payload(50))]).embed(
            _request(texts, "gemini-embedding-001")
        )
    )

    assert [usage["input_tokens"] for usage, _poster in published] == [
        sum(estimate_gemini_tokens(text) for text in texts[:100]),
        sum(estimate_gemini_tokens(text) for text in texts[100:]),
    ]


def test_openai_compatible_embeddings_publish_the_prompt_tokens_of_the_response(published):
    payload = _openai_payload(2, usage={"prompt_tokens": 9, "total_tokens": 9})

    asyncio.run(_openai([_Response(payload)]).embed(_request(["one", "two"], "embedding-v1")))

    [(usage, poster)] = published
    assert usage == {
        "input_tokens": 9,
        "output_tokens": 0,
        "total_tokens": 9,
        "estimated": False,
        "model_id": "embedding-v1",
        "provider": "openai_compatible",
        "operation": "quality_check",
    }
    assert poster is None


def test_openai_compatible_embeddings_without_usage_publish_an_estimate(published):
    texts = ["one", "two"]

    asyncio.run(_openai([_Response(_openai_payload(2))]).embed(_request(texts, "embedding-v1")))

    [(usage, _poster)] = published
    assert usage["input_tokens"] == sum(estimate_gemini_tokens(text) for text in texts)
    assert usage["estimated"] is True


def test_a_refused_embedding_request_publishes_nothing(published):
    with pytest.raises(EmbeddingHttpError):
        asyncio.run(_openai([_Response({}, status=400)]).embed(_request(["one"], "embedding-v1")))

    assert published == []


def test_a_failing_publication_does_not_fail_the_embedding(monkeypatch):
    def broken(usage, poster=None):
        raise RuntimeError("usage log is gone")

    monkeypatch.setattr(token_usage, "publish_token_usage", broken)

    batch = asyncio.run(_openai([_Response(_openai_payload(1))]).embed(_request(["one"], "embedding-v1")))

    assert batch.vectors.shape == (1, 2)
