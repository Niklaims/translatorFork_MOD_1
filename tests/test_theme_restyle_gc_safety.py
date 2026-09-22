"""Пока тема перестилизует приложение, сборщик мусора не работает.

QApplication.setStyleSheet снимает список указателей на все виджеты и шлёт
каждому StyleChange. На этих событиях работает Python — фильтры событий,
переопределённые event(), — и автоматический сборщик мусора может удалить
виджет из циклической ссылки, до которого перебор ещё не дошёл. Следующая
итерация обращается к удалённому объекту, и процесс падает: так трижды за
день падал полный набор тестов, всегда внутри theme_manager.apply. Сценарий
с gc.collect() в обработчике StyleChange падает с кодом 139 стабильно.
"""
import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from gemini_translator.ui import theme_manager as tm


class _CollectorProbe(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.collector_enabled = []

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API name
        if event.type() == QtCore.QEvent.Type.StyleChange:
            self.collector_enabled.append(gc.isenabled())
        return False


def _collector_states_during(qapp, restyle):
    label = QtWidgets.QLabel("styled")
    label.show()
    qapp.processEvents()
    probe = _CollectorProbe()
    qapp.installEventFilter(probe)
    try:
        restyle()
    finally:
        qapp.removeEventFilter(probe)
        label.close()
    return probe.collector_enabled


def test_garbage_collector_is_paused_while_the_theme_is_applied(qapp):
    def restyle():
        tm.apply(qapp, mode="light", manual_colors={})
        tm.apply(qapp, mode="dark", manual_colors={})

    states = _collector_states_during(qapp, restyle)

    assert states, "перестилизация не дошла до виджета"
    assert not any(states)
    assert gc.isenabled()


def test_app_stylesheet_helper_pauses_the_collector(qapp):
    # Тесты сбрасывают тему этой же функцией: прямой app.setStyleSheet("")
    # в их уборке падал так же.
    def restyle():
        tm.set_app_stylesheet(qapp, "QLabel { color: #123456; }")
        tm.set_app_stylesheet(qapp, "")

    states = _collector_states_during(qapp, restyle)

    assert states, "перестилизация не дошла до виджета"
    assert not any(states)
    assert gc.isenabled()
