# -*- coding: utf-8 -*-
"""Регресс для ui-dialogs-validation/runtime/8-ai-repair-whole-book-main-thre
и для замечаний код-ревью группы ui_dialogs_validation_c к первой версии
этого исправления.

_repair_ai_artifacts_for_selection при пустом выделении берёт ВСЕ видимые
строки таблицы и синхронно на GUI-потоке обрабатывает каждую: без прогресса,
без возможности отмены, и при каждом промахе ограниченного LRU-кэша
(ContentLru, 24 главы) заново открывает zipfile.ZipFile(original_epub_path) —
на книге в сотни глав это десятки/сотни повторных открытий одного и того же
архива и интерфейс "не отвечает" на заметное время.

Тест привязывает НАСТОЯЩИЕ тела методов TranslationValidatorPage
(_repair_ai_artifacts_for_selection, _get_ai_repair_target_rows,
_ensure_row_original_html_loaded, _ensure_row_translated_html_loaded,
_get_ai_repair_protected_terms, _push_ai_repair_review_page) к минимальному
объекту с реальным QTableWidget (offscreen Qt) и настоящим временным .epub
(zip)-архивом — без сети и без реальных настроек пользователя.

Проверяем алгоритмические свойства (не секунды):
1. На проход по многим строкам, промахивающим кэш, архив оригинала
   открывается ОДИН раз, а не по разу на строку.
2. Отмена через прогресс-диалог останавливает проход раньше конца — не все
   строки успевают обработаться.

Код-ревью (needs_work) на первую версию этого исправления указал три minor-
дефекта, для которых ниже добавлены отдельные регресс-тесты:

- проход не открывает архив вовсе, если ни одна строка не промахивает кэш
  (test_batch_repair_does_not_open_original_zip_when_no_row_misses_cache) —
  раньше ZipFile открывался безусловно в начале ЛЮБОГО прохода;
- прогресс-диалог явно закрывается и уничтожается после прохода
  (test_batch_repair_closes_and_deletes_progress_dialog_when_done) — раньше
  он только скрывался (autoReset/autoClose), накапливаясь на долгоживущей
  странице валидатора;
- отмена честно отражена в тексте итогового сообщения пользователю — и в
  ветке "нет изменений" (test_batch_repair_reports_cancellation_when_no_changes_found),
  и в сообщении страницы ревью после отмены с частичными кандидатами
  (test_push_ai_repair_review_page_notes_cancellation_in_completion_message) —
  раньше пользователь не мог узнать, что показана лишь часть глав.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import zipfile
from unittest.mock import patch

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from gemini_translator.ui.dialogs.validation import TranslationValidatorPage as P
from gemini_translator.ui.dialogs.validation_dialogs.content_lru import ContentLru
from gemini_translator.ui.shell import ShellPage


_APP = QApplication.instance() or QApplication([])


def _make_app():
    # Держим ссылку на QApplication на уровне модуля: без неё singleton
    # уничтожается сборщиком мусора сразу после возврата из функции.
    return _APP


class _Harness(QWidget):
    """Минимальный объект с реальными телами методов автоправки.

    Наследует QWidget (не полный TranslationValidatorPage), потому что
    _repair_ai_artifacts_for_selection передаёт ``self`` как parent в
    QProgressDialog — конструктору нужен настоящий QWidget, а не
    произвольный объект.
    """

    _repair_ai_artifacts_for_selection = P._repair_ai_artifacts_for_selection
    _get_ai_repair_target_rows = P._get_ai_repair_target_rows
    _ensure_row_original_html_loaded = P._ensure_row_original_html_loaded
    _ensure_row_translated_html_loaded = P._ensure_row_translated_html_loaded

    def __init__(self, n, epub_path):
        super().__init__()
        self.original_epub_path = epub_path
        # LRU намеренно маленький — на n строк почти каждая пройдёт мимо
        # кэша и обычная (не батчевая) реализация открыла бы архив заново
        # на каждую такую строку.
        self.original_content_cache = ContentLru(max_entries=2)
        self.translated_content_cache = ContentLru()

        self.results_data = {}
        for r in range(n):
            self.results_data[r] = {
                "path": f"ch{r}.html",
                "internal_html_path": f"ch{r}.xhtml",
                # Простой безартефактный текст: repair_ai_html_artifacts не
                # должен ничего в нём поменять — нас интересует только
                # цикл чтения, а не сама логика починки.
                "translated_html": f"<p>Chapter {r} translation.</p>",
                "untranslated_words": [],
                "is_edited": False,
            }

        self.table_results = QTableWidget(n, 4)
        self.table_results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for r in range(n):
            for c in range(4):
                self.table_results.setItem(r, c, QTableWidgetItem(""))


def _make_original_epub(tmp_path, n):
    epub_path = os.path.join(str(tmp_path), "original.epub")
    with zipfile.ZipFile(epub_path, "w") as zf:
        for r in range(n):
            zf.writestr(f"ch{r}.xhtml", f"<p>Original {r}.</p>")
    return epub_path


def test_batch_repair_opens_original_zip_only_once_for_the_whole_pass(tmp_path):
    """Свойство 1: один открытый архив на весь проход, а не по разу на строку."""
    _make_app()
    n = 10
    epub_path = _make_original_epub(tmp_path, n)
    h = _Harness(n, epub_path)

    real_zipfile_class = zipfile.ZipFile
    open_calls = []
    read_calls = []

    class _CountingZipFile(real_zipfile_class):
        def __init__(self, *args, **kwargs):
            open_calls.append(1)
            super().__init__(*args, **kwargs)

        def read(self, name, *args, **kwargs):
            read_calls.append(name)
            return super().read(name, *args, **kwargs)

    with patch("gemini_translator.ui.dialogs.validation.zipfile.ZipFile", _CountingZipFile), \
         patch("gemini_translator.ui.dialogs.validation.QMessageBox") as message_box:
        h._repair_ai_artifacts_for_selection()

    assert len(open_calls) == 1, (
        f"архив оригинала открыт {len(open_calls)} раз(а) вместо одного на весь "
        "батч — дефект (или регресс исправления) all-visible-rows zip-reopen"
    )
    # Каждая глава реально прочитана из архива ровно один раз (промах LRU
    # размером 2 на 10 новых, ранее не встречавшихся ключей) — контент не
    # потерян из-за общего хендла, несмотря на вытеснение из кэша.
    assert sorted(read_calls) == sorted(f"ch{r}.xhtml" for r in range(n))
    # Изменений не найдено (безартефактный текст) -> путь "нет изменений".
    assert message_box.information.called


class _CancelingProgressDialog:
    """Фейковый QProgressDialog: отменяет проход после нескольких строк."""

    def __init__(self, *args, cancel_after=3, **kwargs):
        self._cancel_after = cancel_after
        self._values_seen = []

    def setWindowModality(self, *_a, **_kw):
        pass

    def setMinimumDuration(self, *_a, **_kw):
        pass

    def setValue(self, value):
        self._values_seen.append(value)

    def wasCanceled(self):
        return len(self._values_seen) > self._cancel_after

    def close(self):
        pass

    def deleteLater(self):
        pass


def test_batch_repair_stops_early_when_progress_dialog_is_canceled(tmp_path):
    """Свойство 2: «Отмена» в прогресс-диалоге реально прерывает проход."""
    _make_app()
    n = 10
    epub_path = _make_original_epub(tmp_path, n)
    h = _Harness(n, epub_path)
    # Кэш вместимостью на все строки — считаем количество загруженных
    # оригиналов напрямую по числу ключей без вытеснения.
    h.original_content_cache = ContentLru(max_entries=100)

    fake_dialogs = []

    def _fake_progress_dialog_factory(*args, **kwargs):
        dlg = _CancelingProgressDialog(*args, cancel_after=3, **kwargs)
        fake_dialogs.append(dlg)
        return dlg

    with patch(
        "gemini_translator.ui.dialogs.validation.QProgressDialog",
        side_effect=_fake_progress_dialog_factory,
    ), patch("gemini_translator.ui.dialogs.validation.QMessageBox"):
        h._repair_ai_artifacts_for_selection()

    assert len(fake_dialogs) == 1
    processed_rows = len(h.original_content_cache)
    assert 0 < processed_rows < n, (
        f"обработано {processed_rows} из {n} строк — отмена должна была "
        "остановить проход раньше конца, но не сразу"
    )


def test_batch_repair_does_not_open_original_zip_when_no_row_misses_cache(tmp_path):
    """Minor-регресс код-ревью: если ни одна строка не промахивает кэш,
    архив оригинала вообще не должен открываться — раньше ZipFile
    открывался безусловно в начале ЛЮБОГО прохода, даже когда до него
    ни разу не доходило дело."""
    _make_app()
    n = 10
    epub_path = _make_original_epub(tmp_path, n)
    h = _Harness(n, epub_path)
    h.original_content_cache = ContentLru(max_entries=100)
    # Каждая глава уже в кэше — реальных промахов не будет ни одного.
    for r in range(n):
        h.original_content_cache[f"ch{r}.xhtml"] = f"<p>Original {r}.</p>"

    real_zipfile_class = zipfile.ZipFile
    open_calls = []

    class _CountingZipFile(real_zipfile_class):
        def __init__(self, *args, **kwargs):
            open_calls.append(1)
            super().__init__(*args, **kwargs)

    with patch("gemini_translator.ui.dialogs.validation.zipfile.ZipFile", _CountingZipFile), \
         patch("gemini_translator.ui.dialogs.validation.QMessageBox") as message_box:
        h._repair_ai_artifacts_for_selection()

    assert len(open_calls) == 0, (
        f"архив оригинала открыт {len(open_calls)} раз(а), хотя ни одна строка "
        "не промахнула кэш — открытие ZipFile должно быть ленивым"
    )
    assert message_box.information.called


class _TrackingProgressDialog:
    """Фейковый QProgressDialog, никогда не отменяющий проход, но
    фиксирующий close()/deleteLater()."""

    def __init__(self, *args, **kwargs):
        self.close_called = False
        self.delete_later_called = False

    def setWindowModality(self, *_a, **_kw):
        pass

    def setMinimumDuration(self, *_a, **_kw):
        pass

    def setValue(self, value):
        pass

    def wasCanceled(self):
        return False

    def close(self):
        self.close_called = True

    def deleteLater(self):
        self.delete_later_called = True


def test_batch_repair_closes_and_deletes_progress_dialog_when_done(tmp_path):
    """Minor-регресс код-ревью: прогресс-диалог должен явно close()/
    deleteLater() после прохода — раньше он только скрывался
    (autoReset/autoClose), накапливаясь как дочерний объект страницы на
    каждый запуск автоправки."""
    _make_app()
    n = 5
    epub_path = _make_original_epub(tmp_path, n)
    h = _Harness(n, epub_path)

    created = []

    def _factory(*args, **kwargs):
        dlg = _TrackingProgressDialog(*args, **kwargs)
        created.append(dlg)
        return dlg

    with patch(
        "gemini_translator.ui.dialogs.validation.QProgressDialog",
        side_effect=_factory,
    ), patch("gemini_translator.ui.dialogs.validation.QMessageBox"):
        h._repair_ai_artifacts_for_selection()

    assert len(created) == 1
    assert created[0].close_called is True
    assert created[0].delete_later_called is True


def test_batch_repair_reports_cancellation_when_no_changes_found(tmp_path):
    """Minor-регресс код-ревью: если проход отменён и кандидатов на правку
    не нашлось, итоговое сообщение обязано честно сказать, что проход
    прерван и обработана лишь часть строк — раньше отмена молча вела к
    тому же тексту, что и полный проход без изменений."""
    _make_app()
    n = 10
    epub_path = _make_original_epub(tmp_path, n)
    h = _Harness(n, epub_path)
    h.original_content_cache = ContentLru(max_entries=100)

    fake_dialogs = []

    def _factory(*args, **kwargs):
        dlg = _CancelingProgressDialog(*args, cancel_after=3, **kwargs)
        fake_dialogs.append(dlg)
        return dlg

    with patch(
        "gemini_translator.ui.dialogs.validation.QProgressDialog",
        side_effect=_factory,
    ), patch("gemini_translator.ui.dialogs.validation.QMessageBox") as message_box:
        h._repair_ai_artifacts_for_selection()

    assert len(fake_dialogs) == 1
    assert message_box.information.called
    shown_message = message_box.information.call_args.args[-1]
    assert "прерван" in shown_message.lower(), (
        f"сообщение не сообщает об отмене прохода: {shown_message!r}"
    )
    assert "3" in shown_message and "10" in shown_message, (
        f"сообщение не называет, сколько строк реально обработано: {shown_message!r}"
    )


class _FakeReviewPage(ShellPage):
    """Минимальная замена AIRepairReviewPage для теста сообщения о частичном
    проходе: _push_ai_repair_review_page работает со страницей ревью только
    через result_ready/request_back/selected_html_by_row() — конструктор
    настоящей AIRepairReviewPage тянет полноценную таблицу и редактор,
    вообще не относящиеся к тексту сообщения об отмене."""

    result_ready = pyqtSignal(bool)

    instances = []

    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.candidates = candidates
        self.selected = {}
        _FakeReviewPage.instances.append(self)

    def selected_html_by_row(self):
        return self.selected


class _ReviewHarness(ShellPage):
    """Минимальный объект с настоящим телом _push_ai_repair_review_page."""

    _push_ai_repair_review_page = P._push_ai_repair_review_page

    def __init__(self, results_data):
        super().__init__()
        self.results_data = results_data
        self.btn_save_changes = QPushButton()
        self.lbl_status = QLabel()
        self._fixer_data_fingerprint = "stale"
        self.marked_rows = []

    def _ensure_row_translated_html_loaded(self, row):
        return self.results_data[row]["translated_html"]

    def _mark_row_changed_by_ai_repair(self, row):
        # Реальное обновление ячеек/статусов таблицы результатов — отдельная
        # логика, не относящаяся к тексту сообщения об отмене; стаб только
        # фиксирует, что до применения строки вообще дошло исполнение.
        self.marked_rows.append(row)

    def reapply_filters(self):
        pass

    def update_comparison_view(self):
        pass


def test_push_ai_repair_review_page_notes_cancellation_in_completion_message():
    """Minor-регресс код-ревью: сообщение после применения строк со
    страницы ревью обязано сказать, что проход был прерван и что показаны
    предложения только по обработанной части — раньше canceled никуда не
    передавался, и сообщение выглядело так, будто прошли все строки."""
    _make_app()
    _FakeReviewPage.instances = []
    h = _ReviewHarness({0: {"internal_html_path": "ch0.xhtml", "translated_html": "<p>old</p>"}})

    review_candidates = [{
        "row": 0,
        "chapter": "ch0.xhtml",
        "original_html": "<p>old</p>",
        "repaired_html": "<p>fixed</p>",
        "segments": [],
        "changes": [{"id": "c0"}],
        "warning": "",
        "notes": "",
    }]

    with patch(
        "gemini_translator.ui.dialogs.validation.AIRepairReviewPage",
        _FakeReviewPage,
    ), patch("gemini_translator.ui.dialogs.validation.QMessageBox") as message_box:
        h._push_ai_repair_review_page(
            review_candidates,
            used_selection=True,
            unchanged_count=2,
            errors=[],
            ambiguous_glued_words=None,
            canceled=True,
            processed_count=3,
            total_count=10,
        )
        assert len(_FakeReviewPage.instances) == 1
        page = _FakeReviewPage.instances[0]
        page.selected = {0: "<p>fixed</p>"}
        page.result_ready.emit(True)

    assert h.marked_rows == [0]
    assert message_box.information.called
    shown_message = message_box.information.call_args.args[-1]
    assert "прерван" in shown_message.lower(), (
        f"сообщение не сообщает об отмене прохода: {shown_message!r}"
    )
    assert "3" in shown_message and "10" in shown_message, (
        f"сообщение не называет, сколько строк реально обработано: {shown_message!r}"
    )


def test_push_ai_repair_review_page_skips_row_retargeted_during_the_pass():
    """Minor-регресс код-ревью: прогресс-диалог пампит цикл событий на
    каждом setValue() внутри долгого прохода, и таблицу результатов могут
    успеть перестроить (например, _smart_reload_table_preserving_data после
    фоновой синхронизации) — тогда числовой row из кандидата к моменту
    применения указывает уже на ДРУГУЮ главу. Применять правку по такому
    row нельзя: это молча испортит не ту главу."""
    _make_app()
    _FakeReviewPage.instances = []
    h = _ReviewHarness({0: {"internal_html_path": "ch0.xhtml", "translated_html": "<p>old</p>"}})

    review_candidates = [{
        "row": 0,
        "internal_html_path": "ch0.xhtml",
        "chapter": "ch0.xhtml",
        "original_html": "<p>old</p>",
        "repaired_html": "<p>fixed</p>",
        "segments": [],
        "changes": [{"id": "c0"}],
        "warning": "",
        "notes": "",
    }]

    with patch(
        "gemini_translator.ui.dialogs.validation.AIRepairReviewPage",
        _FakeReviewPage,
    ), patch("gemini_translator.ui.dialogs.validation.QMessageBox") as message_box:
        h._push_ai_repair_review_page(
            review_candidates,
            used_selection=True,
            unchanged_count=0,
            errors=[],
        )
        assert len(_FakeReviewPage.instances) == 1
        page = _FakeReviewPage.instances[0]
        page.selected = {0: "<p>fixed</p>"}
        # За время прохода (в реальности — пока крутился прогресс-диалог)
        # таблицу результатов перестроили: row 0 теперь относится к СОВСЕМ
        # ДРУГОЙ главе.
        h.results_data[0]["internal_html_path"] = "ch999-not-the-one.xhtml"
        page.result_ready.emit(True)

    assert h.marked_rows == [], (
        "правка применена к строке, которая на момент применения указывала "
        "уже не на ту главу, для которой её построили"
    )
    assert h.results_data[0]["translated_html"] == "<p>old</p>"
    assert message_box.information.called
    shown_message = message_box.information.call_args.args[-1]
    assert "перестрой" in shown_message.lower(), (
        f"сообщение не предупреждает о пропуске перенумерованной строки: {shown_message!r}"
    )
