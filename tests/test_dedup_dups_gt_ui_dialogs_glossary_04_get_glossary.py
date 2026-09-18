"""Дедуп dups-gt_ui_dialogs_glossary-04 (get-glossary-duplicate-query).

GlossaryManagerPage.get_glossary и _get_glossary_with_db_ids выполняли один
и тот же SELECT ... ORDER BY sequence, отличаясь только колонкой
`id AS _db_id`. Теперь один метод get_glossary(include_db_id=...), а старое
имя — тонкий алиас (его используют conflict-резолверы и тесты).
"""

from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from gemini_translator.ui.widgets.glossary_widget import GlossaryWidget  # noqa: F401  (разрывает циклический импорт dialogs.glossary <-> widgets)
from gemini_translator.ui.dialogs.glossary import GlossaryManagerPage


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE glossary_editor_state (id INTEGER PRIMARY KEY, sequence INTEGER, "
        "original TEXT, rus TEXT, note TEXT, timestamp TEXT)"
    )
    conn.executemany(
        "INSERT INTO glossary_editor_state (sequence, original, rus, note, timestamp) VALUES (?, ?, ?, ?, ?)",
        [(2, "b", "Б", "", "t2"), (1, "a", "А", "n", "t1")],
    )
    conn.commit()
    return conn


class _PageStub:
    def __init__(self):
        self._conn = _conn()

    def _get_db_conn(self):
        return self._conn


class GetGlossaryTests(unittest.TestCase):
    def test_default_rows_follow_sequence_and_carry_no_db_id(self):
        rows = GlossaryManagerPage.get_glossary(_PageStub())
        self.assertEqual([r["original"] for r in rows], ["a", "b"])
        self.assertEqual(set(rows[0]), {"original", "rus", "note", "timestamp"})

    def test_include_db_id_adds_stable_db_id(self):
        rows = GlossaryManagerPage.get_glossary(_PageStub(), include_db_id=True)
        self.assertEqual([r["_db_id"] for r in rows], [2, 1])
        self.assertEqual(set(rows[0]), {"_db_id", "original", "rus", "note", "timestamp"})

    def test_with_db_ids_alias_routes_through_get_glossary(self):
        stub = _PageStub()
        stub.get_glossary = mock.Mock(wraps=lambda **kw: GlossaryManagerPage.get_glossary(stub, **kw))
        rows = GlossaryManagerPage._get_glossary_with_db_ids(stub)
        stub.get_glossary.assert_called_once_with(include_db_id=True)
        self.assertEqual([r["_db_id"] for r in rows], [2, 1])


if __name__ == "__main__":
    unittest.main()
