"""Нарезка запроса AI-коррекции глоссария на пакеты.

Один запрос на весь глоссарий упирается в контекст модели (у пользователей
605k токенов против лимита 207k). Полезная нагрузка режется на пакеты, каждый
уходит отдельной задачей, а результаты сливаются в один патч — это уже умеет
`_process_results_from_db`, читающий всю таблицу `glossary_results` разом.

Единица нарезки — смысловая группа (запись контекста, группа конфликта,
паттерн). Группы неделимы: половина конфликта в отдельном запросе бесполезна.
"""

import importlib
import os
import sys
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _import_ai_correction():
    """Импорт ai_correction в обход циклической зависимости widgets/glossary."""
    module_name = "gemini_translator.ui.widgets.glossary_widget"
    previous_module = sys.modules.get(module_name)
    fake_module = types.ModuleType(module_name)
    fake_glossary_widget = type("_FakeGlossaryWidget", (), {})
    fake_module.GlossaryWidget = fake_glossary_widget
    sys.modules[module_name] = fake_module
    try:
        module = importlib.import_module(
            "gemini_translator.ui.dialogs.glossary_dialogs.ai_correction"
        )
    finally:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module

        widgets_package = sys.modules.get("gemini_translator.ui.widgets")
        if widgets_package and getattr(widgets_package, "GlossaryWidget", None) is fake_glossary_widget:
            if previous_module is not None:
                widgets_package.GlossaryWidget = previous_module.GlossaryWidget
            else:
                try:
                    real_module = importlib.import_module(module_name)
                    widgets_package.GlossaryWidget = real_module.GlossaryWidget
                except Exception:
                    delattr(widgets_package, "GlossaryWidget")

    return module


ai_correction = _import_ai_correction()


def _unit(section, *lines):
    return ai_correction.PayloadUnit(section=section, lines=list(lines))


class SplitUnitsIntoBatchesTests(unittest.TestCase):
    """Оценщик токенов в тестах — len(): один символ равен одному токену."""

    def _split(self, units, budget):
        return ai_correction.split_units_into_batches(units, budget, len)

    def test_units_are_packed_until_the_budget_is_reached(self):
        units = [_unit("context", "a" * 10) for _ in range(3)]
        header = len(ai_correction.PAYLOAD_SECTION_HEADERS["context"])

        batches = self._split(units, budget=header + 21)

        self.assertEqual([len(b.units) for b in batches], [2, 1])

    def test_a_unit_larger_than_the_budget_gets_its_own_batch(self):
        units = [_unit("context", "a" * 5), _unit("context", "b" * 500)]

        batches = self._split(units, budget=50)

        self.assertEqual([len(b.units) for b in batches], [1, 1])
        self.assertEqual(batches[1].units[0].lines, ["b" * 500])

    def test_section_header_is_counted_once_per_batch(self):
        # Три единицы по 10 символов и один заголовок влезают в бюджет.
        # Если заголовок посчитать на каждую единицу, пакетов станет больше.
        units = [_unit("context", "a" * 10) for _ in range(3)]
        header = len(ai_correction.PAYLOAD_SECTION_HEADERS["context"])

        batches = self._split(units, budget=header + 32)

        self.assertEqual(len(batches), 1)

    def test_no_unit_is_lost_or_reordered(self):
        units = [
            _unit("context", "ctx"),
            _unit("direct", "one"),
            _unit("direct", "two"),
            _unit("hidden", "hid"),
        ]

        batches = self._split(units, budget=20)

        flattened = [unit for batch in batches for unit in batch.units]
        self.assertEqual(flattened, units)

    def test_empty_input_produces_no_batches(self):
        self.assertEqual(self._split([], budget=100), [])


