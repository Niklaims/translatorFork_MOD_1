"""Регресс на находку ui-pages-shell/bugs/5-selection-translator-unguarded.

translate() разыменовывал snapshot.widget().window() без защиты от уже
уничтоженного (C++) виджета: SelectionSnapshot.widget() ловит только
ReferenceError/RuntimeError вокруг самого вызова weakref, но это никогда не
бросает RuntimeError — Python-обёртка возвращается даже после удаления её
C++-объекта. RuntimeError 'wrapped C/C++ object ... has been deleted'
возникает только при обращении к атрибуту/методу этой обёртки (здесь —
.window()).
"""

import weakref

from PyQt6 import QtCore, QtWidgets, sip

from gemini_translator.ui.selection_translator import (
    SelectionSnapshot,
    SelectionTranslationController,
)


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_translate_survives_widget_with_deleted_cpp_object(monkeypatch):
    """translate() не должен падать, если C++-объект виджета уже уничтожен.

    Python-обёртка ещё жива (мы держим на неё ссылку в `editor`), поэтому
    SelectionSnapshot.widget() вернёт её без исключения — ровно как в
    боевом сценарии, когда исходный диалог закрыт системной кнопкой, а
    плавающая кнопка-предложение перевода ещё видна и по ней кликают.
    """

    app = _app()
    controller = SelectionTranslationController(app)
    editor = QtWidgets.QLineEdit("Hello world")
    snapshot = SelectionSnapshot(
        widget_ref=weakref.ref(editor),
        text="Hello",
        start=0,
        end=5,
        editable=True,
    )

    # Принудительно уничтожаем C++-объект, не трогая Python-обёртку —
    # именно так выглядит виджет из уже закрытого диалога, на который ещё
    # существует "живая" ссылка (например, в снапшоте предложения перевода).
    sip.delete(editor)
    assert sip.isdeleted(editor)
    assert snapshot.widget() is editor  # обёртка жива, C++ — нет

    # Не должно падать необработанным RuntimeError.
    controller._request_next_chunk = lambda job_id: None
    controller.translate(snapshot, anchor=QtCore.QPoint(0, 0))

    controller.shutdown()
    app.removeEventFilter(controller)
