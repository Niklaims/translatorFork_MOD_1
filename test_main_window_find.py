from PyQt6.QtWidgets import QApplication

def get_main_window():
    for w in QApplication.topLevelWidgets():
        if w.__class__.__name__ == 'MainWindow':
            return w
    return None