class RenderPayloadUnitsTests(unittest.TestCase):
    def test_section_header_precedes_its_units(self):
        text = ai_correction.render_payload_units([_unit("direct", '"A": {"rus": "Б"},')])

        self.assertIn("--- DIRECT CONFLICTS ---", text)
        self.assertLess(text.index("DIRECT CONFLICTS"), text.index('"A"'))

    def test_header_is_emitted_once_for_consecutive_units_of_one_section(self):
        text = ai_correction.render_payload_units(
            [_unit("context", "first"), _unit("context", "second")]
        )

        self.assertEqual(text.count("--- GLOSSARY CONTEXT ---"), 1)

    def test_each_batch_repeats_the_header_of_the_sections_it_carries(self):
        units = [_unit("context", "a" * 10) for _ in range(2)]
        header = len(ai_correction.PAYLOAD_SECTION_HEADERS["context"])

        batches = ai_correction.split_units_into_batches(units, header + 11, len)
        rendered = [ai_correction.render_payload_units(batch.units) for batch in batches]

        self.assertEqual(len(rendered), 2)
        for text in rendered:
            self.assertIn("--- GLOSSARY CONTEXT ---", text)

    def test_blank_line_runs_are_collapsed(self):
        text = ai_correction.render_payload_units(
            [_unit("direct", "one", "", "", ""), _unit("direct", "two")]
        )

        self.assertNotIn("\n\n\n", text)



# --- Стенд страницы коррекции --------------------------------------------
#
# PyQt6 запрещает звать методы на объекте, созданном через cls.__new__(cls)
# ("super-class __init__ was never called"), поэтому метод берётся у класса и
# привязывается к обычному объекту через types.MethodType — идиома _FixerHarness.


class _Checkbox:
    def __init__(self, checked=False):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setChecked(self, value):
        self._checked = bool(value)


class _Spin:
    def __init__(self, value=0):
        self._value = value

    def value(self):
        return self._value


class GlossaryManagerPage:
    """Владелец глоссария. Имя класса значимо: страница сверяет его."""

    def __init__(self, glossary, **kwargs):
        self._glossary = glossary
        self.direct_conflicts = kwargs.get("direct_conflicts", {})
        self.reverse_issues = kwargs.get("reverse_issues", {})
        self.overlap_groups = kwargs.get("overlap_groups", {})
        self.inverted_overlaps = kwargs.get("inverted_overlaps", {})
        self.untranslated_residue = kwargs.get("untranslated_residue", {})

    def get_glossary(self):
        return [dict(entry) for entry in self._glossary]


class _PageHarness:
    def __init__(self, owner, **attrs):
        self._owner = owner
        self.__dict__.update(attrs)

    def _get_glossary_owner(self):
        return self._owner

    def __getattr__(self, name):
        attr = getattr(ai_correction.CorrectionSessionPage, name, None)
        if callable(attr):
            bound = types.MethodType(attr, self)
            self.__dict__[name] = bound
            return bound
        raise AttributeError(name)


def make_page(owner, **overrides):
    attrs = {
        "cb_context": _Checkbox(True),
        "cb_notes": _Checkbox(True),
        "cb_direct": _Checkbox(False),
        "cb_reverse": _Checkbox(False),
        "cb_overlaps": _Checkbox(False),
        "cb_untranslated": _Checkbox(False),
        "cb_frequency_filter": _Checkbox(False),
        "cb_hierarchical_patterns": _Checkbox(True),
        "divergence_spinbox": _Spin(30),
        "patterns_included": False,
        "partial_overlaps_included": False,
        "_cached_pattern_results": None,
        "_cached_analysis_results": None,
        "_term_frequency_map": {},
        "adopted_terms_registry": set(),
    }
    attrs.update(overrides)
    return _PageHarness(owner, **attrs)


GLOSSARY = [
    {"original": "Alpha", "rus": "Альфа", "note": "первая"},
    {"original": "Alpha", "rus": "Альфа-два", "note": ""},
    {"original": "Beta", "rus": "Бета", "note": ""},
    {"original": "Gamma", "rus": "Гамма", "note": "третья"},
    {"original": "Delta", "rus": "Дельта", "note": ""},
    {"original": "Epsilon", "rus": "Epsilon", "note": ""},
]

GOLDEN_PAYLOAD = (
    '\n--- GLOSSARY CONTEXT ---\n'
    '\n"Delta": {"rus": "Дельта"},'
    '\n"Epsilon": {"rus": "Epsilon"},'
    '\n\n--- DIRECT CONFLICTS ---\n'
    '\n"Alpha": {"rus": "Альфа", "note": "первая"},'
    '\n"Alpha": {"rus": "Альфа-два"},'
    '\n\n--- REVERSE CONFLICTS ---\n'
    '\n"Beta": {"rus": "Бета"},'
    '\n\n"Gamma": {"rus": "Гамма", "note": "третья"},\n'
)


