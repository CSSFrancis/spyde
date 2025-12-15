from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton, QGroupBox,QComboBox
)


from spyde.external.qt.labels import EditableLabel

class CameraControlWidget(QGroupBox):
    """

    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # Scan parameters
        self.setTitle("CameraControl")

        scan_group = QGroupBox("Camera Parameters")
        scan_group.setMaximumHeight(60)
        scan_group.setLayout(QHBoxLayout())
        # input fields for fps and scan repeats.
        scan_group.layout().addWidget(QLabel("FPS:"))
        self.fps_input = EditableLabel("30")
        scan_group.layout().addWidget(self.fps_input)
        # Add scan group to main layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(scan_group)
        self.setLayout(main_layout)

        # Camera mode:
        mode_group = QGroupBox("Camera Mode")
        mode_group.setMaximumHeight(60)
        mode_group.setLayout(QHBoxLayout())
        mode_group.layout().addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Integrating", "Counting", "Hybrid"])
        mode_group.layout().addWidget(self.mode_combo)
        main_layout.addWidget(mode_group)
        


