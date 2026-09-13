# -*- coding: utf-8 -*-
"""Регресс на ui-dialogs-other/bugs/6-chapter-editor-sync-diff-block
и на замечания ревью к первой версии фикса.

``ChapterEditorDialog._refresh_analysis`` раньше выполняла HTML-парсинг
проблемных мест (``_analyze_chapter_problems``) и построчный
``SequenceMatcher``-дифф прямо в слоте ``QTimer.timeout`` — то есть
синхронно на главном (GUI) потоке. Для диалогово-плотных глав, близких
к DIFF_TEXT_LIMIT/DIFF_LINE_LIMIT, это заметно подвешивало редактор при
каждой паузе в наборе. Расчёт вынесен в фоновый ``_ChapterAnalysisWorker``
(``QThread``), результат применяется на GUI-потоке в ``_on_analysis_ready``.

Первая версия этого фикса ждала завершения воркера только в
``closeEvent`` — а Esc в QDialog обрабатывается через
``QDialog.keyPressEvent`` -> ``reject()`` -> ``done()``, минуя
``closeEvent`` целиком. Дальше в реальном приложении ``OverlayHost``
подписан на сигнал ``finished`` диалога и по нему делает
``setParent(None)`` + ``deleteLater()`` (см. ``epub.py``,
``overlay_host.py``). Единственная Python-ссылка на ещё работающий
воркер жила в ``dialog._analysis_thread`` — вместе с диалогом исчезала и
она, и Qt ронял процесс при уничтожении ещё работающего ``QThread``
(``"QThread: Destroyed while thread is still running"``, SIGABRT).

Тесты в этом файле проверяют:
  1. тяжёлый анализ действительно уходит в фоновый поток;
  2. диалог можно уничтожить (через reject()+deleteLater(), как это
     реально делает OverlayHost при закрытии по Esc), пока анализ ещё не
     завершился, и работающий QThread при этом не разрушается — он
     переживает диалог и освобождается сам, когда естественным образом
     завершится;
  3. результат, посчитанный по уже неактуальному saved_text (глава была
     сохранена, пока анализ считался), не затирает актуальное состояние
     ``_changed_lines``;
  4. исключение при применении результата к виджетам не оставляет
     ``_analysis_thread`` навечно занятым;
  5. закрытие диалога не блокируется на время работы анализа (раньше
     ``closeEvent`` синхронно ждал воркер без таймаута).
"""

import gc
import os
import tempfile
import threading
import time
import weakref

from PyQt6 import QtTest, QtWidgets

from gemini_translator.ui.dialogs import chapter_editor