def _page_with_conflicts(**overrides):
    owner = GlossaryManagerPage(
        GLOSSARY,
        direct_conflicts={"Alpha": {}},
        reverse_issues={"Бета": {"complete": [{"original": "Beta"}, {"original": "Gamma"}]}},
        **{k: v for k, v in overrides.pop("owner", {}).items()},
    )
    attrs = {"cb_direct": _Checkbox(True), "cb_reverse": _Checkbox(True)}
    attrs.update(overrides)
    return make_page(owner, **attrs)


class PayloadIsUnchangedWithoutBatchingTests(unittest.TestCase):
    """Страховка рефакторинга: без пакетов текст запроса обязан остаться прежним."""

    def test_payload_text_matches_the_pre_refactor_output(self):
        page = _page_with_conflicts()

        data, _tokens, _blocks, _ctx, *_rest = page._get_data_and_estimate_tokens()

        self.assertEqual(data, GOLDEN_PAYLOAD)

    def test_blocks_and_context_flag_are_reported_as_before(self):
        page = _page_with_conflicts()

        _data, _tokens, blocks, context_added, *_rest = page._get_data_and_estimate_tokens()

        self.assertEqual(sorted(blocks), ["direct", "reverse"])
        self.assertTrue(context_added)


class PayloadUnitsFromGlossaryTests(unittest.TestCase):
    def test_units_render_back_to_the_very_same_text(self):
        page = _page_with_conflicts()

        bundle = page._get_data_and_estimate_tokens()

        self.assertEqual(ai_correction.render_payload_units(bundle.units), bundle.text)

    def test_context_becomes_one_unit_per_original(self):
        page = _page_with_conflicts()

        bundle = page._get_data_and_estimate_tokens()

        context_units = [u for u in bundle.units if u.section == "context"]
        self.assertEqual(len(context_units), 2)

    def test_a_conflict_group_stays_whole_inside_one_unit(self):
        # У "Alpha" два перевода — обе записи обязаны ехать вместе,
        # иначе модель увидит половину конфликта.
        page = _page_with_conflicts()

        bundle = page._get_data_and_estimate_tokens()

        direct_units = [u for u in bundle.units if u.section == "direct"]
        self.assertEqual(len(direct_units), 1)
        self.assertEqual(
            len([line for line in direct_units[0].lines if "Alpha" in line]), 2
        )

    def test_empty_owner_yields_no_units(self):
        page = make_page(object())

        bundle = page._get_data_and_estimate_tokens()

        self.assertIsNone(bundle.text)
        self.assertEqual(list(bundle.units), [])


class _TaskManager:
    def __init__(self):
        self.pending = None
        self.cleared_queues = 0
        self.cleared_results = 0

    def clear_all_queues(self):
        self.cleared_queues += 1

    def clear_glossary_results(self):
        self.cleared_results += 1

    def add_pending_tasks(self, tasks):
        self.pending = list(tasks)


class _Engine:
    def __init__(self):
        self.task_manager = _TaskManager()


BIG_GLOSSARY = [
    {"original": f"Term{i:03d}", "rus": f"Термин номер {i:03d}", "note": "примечание к термину"}
    for i in range(200)
]


