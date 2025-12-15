from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QPushButton, QGroupBox,
)
class ReferenceControlWidget(QWidget):
    """

    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ref. Control")

        # Scan parameters

        scan_group = QGroupBox("References")

        scan_group.setLayout(QHBoxLayout())

        self.dark_button = QPushButton("Dark")
        self.gain_trial_button = QPushButton("Gain Trial")
        self.gain_button = QPushButton("Gain")
        scan_group.layout().addWidget(self.dark_button)
        scan_group.layout().addWidget(self.gain_trial_button)
        scan_group.layout().addWidget(self.gain_button)
        main_layout = QHBoxLayout()
        main_layout.addWidget(scan_group)
        self.setLayout(main_layout)