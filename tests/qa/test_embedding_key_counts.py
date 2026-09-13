"""The quality window shows how many of a provider's keys can embed, not a list of keys."""

from __future__ import annotations

from gemini_translator.qa.assembly import embedding_key_counts


class _Manager:
    def __init__(self, keys, blocked=()) -> None:
        self.keys = list(keys)
        self.blocked = set(blocked)

    def load_key_statuses(self):
        return [dict(item) for item in self.keys]

    def is_key_limit_active(self, key_info, model_id):
        return (key_info.get("key"), model_id) in self.blocked


def test_working_keys_are_counted_out_of_the_providers_keys():
    manager = _Manager(
        [
            {"provider": "gemini", "key": "g-1"},
            {"provider": "gemini", "key": "g-2"},
            {"provider": "gemini", "key": "g-3"},
            {"provider": "openrouter", "key": "o-1"},
        ],
        blocked={("g-2", "gemini-embedding-001")},
    )

    assert embedding_key_counts(manager, "gemini", "gemini-embedding-001") == (2, 3)


def test_a_limit_on_another_model_does_not_count_against_embeddings():
    manager = _Manager(
        [{"provider": "gemini", "key": "g-1"}, {"provider": "gemini", "key": "g-2"}],
        blocked={("g-1", "gemini-2.5-flash")},
    )

    assert embedding_key_counts(manager, "gemini", "gemini-embedding-001") == (2, 2)


def test_a_key_listed_twice_counts_once():
    manager = _Manager(
        [{"provider": "gemini", "key": "g-1"}, {"provider": "gemini", "key": " g-1 "}]
    )

    assert embedding_key_counts(manager, "gemini", "gemini-embedding-001") == (1, 1)


def test_nothing_to_read_counts_nothing():
    class _Broken:
        def load_key_statuses(self):
            raise RuntimeError("database is locked")

    assert embedding_key_counts(None, "gemini", "gemini-embedding-001") == (0, 0)
    assert embedding_key_counts(_Manager([]), "", "gemini-embedding-001") == (0, 0)
    assert embedding_key_counts(_Broken(), "gemini", "gemini-embedding-001") == (0, 0)