class PrepareTaskContextTests(unittest.TestCase):
    def _page(self, glossary, batching=False, batch_thousands=1):
        owner = GlossaryManagerPage(glossary)
        page = make_page(
            owner,
            cb_batching=_Checkbox(batching),
            batch_size_spinbox=_Spin(batch_thousands),
        )
        page.get_settings = lambda: {"model_config": {"context_length": 10_000_000}}
        page._build_final_prompt = lambda blocks, context_added: "PROMPT"
        payloads = []

        def fake_epub(content, internal_path):
            payloads.append(content)
            return f"mem://batch{len(payloads)}.epub"

        page._create_virtual_epub = fake_epub
        page.engine = _Engine()
        return page, payloads

    def test_without_batching_a_single_task_is_queued(self):
        page, payloads = self._page(BIG_GLOSSARY, batching=False)

        settings = page._prepare_task_context()

        self.assertIsNotNone(settings)
        self.assertEqual(len(page.engine.task_manager.pending), 1)
        self.assertEqual(len(payloads), 1)

    def test_batching_queues_one_task_per_batch(self):
        page, payloads = self._page(BIG_GLOSSARY, batching=True, batch_thousands=1)

        page._prepare_task_context()

        self.assertGreater(len(page.engine.task_manager.pending), 1)
        self.assertEqual(len(payloads), len(page.engine.task_manager.pending))

    def test_every_term_survives_the_batching_exactly_once(self):
        page, payloads = self._page(BIG_GLOSSARY, batching=True, batch_thousands=1)

        page._prepare_task_context()

        for entry in BIG_GLOSSARY:
            hits = sum(payload.count(f'"{entry["original"]}"') for payload in payloads)
            self.assertEqual(hits, 1, f'{entry["original"]} встречается {hits} раз')

    def test_each_batch_stays_within_the_requested_budget(self):
        page, payloads = self._page(BIG_GLOSSARY, batching=True, batch_thousands=1)

        page._prepare_task_context()

        counter = ai_correction.TokenCounter()
        for payload in payloads:
            self.assertLessEqual(counter.estimate_tokens(payload), 1000)

    def test_every_queued_task_is_a_glossary_batch_task(self):
        page, _payloads = self._page(BIG_GLOSSARY, batching=True, batch_thousands=1)

        page._prepare_task_context()

        for task in page.engine.task_manager.pending:
            self.assertEqual(task[0], "glossary_batch_task")
            self.assertEqual(task[2], ("correction_data.txt",))

    def test_queued_batches_use_separate_virtual_files(self):
        page, _payloads = self._page(BIG_GLOSSARY, batching=True, batch_thousands=1)

        page._prepare_task_context()

        paths = [task[1] for task in page.engine.task_manager.pending]
        self.assertEqual(len(set(paths)), len(paths))


def _entry(original):
    """Запись глоссария по оригиналу — устойчивее, чем индекс в списке."""
    return next(e for e in GLOSSARY if e["original"] == original)


def _residue(*entries):
    """Карта остатков в том виде, в каком её отдаёт find_untranslated_residue."""
    by_fragment = {}
    for entry, location in entries:
        fragment = str(entry["rus"] if location == "rus" else entry["note"]).lower()
        by_fragment.setdefault(fragment, {"entries_with_residue": []})
        by_fragment[fragment]["entries_with_residue"].append(
            {"entry": entry, "location": location}
        )
    return by_fragment


class UntranslatedBlockTests(unittest.TestCase):
    def _page(self, *, checked, residue, **overrides):
        owner = GlossaryManagerPage(GLOSSARY, untranslated_residue=residue, **overrides.pop("owner", {}))
        return make_page(owner, cb_untranslated=_Checkbox(checked), **overrides)

    def test_checked_box_sends_the_untranslated_terms(self):
        page = self._page(checked=True, residue=_residue((_entry("Epsilon"), "rus")))

        bundle = page._get_data_and_estimate_tokens()

        self.assertIn("--- UNTRANSLATED ---", bundle.text)
        self.assertEqual(bundle.blocks.get("untranslated"), ["Epsilon"])

    def test_unchecked_box_sends_nothing(self):
        page = self._page(checked=False, residue=_residue((_entry("Epsilon"), "rus")))

        bundle = page._get_data_and_estimate_tokens()

        self.assertNotIn("--- UNTRANSLATED ---", bundle.text)
        self.assertNotIn("untranslated", bundle.blocks)

    def test_residue_only_in_the_note_is_left_alone(self):
        # Латиница в примечании — не непереведённый термин, перевод у него в порядке.
        noted = {"original": "Zeta", "rus": "Зета", "note": "cf. Zeta"}
        page = self._page(checked=True, residue=_residue((noted, "note")))

        bundle = page._get_data_and_estimate_tokens()

        self.assertNotIn("untranslated", bundle.blocks)

    def test_a_term_already_sent_as_a_conflict_is_not_repeated(self):
        owner = GlossaryManagerPage(
            GLOSSARY,
            direct_conflicts={"Epsilon": {}},
            untranslated_residue=_residue((_entry("Epsilon"), "rus")),
        )
        page = make_page(owner, cb_direct=_Checkbox(True), cb_untranslated=_Checkbox(True))

        bundle = page._get_data_and_estimate_tokens()

        self.assertNotIn("untranslated", bundle.blocks)
        # Ключ записи, а не подстрока: у Epsilon перевод совпадает с оригиналом.
        self.assertEqual(bundle.text.count('"Epsilon": {'), 1)

    def test_untranslated_terms_leave_the_context_block(self):
        page = self._page(checked=True, residue=_residue((_entry("Epsilon"), "rus")))

        bundle = page._get_data_and_estimate_tokens()

        context_text = "\n".join(
            line for unit in bundle.units if unit.section == "context" for line in unit.lines
        )
        self.assertNotIn("Epsilon", context_text)

    def test_frequency_filter_also_narrows_the_untranslated_terms(self):
        page = self._page(
            checked=True,
            residue=_residue((_entry("Epsilon"), "rus")),
            cb_frequency_filter=_Checkbox(True),
            _term_frequency_map={"Epsilon": {"count": 1}, "Delta": {"count": 50}},
            freq_min_spinbox=_Spin(10),
            freq_max_spinbox=_Spin(100),
        )

        bundle = page._get_data_and_estimate_tokens()

        self.assertNotIn("untranslated", bundle.blocks)