def _make_dialog(tmp_dir: str, text: str = "<p>Раз.</p><p>Два.</p><p>Три.</p>"):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    translated_path = os.path.join(tmp_dir, "chapter.html")
    with open(translated_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return chapter_editor.ChapterEditorDialog(
        translated_path,
        original_epub_path=None,
        original_internal_path=None,
        project_manager=None,
    )


def _worker_running(worker) -> bool:
    """``worker.isRunning()``, но переживает уже удалённый C++ объект.

    Как только поток естественно завершается, ``_retire_analysis_worker``
    (см. chapter_editor.py) сам вызывает ``worker.deleteLater()`` — после
    того, как деферред-удаление реально обработается event loop'ом,
    обращение к любому методу воркера бросает
    ``RuntimeError: wrapped C/C++ object ... has been deleted``. Раз объект
    удалён именно ЭТИМ путём (через finished -> deleteLater), значит поток
    уже не работает — это не свежая проблема, а ожидаемый исход.
    """
    try:
        return worker.isRunning()
    except RuntimeError:
        return False


def _wait_until(predicate, timeout_ms: int = 2000, step_ms: int = 25) -> bool:
    """Прокручиваем event loop, пока predicate() не станет истинным.

    Аналог qtbot.waitUntil/waitSignal, но через QTest.qWait: в этом файле
    оба варианта из pytest-qt почему-то не ловят сигнал фонового QThread
    (таймаут даже когда воркер реально уже отработал и сигнал доставлен),
    а обычный опрос через qWait — тот же приём, что и в остальных тестах
    репозитория (см. test_delayed_wait_dialog.py) — работает надёжно.
    """
    waited = 0
    while waited < timeout_ms:
        if predicate():
            return True
        QtTest.QTest.qWait(step_ms)
        waited += step_ms
    return predicate()


def test_chapter_analysis_runs_off_the_gui_thread(qtbot, monkeypatch):
    real_analyze = chapter_editor._analyze_chapter_problems
    call_threads = []

    def _spy_analyze(*args, **kwargs):
        call_threads.append(threading.current_thread())
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(chapter_editor, "_analyze_chapter_problems", _spy_analyze)

    with tempfile.TemporaryDirectory() as tmp_dir:
        dialog = _make_dialog(tmp_dir)
        qtbot.addWidget(dialog)

        # Загрузка главы уже вызвала первый _refresh_analysis() —
        # воркер должен быть запущен, но ещё не мог доставить сигнал
        # (доставка требует прокрутки event loop, которой пока не было).
        worker = dialog._analysis_thread
        assert worker is not None, (
            "анализ обязан уйти в фоновый _ChapterAnalysisWorker, а не "
            "выполниться синхронно внутри _load_state()"
        )

        # Даём event loop доставить очередь сигналов на GUI-поток.
        assert _wait_until(lambda: dialog._analysis_thread is None), (
            "фоновый анализ не завершился и не применил результат "
            "(analysis_ready так и не доставлен на GUI-поток)"
        )

        assert call_threads, "_analyze_chapter_problems ни разу не вызвана"
        assert all(
            thread is not threading.main_thread() for thread in call_threads
        ), (
            "_analyze_chapter_problems выполнилась на главном потоке — "
            "тяжёлый парсинг/дифф снова блокирует GUI"
        )

        # Результат должен корректно долетать обратно и применяться к
        # виджетам диалога на главном потоке.
        assert dialog.issues_list.count() >= 1


def test_reject_during_background_analysis_does_not_destroy_running_worker(qtbot, monkeypatch):
    """Регресс на blocker из ревью: Esc (reject()) минует closeEvent.

    Воспроизводим ровно то, что делает связка QDialog.reject() ->
    done() -> emit finished -> OverlayHost._dismiss в проде: reject(),
    затем setParent(None) + deleteLater(), затем удаление последних
    Python-ссылок на диалог и сборка мусора — пока фоновый воркер ещё
    гарантированно работает (стаб анализа спит достаточно долго).

    Без фикса эта последовательность превращает эту функцию не в
    упавший тест, а в аварийно завершившийся процесс (SIGABRT) — это
    неотъемлемое свойство бага (Qt уничтожает работающий QThread), а не
    недостаток теста. Фикстура ``qtbot`` запрошена только ради корректно
    настроенного pytest-qt'шного QApplication (без неё голое создание
    QApplication внутри теста падает даже без какого-либо кода из этого
    файла — окружение pytest-qt, а не наш баг); qtbot.addWidget(dialog) же
    намеренно НЕ вызываем: qtbot сам держит ссылку на диалог до конца
    теста, а тест обязан проверить именно момент, когда никакая ссылка на
    диалог больше не остаётся.
    """
    real_analyze = chapter_editor._analyze_chapter_problems

    def _slow_analyze(*args, **kwargs):
        time.sleep(0.4)
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(chapter_editor, "_analyze_chapter_problems", _slow_analyze)

    with tempfile.TemporaryDirectory() as tmp_dir:
        dialog = _make_dialog(tmp_dir)

        worker = dialog._analysis_thread
        assert worker is not None and worker.isRunning(), (
            "воркер должен быть ещё жив на этом шаге — иначе проба ничего "
            "не проверяет (сделай стаб анализа медленнее)"
        )
        worker_ref = weakref.ref(worker)
        # Локальная переменная worker — единственная оставшаяся Python-
        # ссылка помимо диалога и модульного реестра; её тоже нужно снять,
        # иначе именно она (а не реестр) будет держать объект живым ниже,
        # и проверка утечки будет проверять не то.
        del worker

        # Esc в реальном UI обрабатывается QDialog.keyPressEvent через
        # reject(); используем reject() напрямую — это ровно тот же путь
        # (closeEvent он не проходит).
        dialog.reject()

        # Так OverlayHost._dismiss освобождает диалог по сигналу finished.
        dialog.setParent(None)
        dialog.deleteLater()
        del dialog
        gc.collect()

        # Если процесс дожил до этой строки — воркер не был уничтожен
        # работающим (иначе процесс уже упал бы с SIGABRT).
        assert worker_ref() is not None and worker_ref().isRunning(), (
            "фоновый QThread не должен исчезать, пока он ещё работает"
        )

        # Поток должен естественно доработать и сам себя освободить —
        # реестр не течёт воркерами, которые уже закончили.
        assert _wait_until(lambda: worker_ref() is None), (
            "воркер остался висеть после завершения потока — утечка в "
            "модульном реестре _ACTIVE_ANALYSIS_WORKERS"
        )


def test_stale_analysis_result_does_not_overwrite_fresh_saved_state(qtbot):
    """Регресс на находку ревью: устаревший дифф поверх нового состояния.

    Воркер захватывает saved_text на старте. Если пока он считает,
    save_changes() успевает сохранить главу (и обнулить _changed_lines
    через _set_saved_state), результат, посчитанный по СТАРОМУ
    saved_text, не должен затем перекрашивать только что сохранённые
    строки как изменённые.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        dialog = _make_dialog(tmp_dir, text="<p>Раз.</p>\n<p>Два.</p>\n")
        qtbot.addWidget(dialog)
        assert _wait_until(lambda: dialog._analysis_thread is None)

        # Пользователь правит текст и анализ запускается вручную (как это
        # сделал бы analysis_timer), но event loop ещё не прокручивался —
        # сигнал воркера гарантированно не доставлен.
        dialog._loading = False
        dialog.translated_editor.setPlainText("<p>Раз.</p>\n<p>ДВА-ИЗМЕНЕНО.</p>\n")
        dialog._start_analysis_worker()
        worker = dialog._analysis_thread
        assert worker is not None

        # Пользователь жмёт "Сохранить", пока воркер ещё в полёте — это
        # обновляет _saved_text и обнуляет _changed_lines НЕЗАВИСИМО от
        # воркера, который считает дифф по старому _saved_text.
        assert dialog.save_changes() is True
        assert dialog._changed_lines == set()
        assert dialog._saved_text == dialog.translated_document.toPlainText()

        # Прилетает результат, посчитанный по старому saved_text.
        assert _wait_until(lambda: dialog._analysis_thread is None)

        assert dialog._changed_lines == set(), (
            "устаревший дифф (посчитанный до save_changes) перекрасил "
            "только что сохранённую главу как изменённую"
        )
        assert dialog._saved_text == dialog.translated_document.toPlainText()


def test_exception_in_analysis_ready_does_not_permanently_block_reanalysis(qtbot, monkeypatch):
    """Регресс на находку ревью: исключение в _on_analysis_ready.

    Раньше сброс dialog._analysis_thread стоял в САМОМ КОНЦЕ слота,
    после всего блока обновления виджетов. Если что-то в этом блоке
    бросало исключение, _analysis_thread навсегда оставался не-None, и
    все дальнейшие _refresh_analysis() только выставляли
    _analysis_dirty=True, ничего не запуская, — анализ главы умирал до
    конца жизни диалога.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        dialog = _make_dialog(tmp_dir)
        qtbot.addWidget(dialog)
        assert _wait_until(lambda: dialog._analysis_thread is None)

        def _boom(*args, **kwargs):
            raise RuntimeError("бум — сбой при применении результата анализа")

        monkeypatch.setattr(dialog, "_update_summary", _boom)

        dialog._start_analysis_worker()
        assert dialog._analysis_thread is not None

        # pytest-qt по умолчанию проваливает тест при ЛЮБОМ исключении,
        # долетевшем через Qt-слот, — оборачиваем ожидание в свой перехват,
        # чтобы проверить именно то, что нас интересует (что _boom
        # действительно сработал и что это не помешало сбросу
        # _analysis_thread), а не получить чужой pytest.fail().
        with qtbot.captureExceptions() as exceptions:
            assert _wait_until(lambda: dialog._analysis_thread is None), (
                "_analysis_thread не сброшен даже после того, как слот "
                "должен был отработать (пусть и с исключением)"
            )

        assert len(exceptions) == 1 and exceptions[0][0] is RuntimeError, (
            "проба должна была спровоцировать исключение внутри "
            "_on_analysis_ready через monkeypatch _update_summary — иначе "
            "тест ничего не проверяет"
        )

        # Диалог не должен навсегда застрять в состоянии "анализ занят" —
        # следующий _refresh_analysis обязан завести новый воркер, а не
        # просто выставить _analysis_dirty.
        monkeypatch.undo()
        dialog._refresh_analysis()
        assert dialog._analysis_thread is not None, (
            "после сбоя внутри _on_analysis_ready дальнейший анализ "
            "молча перестал запускаться"
        )
        assert _wait_until(lambda: dialog._analysis_thread is None)


def test_closing_dialog_does_not_block_on_running_analysis(qtbot, monkeypatch):
    """Регресс на находку ревью: worker.wait() без таймаута на закрытии.

    Раньше closeEvent синхронно ждал завершения воркера без ограничения
    по времени — при небольшом тексте это маскировалось лимитами диффа,
    но сам HTML-парсинг (_analyze_chapter_problems) ими не ограничен.
    closeEvent не должен блокировать GUI-поток на время работы анализа.
    """
    real_analyze = chapter_editor._analyze_chapter_problems

    def _slow_analyze(*args, **kwargs):
        time.sleep(1.0)
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(chapter_editor, "_analyze_chapter_problems", _slow_analyze)

    with tempfile.TemporaryDirectory() as tmp_dir:
        dialog = _make_dialog(tmp_dir)
        qtbot.addWidget(dialog)

        worker = dialog._analysis_thread
        assert worker is not None and worker.isRunning()
        assert not dialog.translated_document.isModified()

        started = time.monotonic()
        dialog.close()
        elapsed = time.monotonic() - started

        assert elapsed < 0.3, (
            f"closeEvent заблокировал GUI-поток на {elapsed:.2f}с, ожидая "
            "фоновый анализ вместо того, чтобы просто закрыться"
        )

        # Воркер, запущенный на 1с, всё ещё жив сразу после close() —
        # именно поэтому предыдущая проверка вообще что-то доказывает.
        assert _worker_running(worker)

        assert _wait_until(lambda: not _worker_running(worker))
