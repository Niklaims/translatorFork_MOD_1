# -*- coding: utf-8 -*-
"""
Тест на находку ui-dialogs-epub-consistency/bugs/5-epub-duplicate-followup-run-no.

TranslatedChaptersManagerDialog._on_translated_duplicate_cleanup_finished()
после применения выбранных исправлений создавал ещё один
HtmlDuplicateAnalysisThread для повторной проверки дублей и вызывал у него
`.run()` напрямую вместо `.start()`. `.run()` — обычный метод Python-объекта:
вызванный так, он выполняется синхронно в текущем (GUI) потоке, несмотря на
то что класс отнаследован от QThread, из-за чего повторное сканирование
HTML-файлов (BeautifulSoup по каждой главе) блокирует интерфейс.

До фикса: `.run()` вызывается напрямую, `.start()` — нет; тест падает на
`fake_run.assert_not_called()` (RED).
После фикса: код запускает поток через `.start()` и обрабатывает результат в
слоте, подключённом к `analysis_finished`, а не читает словарь сразу после
вызова (GREEN).

Дополнительные тесты (по замечанию рецензента к первой версии правки):
первая версия запускала повторное сканирование через .start(), но БЕЗ
модального wait_dialog — в отличие от первого прохода в
_open_duplicate_cleanup_for_translated_files. Из-за этого фоновый проход
проходил молча: интерфейс не блокировался модальным окном, оставался
кликабельным (можно закрыть окно менеджера или второй раз нажать поиск
повторов), а по завершении приложения ещё бегущий QThread мог быть уничтожен
C++-родителем. Тесты ниже проверяют, что wait_dialog показывается перед
стартом повторного потока и закрывается в слоте, обрабатывающем его
результат, а сам поток освобождается через deleteLater по сигналу finished.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

import gemini_translator.ui.dialogs.epub as epub_module
from gemini_translator.ui.dialogs.epub import TranslatedChaptersManagerDialog


class _App:
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class OnTranslatedDuplicateCleanupFinishedFollowupTests(unittest.TestCase, _App):
    @classmethod
    def setUpClass(cls):
        _App.setUpClass()

    def _make_dialog(self, **attrs):
        # Обходим тяжёлую бизнес-логику __init__, но конструируем нижележащий
        # C++/Qt-объект напрямую через QDialog.__init__, иначе QMessageBox(self)
        # падает с "super-class __init__() ... was never called".
        dialog = TranslatedChaptersManagerDialog.__new__(TranslatedChaptersManagerDialog)
        QtWidgets.QDialog.__init__(dialog, None)
        for name, value in attrs.items():
            setattr(dialog, name, value)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _make_ready_dialog(self):
        dialog = self._make_dialog(project_manager=mock.Mock())
        dialog._get_build_chapter_filepaths = mock.Mock(return_value=["/tmp/does-not-matter.xhtml"])
        dialog.load_chapters = mock.Mock()
        dialog._update_preview_button_state = mock.Mock()
        return dialog

    def test_followup_analysis_started_via_start_not_run(self):
        dialog = self._make_ready_dialog()

        with mock.patch.object(epub_module.HtmlDuplicateAnalysisThread, "start", autospec=True) as fake_start, \
                mock.patch.object(epub_module.HtmlDuplicateAnalysisThread, "run", autospec=True) as fake_run, \
                mock.patch.object(epub_module.QMessageBox, "information") as fake_info:
            dialog._on_translated_duplicate_cleanup_finished(True, "Удалено 3 повтора")

            fake_run.assert_not_called()
            fake_start.assert_called_once()
            # Пока фейковый поток "не завершился" (сигнал вручную не эмитирован),
            # итоговое сообщение не должно быть готово синхронно — иначе
            # результат по-прежнему читается сразу после запуска, а не из слота.
            fake_info.assert_not_called()

    def test_followup_analysis_finished_signal_drives_result_message(self):
        dialog = self._make_ready_dialog()

        with mock.patch.object(epub_module.HtmlDuplicateAnalysisThread, "start", autospec=True) as fake_start, \
                mock.patch.object(epub_module.QMessageBox, "information") as fake_info:
            dialog._on_translated_duplicate_cleanup_finished(True, "Удалено 3 повтора")

            self.assertEqual(fake_start.call_count, 1)
            # .start() — это sip-обёртка над C++ QThread::start(), autospec не
            # записывает self в call_args (в отличие от обычного питоновского
            # .run()), поэтому берём созданный поток из атрибута диалога.
            thread_instance = dialog.followup_duplicate_analysis_thread
            # Эмулируем завершение фонового сканирования, как это сделал бы
            # реальный QThread по окончании run().
            thread_instance.analysis_finished.emit({'start_findings': [], 'boundary_findings': []})

            fake_info.assert_called_once()
            args, _ = fake_info.call_args
            self.assertEqual(args[2], "Удалено 3 повтора")

    def test_wait_dialog_shown_while_followup_analysis_runs(self):
        dialog = self._make_ready_dialog()

        with mock.patch.object(epub_module.HtmlDuplicateAnalysisThread, "start", autospec=True):
            dialog._on_translated_duplicate_cleanup_finished(True, "Удалено 3 повтора")

            # Пока фоновый поток "не завершился" (start замокан, сигнал не
            # эмитирован), модальный wait_dialog должен быть показан —
            # иначе пользователь не видит никакой реакции интерфейса на
            # время повторного сканирования.
            self.assertTrue(hasattr(dialog, 'wait_dialog'))
            self.assertIsNotNone(dialog.wait_dialog)
            self.assertTrue(dialog.wait_dialog.isVisible())

    def test_wait_dialog_closed_when_followup_analysis_finishes(self):
        dialog = self._make_ready_dialog()

        with mock.patch.object(epub_module.HtmlDuplicateAnalysisThread, "start", autospec=True), \
                mock.patch.object(epub_module.QMessageBox, "information"):
            dialog._on_translated_duplicate_cleanup_finished(True, "Удалено 3 повтора")
            wait_dialog = dialog.wait_dialog
            self.assertTrue(wait_dialog.isVisible())

            thread_instance = dialog.followup_duplicate_analysis_thread
            thread_instance.analysis_finished.emit({'start_findings': [], 'boundary_findings': []})

            self.assertFalse(wait_dialog.isVisible())

    def test_followup_thread_deleted_on_finished_signal(self):
        # deleteLater() лишь ставит C++-объект в очередь на удаление при
        # следующей обработке событий, поэтому патчить сам метод бесполезно:
        # соединение сигнала сделано с оригинальным bound-методом ДО патча,
        # и подмена атрибута на инстансе на уже установленное соединение не
        # влияет. Проверяем реальный эффект — объект действительно удалён
        # sip после emit(finished) + обработки очереди событий.
        from PyQt6 import sip

        dialog = self._make_ready_dialog()

        with mock.patch.object(epub_module.HtmlDuplicateAnalysisThread, "start", autospec=True):
            dialog._on_translated_duplicate_cleanup_finished(True, "Удалено 3 повтора")

            thread_instance = dialog.followup_duplicate_analysis_thread
            self.assertFalse(sip.isdeleted(thread_instance))

            thread_instance.finished.emit()
            # deleteLater() лишь ставит в очередь DeferredDelete-событие;
            # обычный processEvents() не гарантированно её разбирает, нужно
            # явно попросить доставить события этого типа.
            from PyQt6 import QtCore as _QtCore
            _QtCore.QCoreApplication.sendPostedEvents(None, _QtCore.QEvent.Type.DeferredDelete.value)

            self.assertTrue(sip.isdeleted(thread_instance))


if __name__ == "__main__":
    unittest.main()
