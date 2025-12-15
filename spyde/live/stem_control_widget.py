from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton, QGroupBox,QComboBox
)


from spyde.external.qt.labels import EditableLabel

class StemControlWidget(QGroupBox):
    """

    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # Scan parameters
        self.setTitle("STEM Scan Control")

        scan_group = QGroupBox("Scan Parameters")
        scan_group.setMaximumHeight(60)
        scan_group.setLayout(QHBoxLayout())
        # input fields for x, y, scan rep.
        scan_group.layout().addWidget(QLabel("X:"))
        # input field for x pixels
        self.x_pixels_input = EditableLabel("256")
        scan_group.layout().addWidget(self.x_pixels_input)
        scan_group.layout().addWidget(QLabel("Y:"))
        # input field for y pixels
        self.y_pixels_input = EditableLabel("256")
        scan_group.layout().addWidget(self.y_pixels_input)
        scan_group.layout().addWidget(QLabel("Repeats:"))
        # input field for scan repetitions
        self.scan_reps_input = EditableLabel("1")
        scan_group.layout().addWidget(self.scan_reps_input)
        # Add scan group to main layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(scan_group)
        self.setLayout(main_layout)

        # Scan type:
        scan_type_layout = QHBoxLayout()
        scan_type_layout.addWidget(QLabel("Scan Type:"))
        # Add dropdown for scan type
        self.scan_type_dropdown = QComboBox()
        self.scan_type_dropdown.addItems(["Raster",
                                          "Serpentine",
                                          "Random"])
        scan_type_layout.addWidget(self.scan_type_dropdown)
        main_layout.addLayout(scan_type_layout)
        # Control buttons
        control_layout = QHBoxLayout()
        self.start_stop_button = QPushButton("Acquire")
        self.search_beam_button = QPushButton("Search")
        self.init_button = QPushButton("Init")
        control_layout.addWidget(self.init_button)
        control_layout.addWidget(self.start_stop_button)
        control_layout.addWidget(self.search_beam_button)
        main_layout.addLayout(control_layout)



