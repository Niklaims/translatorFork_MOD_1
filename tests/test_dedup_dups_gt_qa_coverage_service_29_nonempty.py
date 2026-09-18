"""Дедуп dups-gt_qa_coverage_service-29 (qa-nonempty-string-check-reinvented), хвост.

Из пяти копий проверки «непустая строка» после предыдущих фаз без
канонического qa/_common.validate_nonempty_string оставались две:
estimators/base.py::_nonempty и llm/schemas.py::_nonempty_string. Здесь
закрыта первая (schemas.py правится пользователем, не трогаем). Все семь
вызовов _nonempty в estimators/base.py используют её как утверждение и
результат не читают, так что возврат stripped-значения из канонической
функции наблюдаемого поведения не меняет; тип исключения слоя сохранён.
"""

from __future__ import annotations

import unittest
from unittest import mock

import gemini_translator.qa.estimators.base as est_base
from gemini_translator.qa.estimators.base import QualityEstimateError, _nonempty


class NonemptyDelegatesToCanonicalValidatorTests(unittest.TestCase):
    def test_routes_through_qa_common_validator(self):
        with mock.patch.object(est_base, "_validate_nonempty_string", return_value="ok") as spy:
            self.assertEqual(_nonempty("  ok ", "field"), "ok")
        spy.assert_called_once_with("  ok ", "field")

    def test_layer_exception_and_message_are_preserved(self):
        with self.assertRaises(QualityEstimateError) as ctx:
            _nonempty("   ", "chapter_id")
        self.assertEqual(str(ctx.exception), "chapter_id must be a nonempty string")
        self.assertIsInstance(ctx.exception.__cause__, ValueError)

    def test_non_string_is_rejected(self):
        with self.assertRaises(QualityEstimateError):
            _nonempty(12, "source")


if __name__ == "__main__":
    unittest.main()
