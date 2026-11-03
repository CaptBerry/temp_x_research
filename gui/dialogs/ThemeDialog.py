"""Choose the application's light or dark theme."""

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout


class ThemeDialog(QDialog):
    def __init__(self, current_theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Тема приложения")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Выберите оформление интерфейса и 3D-сцены:"))
        self.light_radio = QRadioButton("Светлая")
        self.dark_radio = QRadioButton("Тёмная")
        layout.addWidget(self.light_radio)
        layout.addWidget(self.dark_radio)
        (self.dark_radio if current_theme == "dark" else self.light_radio).setChecked(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_theme(self):
        return "dark" if self.dark_radio.isChecked() else "light"
