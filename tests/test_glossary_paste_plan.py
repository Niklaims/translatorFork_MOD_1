"""Вставка списка терминов в имеющийся глоссарий: что добавится, что
заменится и что останется как есть (glossary_tools.plan_glossary_paste),
и как выбранные замены ложатся на глоссарий (apply_glossary_paste)."""
import unittest

from gemini_translator.utils.glossary_tools import (
    apply_glossary_paste,
    plan_glossary_paste,
)


class PlanGlossaryPasteTests(unittest.TestCase):
    def test_unknown_term_is_added_and_identical_one_is_left_alone(self):
        existing = [{"original": "林动", "rus": "Линь Дун", "note": "герой"}]
        pasted = [
            {"original": "林动", "rus": "Линь Дун", "note": "герой"},
            {"original": "武祖", "rus": "Боевой Предок", "note": ""},
        ]

        plan = plan_glossary_paste(existing, pasted)

        self.assertEqual(
            plan.additions,
            [{"original": "武祖", "rus": "Боевой Предок", "note": ""}],
        )
        self.assertEqual(plan.conflicts, [])
        self.assertEqual(plan.unchanged, 1)

    def test_different_translation_is_a_conflict_that_keeps_the_note(self):
        existing = [
            {"original": "青阳镇", "rus": "Цинъян", "note": ""},
            {"original": "林动", "rus": "Линь Дун", "note": "герой"},
        ]
        pasted = [{"original": "林动", "rus": "Лин Дун", "note": ""}]

        plan = plan_glossary_paste(existing, pasted)

        self.assertEqual(len(plan.conflicts), 1)
        conflict = plan.conflicts[0]
        self.assertEqual(conflict.index, 1)
        self.assertEqual(
            conflict.current,
            {"original": "林动", "rus": "Линь Дун", "note": "герой"},
        )
        self.assertEqual(
            conflict.replacement,
            {"original": "林动", "rus": "Лин Дун", "note": "герой"},
        )
        self.assertEqual(plan.additions, [])
        self.assertEqual(plan.unchanged, 0)

    def test_different_note_alone_is_a_conflict(self):
        existing = [{"original": "林动", "rus": "Линь Дун", "note": "герой"}]
        pasted = [{"original": "林动", "rus": "Линь Дун", "note": "главный герой"}]

        plan = plan_glossary_paste(existing, pasted)

        self.assertEqual(
            [conflict.replacement for conflict in plan.conflicts],
            [{"original": "林动", "rus": "Линь Дун", "note": "главный герой"}],
        )

    def test_empty_pasted_fields_never_count_as_a_difference(self):
        existing = [
            {"original": "林动", "rus": "Линь Дун", "note": "герой"},
            {"original": "武祖", "rus": "Боевой Предок", "note": "титул"},
        ]
        pasted = [
            {"original": "林动", "rus": "Линь Дун", "note": ""},
            {"original": "武祖", "rus": "", "note": ""},
        ]

        plan = plan_glossary_paste(existing, pasted)

        self.assertEqual(plan.conflicts, [])
        self.assertEqual(plan.additions, [])
        self.assertEqual(plan.unchanged, 2)

    def test_term_matches_regardless_of_case_and_outer_spaces(self):
        existing = [{"original": "Dragon", "rus": "Дракон", "note": ""}]
        pasted = [{"original": " dragon ", "rus": "Змей", "note": ""}]

        plan = plan_glossary_paste(existing, pasted)

        self.assertEqual(plan.additions, [])
        self.assertEqual(
            [(conflict.index, conflict.replacement) for conflict in plan.conflicts],
            [(0, {"original": "Dragon", "rus": "Змей", "note": ""})],
        )

    def test_values_differing_only_by_outer_spaces_are_unchanged(self):
        existing = [{"original": "Dragon", "rus": "Дракон ", "note": " зверь"}]
        pasted = [{"original": "Dragon", "rus": "Дракон", "note": "зверь"}]

        plan = plan_glossary_paste(existing, pasted)

        self.assertEqual(plan.conflicts, [])
        self.assertEqual(plan.unchanged, 1)

    def test_last_repeat_of_a_term_in_the_paste_wins(self):
        pasted = [
            {"original": "Alpha", "rus": "Первый", "note": ""},
            {"original": "Beta", "rus": "Бета", "note": ""},
            {"original": "alpha", "rus": "Второй", "note": ""},
        ]

        plan = plan_glossary_paste([], pasted)

        self.assertEqual(
            plan.additions,
            [
                {"original": "alpha", "rus": "Второй", "note": ""},
                {"original": "Beta", "rus": "Бета", "note": ""},
            ],
        )

    def test_rows_without_original_are_skipped(self):
        pasted = [
            {"original": "", "rus": "Сирота", "note": "без оригинала"},
            {"original": "   ", "rus": "Пробел", "note": ""},
            {"original": "Alpha", "rus": "Альфа", "note": ""},
        ]

        plan = plan_glossary_paste([], pasted)

        self.assertEqual(plan.additions, [{"original": "Alpha", "rus": "Альфа", "note": ""}])
        self.assertEqual(plan.skipped, 2)

    def test_repeated_existing_term_conflicts_only_with_its_first_entry(self):
        existing = [
            {"original": "A", "rus": "один", "note": ""},
            {"original": "a", "rus": "два", "note": ""},
        ]
        pasted = [{"original": "A", "rus": "три", "note": ""}]

        plan = plan_glossary_paste(existing, pasted)

        self.assertEqual([conflict.index for conflict in plan.conflicts], [0])

    def test_pasted_fields_are_normalised(self):
        pasted = [
            {"original": "Alpha", "translation": "Альфа"},
            {"original": "Beta", "rus": None, "note": None},
            {"original": " Gamma ", "rus": " Гамма ", "note": " буква "},
        ]

        plan = plan_glossary_paste([], pasted)

        self.assertEqual(
            plan.additions,
            [
                {"original": "Alpha", "rus": "Альфа", "note": ""},
                {"original": "Beta", "rus": "", "note": ""},
                {"original": "Gamma", "rus": "Гамма", "note": "буква"},
            ],
        )


class ApplyGlossaryPasteTests(unittest.TestCase):
    def test_accepted_conflicts_replace_in_place_and_additions_go_last(self):
        existing = [
            {"original": "林动", "rus": "Линь Дун", "note": "герой", "timestamp": 100.0},
            {"original": "武祖", "rus": "Боевой Предок", "note": "", "timestamp": 200.0},
        ]
        pasted = [
            {"original": "林动", "rus": "Лин Дун", "note": ""},
            {"original": "武祖", "rus": "Предок Войны", "note": ""},
            {"original": "青阳镇", "rus": "Цинъян", "note": "город"},
        ]
        plan = plan_glossary_paste(existing, pasted)
        accepted = [c for c in plan.conflicts if c.current["original"] == "林动"]

        merged = apply_glossary_paste(existing, plan, accepted)

        self.assertEqual(
            merged,
            [
                {"original": "林动", "rus": "Лин Дун", "note": "герой", "timestamp": 100.0},
                {"original": "武祖", "rus": "Боевой Предок", "note": "", "timestamp": 200.0},
                {"original": "青阳镇", "rus": "Цинъян", "note": "город"},
            ],
        )
        self.assertEqual(existing[0]["rus"], "Линь Дун")


if __name__ == "__main__":
    unittest.main()
