import sys

from PySide6.QtWidgets import QApplication

from sas_manhole_gui.main_window import MainWindow
from sas_manhole_gui.style import APP_STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SAS Manhole GUI")
    app.setOrganizationName("SAS")
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