class _PromptWidget:
    def get_prompt(self):
        return "BASE|{input_format_description}|{example_json}"


class FinalPromptTests(unittest.TestCase):
    """`keys_to_check` сверялся с ключом 'conflicts', а блоки лежат под
    'direct'/'reverse' — описание блока конфликтов не попадало в промпт ни разу,
    хотя сами данные уезжали."""

    def _prompt(self, blocks, context_added=False, notes=True):
        page = make_page(GlossaryManagerPage(GLOSSARY), cb_notes=_Checkbox(notes))
        page.prompt_widget = _PromptWidget()
        return page._build_final_prompt(blocks, context_added)

    def test_direct_conflicts_are_described(self):
        prompt = self._prompt({"direct": ["Alpha"]})

        self.assertIn("DIRECT CONFLICTS", prompt)

    def test_reverse_conflicts_are_described(self):
        prompt = self._prompt({"reverse": ["Beta"]})

        self.assertIn("REVERSE CONFLICTS", prompt)

    def test_conflicts_are_described_only_once_when_both_kinds_are_present(self):
        prompt = self._prompt({"direct": ["Alpha"], "reverse": ["Beta"]})

        self.assertEqual(prompt.count("противоречивыми переводами"), 1)

    def test_untranslated_block_is_described(self):
        prompt = self._prompt({"untranslated": ["Epsilon"]})

        self.assertIn("UNTRANSLATED", prompt)

    def test_a_block_that_was_not_sent_is_not_described(self):
        prompt = self._prompt({"direct": ["Alpha"]})

        self.assertNotIn("UNTRANSLATED", prompt)
        self.assertNotIn("HIDDEN CONFLICTS", prompt)

    def test_blocks_are_numbered_in_order(self):
        prompt = self._prompt({"direct": ["Alpha"]}, context_added=True)

        self.assertIn("1. ", prompt)
        self.assertIn("2. ", prompt)


class TokenLabelTests(unittest.TestCase):
    def _payload(self, units, tokens):
        return ai_correction.PayloadBundle(
            text=ai_correction.render_payload_units(units), tokens=tokens,
            blocks={}, context_added=True, hidden_count=0, neighbors_count=0,
            pattern_count=0, units=units,
        )

    def _page(self, batching=False, batch_thousands=150):
        return make_page(
            GlossaryManagerPage(GLOSSARY),
            cb_batching=_Checkbox(batching),
            batch_size_spinbox=_Spin(batch_thousands),
        )

    def test_without_batching_the_label_keeps_its_old_shape(self):
        page = self._page(batching=False)

        text, _over = page._token_label_text(self._payload([], 81), 207_000)

        self.assertEqual(text, "Запрос: <b>81</b> / 207,000 токенов")

    def test_with_batching_the_label_counts_the_batches(self):
        page = self._page(batching=True, batch_thousands=1)
        units = [_unit("context", "слово " * 200) for _ in range(6)]

        text, _over = page._token_label_text(self._payload(units, 9999), 207_000)

        self.assertIn("пакет", text)
        self.assertRegex(text, r"\d+ пакет")

    def test_a_single_batch_is_spelled_in_the_singular(self):
        page = self._page(batching=True, batch_thousands=150)
        units = [_unit("context", "коротко")]

        text, _over = page._token_label_text(self._payload(units, 12), 207_000)

        self.assertIn("1 пакет ", text)

    def test_a_request_over_the_limit_is_flagged(self):
        page = self._page(batching=False)

        _text, over = page._token_label_text(self._payload([], 605_488), 207_000)

        self.assertTrue(over)

    def test_batches_that_fit_the_limit_are_not_flagged(self):
        page = self._page(batching=True, batch_thousands=1)
        units = [_unit("context", "слово " * 200) for _ in range(6)]

        _text, over = page._token_label_text(self._payload(units, 605_488), 207_000)

        self.assertFalse(over)


