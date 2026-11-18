import sys
from pathlib import Path

from PyQt6.QtCore import QElapsedTimer, Qt, QTimer
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QSplashScreen


def main():
    if sys.platform == "win32":
        from ctypes import windll

        windll.shell32.SetCurrentProcessExplicitAppUserModelID("AVPD.XSearch")

    app = QApplication(sys.argv)
    images = Path(__file__).resolve().parent / "images"
    icon = QIcon(str(images / "logo.png"))
    app.setWindowIcon(icon)

    pixmap = QPixmap(str(images / "splash.png"))
    splash = None
    elapsed = QElapsedTimer()
    if not pixmap.isNull():
        pixmap = pixmap.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        splash = QSplashScreen(pixmap)
        splash.setWindowIcon(icon)
        splash.show()
        app.processEvents()
        elapsed.start()

    from gui.MainWindow import MainWindow

    window = MainWindow()
    window.setWindowIcon(icon)
    window.showMaximized()
    if splash is not None:
        QTimer.singleShot(max(0, 1000 - elapsed.elapsed()),
                          lambda: splash.finish(window))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
