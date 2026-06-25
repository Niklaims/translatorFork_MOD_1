import sys
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QStyle
import ctypes

def main():
    app = QApplication(sys.argv)
    
    if sys.platform == 'win32':
        myappid = 'siberianteam.translatorfork.1.0'
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    tray = QSystemTrayIcon()
    icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    tray.setIcon(icon)
    tray.show()
    print("Tray icon visible:", tray.isVisible())
    print("System tray available:", QSystemTrayIcon.isSystemTrayAvailable())
    tray.showMessage("Test Title", "Test Message", QSystemTrayIcon.MessageIcon.Information, 5000)
    
    # Need to run event loop for a bit to show it
    import threading
    threading.Timer(2.0, app.quit).start()
    app.exec()

if __name__ == '__main__':
    main()