class DataTabVisibilityTests(unittest.TestCase):
    """Категория без данных не занимает место в сетке — как уже сделано
    для прямых, обратных конфликтов и наложений."""

    def _page(self, residue):
        owner = GlossaryManagerPage(GLOSSARY, untranslated_residue=residue)
        return make_page(owner, cb_untranslated=_Checkbox(True))

    def test_untranslated_box_shows_up_when_residue_was_found(self):
        page = self._page(_residue((_entry("Epsilon"), "rus")))

        shown = page._data_checkboxes_to_show()

        self.assertIn(page.cb_untranslated, shown)

    def test_without_residue_the_box_is_hidden_and_unchecked(self):
        page = self._page({})

        shown = page._data_checkboxes_to_show()

        self.assertNotIn(page.cb_untranslated, shown)
        self.assertFalse(page.cb_untranslated.isChecked())

    def test_context_and_notes_are_always_offered(self):
        page = self._page({})

        shown = page._data_checkboxes_to_show()

        self.assertIn(page.cb_context, shown)
        self.assertIn(page.cb_notes, shown)


class _MutableSpin(_Spin):
    def setValue(self, value):
        self._value = value

    def setEnabled(self, value):
        self.enabled = bool(value)


class BatchBudgetDefaultTests(unittest.TestCase):
    def _page(self, context_length, batching=False):
        page = make_page(
            GlossaryManagerPage(GLOSSARY),
            cb_batching=_Checkbox(batching),
            batch_size_spinbox=_MutableSpin(1),
        )
        page.get_settings = lambda: {"model_config": {"context_length": context_length}}
        page.update_token_estimation = lambda: None
        return page

    def test_default_budget_follows_the_model_safe_limit(self):
        page = self._page(230_000)

        # 230 000 × 0.9 = 207 000 — то же число, что показывает метка.
        self.assertEqual(page._default_batch_thousands(), 207)

    def test_a_tiny_context_still_gives_at_least_one_thousand(self):
        page = self._page(500)

        self.assertEqual(page._default_batch_thousands(), 1)

    def test_enabling_batching_turns_the_spinbox_on(self):
        page = self._page(230_000, batching=True)

        page._on_batching_toggled()

        self.assertTrue(page.batch_size_spinbox.enabled)

    def test_disabling_batching_turns_the_spinbox_off(self):
        page = self._page(230_000, batching=False)

        page._on_batching_toggled()

        self.assertFalse(page.batch_size_spinbox.enabled)


class RealWidgetsSmokeTests(unittest.TestCase):
    """Настоящие виджеты, а не заглушки: проверяем, что новая группа строится
    и что перекомпоновка сетки не спотыкается о добавленную категорию."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_batching_group_builds_with_real_widgets(self):
        from PyQt6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QWidget
        from gemini_translator.ui.widgets.common_widgets import NoScrollSpinBox

        host = QWidget()
        group = QGroupBox("Пакеты", host)
        layout = QHBoxLayout(group)
        checkbox = QCheckBox("Разбивать запрос на пакеты")
        spinbox = NoScrollSpinBox(host)
        spinbox.setRange(1, 2000)
        spinbox.setSuffix(" тыс.")
        spinbox.setEnabled(False)
        layout.addWidget(checkbox)
        layout.addWidget(QLabel("не больше"))
        layout.addWidget(spinbox)

        spinbox.setValue(207)
        self.assertEqual(spinbox.value(), 207)
        self.assertEqual(spinbox.text(), "207 тыс.")

    def test_repack_places_every_visible_category_in_the_grid(self):
        from PyQt6.QtWidgets import QCheckBox, QGridLayout, QWidget

        host = QWidget()
        grid = QGridLayout(host)
        owner = GlossaryManagerPage(
            GLOSSARY,
            direct_conflicts={"Alpha": {}},
            untranslated_residue=_residue((_entry("Epsilon"), "rus")),
        )
        page = make_page(
            owner,
            data_grid_layout=grid,
            cb_context=QCheckBox("Весь глоссарий"),
            cb_notes=QCheckBox("Примечания"),
            cb_direct=QCheckBox("Прямые"),
            cb_reverse=QCheckBox("Обратные"),
            cb_overlaps=QCheckBox("Наложения"),
            cb_untranslated=QCheckBox("Непереведённые остатки"),
        )

        page._repack_data_tab_layout()

        placed = {
            grid.itemAt(i).widget().text()
            for i in range(grid.count())
            if grid.itemAt(i).widget()
        }
        self.assertIn("Непереведённые остатки", placed)
        self.assertIn("Прямые", placed)
        self.assertNotIn("Обратные", placed)


class OversizeWarningTests(unittest.TestCase):
    """Совет в предупреждении должен отвечать настоящей причине, а не
    предлагать включить то, что уже включено."""

    def _page(self, batching, batch_thousands=207):
        return make_page(
            GlossaryManagerPage(GLOSSARY),
            cb_batching=_Checkbox(batching),
            batch_size_spinbox=_Spin(batch_thousands),
        )

    def test_without_batching_it_suggests_turning_batching_on(self):
        page = self._page(batching=False)

        _headline, details = page._oversize_warning(
            limit=207_000, batch_count=1, oversized_count=1, payload_tokens=605_488
        )

        self.assertIn("Разбивать запрос на пакеты", details)

    def test_a_budget_above_the_model_limit_is_named_as_the_cause(self):
        page = self._page(batching=True, batch_thousands=500)

        _headline, details = page._oversize_warning(
            limit=207_000, batch_count=2, oversized_count=2, payload_tokens=605_488
        )

        self.assertIn("Поставьте не больше 207 тыс.", details)
        self.assertNotIn("Разбивать запрос на пакеты", details)

    def test_an_indivisible_group_is_explained_as_such(self):
        page = self._page(batching=True, batch_thousands=207)

        _headline, details = page._oversize_warning(
            limit=207_000, batch_count=5, oversized_count=1, payload_tokens=605_488
        )

        self.assertIn("неделимая группа", details)
        self.assertNotIn("Разбивать запрос на пакеты", details)

    def test_the_headline_counts_the_batches_that_do_not_fit(self):
        page = self._page(batching=True)

        headline, _details = page._oversize_warning(
            limit=207_000, batch_count=5, oversized_count=2, payload_tokens=605_488
        )

        self.assertIn("Пакетов: 5", headline)
        self.assertIn("из них 2", headline)


class InterruptedSessionTests(unittest.TestCase):
    """Пакетов несколько, и обрыв на последнем не повод выбрасывать правки,
    которые уже приехали из предыдущих."""

    def test_a_cancelled_session_is_recognised(self):
        self.assertTrue(ai_correction.session_was_interrupted("Отменено пользователем"))

    def test_an_error_session_is_recognised(self):
        self.assertTrue(ai_correction.session_was_interrupted("Ошибка сети"))

    def test_exhausted_keys_count_as_an_interruption(self):
        self.assertTrue(ai_correction.session_was_interrupted("Ключи исчерпаны"))

    def test_a_clean_finish_is_not_an_interruption(self):
        self.assertFalse(ai_correction.session_was_interrupted("Сессия успешно завершена"))

    def test_an_empty_reason_is_not_an_interruption(self):
        self.assertFalse(ai_correction.session_was_interrupted(""))
        self.assertFalse(ai_correction.session_was_interrupted(None))

    def test_the_notice_names_how_many_terms_survived(self):
        notice = ai_correction.partial_results_notice(3)

        self.assertIn("3", notice)
        self.assertIn("термина", notice)

    def test_the_notice_agrees_with_a_single_term(self):
        self.assertIn("1 термин ", ai_correction.partial_results_notice(1))


if __name__ == "__main__":
    unittest.main()
