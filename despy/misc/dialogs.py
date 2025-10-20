from functools import partial

import numpy as np
from PySide6.QtWidgets import QDialog, QVBoxLayout, QSpinBox, QLabel, QPushButton, QDialogButtonBox
import hyperspy.api as hs

from PySide6 import QtWidgets

import dask.array as da
import pyxem


class DatasetSizeDialog(QDialog):
    def __init__(self, parent=None, filename=None):
        print("Creating Dialog")
        super().__init__(parent)

        self.filename = filename

        kwargs = {}
        # try to load the dataset
        print(f"loading: {filename}")
        if ".mrc" in filename:
            kwargs["distributed"] = True
        try:
            data = hs.load(filename, lazy=True, **kwargs)
        except Exception as e:
            print(f"Error loading dataset: {e}")
            self.reject()
            return
        nav_shape = [a.size for a in data.axes_manager.navigation_axes]
        x, y, t = nav_shape + ([0,] * (3-len(nav_shape)))

        self.total_frames = np.prod(nav_shape)
        print(self.total_frames)

        sig_shape = [a.size for a in data.axes_manager.signal_axes]
        kx, ky, kz = sig_shape + ([0,] * (3-len(sig_shape)))
        print("setting_size")

        self.setWindowTitle("Dataset Size Configuration")

        # Main layout
        layout = QVBoxLayout(self)

        # Input fields for x, y, and time sizes
        self.x_input = QSpinBox()
        self.x_input.setRange(1, 100000)
        self.x_input.setValue(x)
        set_x = partial(self.update_image_size, 0)
        self.x_input.valueChanged.connect(set_x)

        set_y = partial(self.update_image_size, 1)
        self.y_input = QSpinBox()
        self.y_input.setRange(1, 100000)
        self.y_input.setValue(y)
        self.y_input.valueChanged.connect(set_y)

        set_t = partial(self.update_image_size, 2)
        self.time_input = QSpinBox()
        self.time_input.setRange(1, 10000)
        self.time_input.setValue(t)
        self.time_input.valueChanged.connect(set_t)

        # Labels and inputs
        layout.addWidget(QLabel("X Size:"))
        layout.addWidget(self.x_input)
        layout.addWidget(QLabel("Y Size:"))
        layout.addWidget(self.y_input)
        layout.addWidget(QLabel("Time Size:"))
        layout.addWidget(self.time_input)

        # Display for image size in pixels
        self.image_size_label = QLabel(f"Image Size (Pixels):( {kx}, {ky})")
        layout.addWidget(self.image_size_label)
        # Add a button to enable/disable the time input
        self.toggle_time_button = QPushButton("Enable Time Input")
        self.toggle_time_button.setCheckable(True)
        self.toggle_time_button.toggled.connect(self.toggle_time_input)
        layout.addWidget(self.toggle_time_button)
        self.time_input.setEnabled(False)  # Initially disable the time input
        # OK and Cancel buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.update_image_size()

    def update_image_size(self, index=None):
        """Update the image size in pixels based on x and y inputs."""
        if self.time_input.isEnabled():
            x = self.x_input.value()
            y = self.y_input.value()
            t = self.time_input.value()
            if index == 0 or index == 1:
                t = self.total_frames // (x * y)
                self.time_input.setValue(t)
        else:
            if index == 0:
                x_size = self.x_input.value()
                self.y_input.setValue(self.total_frames//x_size)
            else:
                y_size = self.y_input.value()
                self.x_input.setValue(self.total_frames//y_size)

    def toggle_time_input(self, checked):
        """Enable or disable the time input box."""
        self.time_input.setEnabled(checked)


class CreateDataDialog(QDialog):
    """
    Dialog to generate synthetic datasets for quick testing.

    Tabs:
    - insitu TEM: (t, x, y) -> ensures at least 2D spatial data.
    - 4D STEM: (x, y, kx, ky) -> random or multiphase synthetic patterns via `pyxem`.
    - 5D STEM: (t, x, y, kx, ky) -> flexible dimensionality; drops dims with size <= 1.

    Includes a dtype option: int8, int16, float32, float64.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Create Data")

        layout = QVBoxLayout(self)

        def add_spin_row(parent_layout: QtWidgets.QVBoxLayout,
                         label_text: str,
                         min_val: int,
                         max_val: int,
                         default: int) -> QtWidgets.QSpinBox:
            """Add a labeled QSpinBox row to a layout and return the spin box."""
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(label_text))
            spin = QtWidgets.QSpinBox()
            spin.setRange(min_val, max_val)
            spin.setValue(default)
            row.addWidget(spin)
            parent_layout.addLayout(row)
            return spin

        # DType selector
        dtype_row = QtWidgets.QHBoxLayout()
        dtype_row.addWidget(QtWidgets.QLabel("DType:"))
        self.dtype_combo = QtWidgets.QComboBox()
        self.dtype_combo.addItems(["int8", "int16", "float32", "float64"])
        dtype_row.addWidget(self.dtype_combo)
        layout.addLayout(dtype_row)

        # Tabs
        self.tabs: QtWidgets.QTabWidget = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: insitu TEM (t, x, y)
        insitu_tab = QtWidgets.QWidget()
        insitu_layout = QtWidgets.QVBoxLayout(insitu_tab)
        self.it_t_input = add_spin_row(insitu_layout, "Time Size:", 1, 10000, 10)
        self.it_x_input = add_spin_row(insitu_layout, "X Size:", 1, 10000, 256)
        self.it_y_input = add_spin_row(insitu_layout, "Y Size:", 1, 10000, 256)
        self.tabs.addTab(insitu_tab, "insitu TEM")

        # Tab 2: 4D STEM (x, y, kx, ky) + mode radios
        stem_tab = QtWidgets.QWidget()
        stem_layout = QtWidgets.QVBoxLayout(stem_tab)
        radios_layout = QtWidgets.QHBoxLayout()
        self.fs_multiphase_radio = QtWidgets.QRadioButton("Multiphase")
        self.fs_random_radio = QtWidgets.QRadioButton("Random")
        self.fs_random_radio.setChecked(True)
        radios_layout.addWidget(self.fs_multiphase_radio)
        radios_layout.addWidget(self.fs_random_radio)
        stem_layout.addLayout(radios_layout)
        self.fs_x_input = add_spin_row(stem_layout, "Scan X Size:", 1, 10000, 128)
        self.fs_y_input = add_spin_row(stem_layout, "Scan Y Size:", 1, 10000, 128)
        self.fs_kx_input = add_spin_row(stem_layout, "Detector KX Size:", 1, 10000, 64)
        self.fs_ky_input = add_spin_row(stem_layout, "Detector KY Size:", 1, 10000, 64)
        self.tabs.addTab(stem_tab, "4D STEM")

        # Tab 3: Random (t, x, y, kx, ky)
        random_tab = QtWidgets.QWidget()
        random_layout = QtWidgets.QVBoxLayout(random_tab)
        self.r_t_input = add_spin_row(random_layout, "Time Size:", 0, 10000, 0)
        self.r_x_input = add_spin_row(random_layout, "X Size:", 1, 10000, 128)
        self.r_y_input = add_spin_row(random_layout, "Y Size:", 1, 10000, 128)
        self.r_kx_input = add_spin_row(random_layout, "KX Size:", 1, 10000, 64)
        self.r_ky_input = add_spin_row(random_layout, "KY Size:", 1, 10000, 64)
        self.tabs.addTab(random_tab, "5D STEM")

        # OK / Cancel
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(button_box)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

    @staticmethod
    def _auto_chunks(ndim: int) -> tuple:
        """
        Build dask chunks with auto for navigation dims and -1 for the two signal dims.
        Ensures last two dims are unchunked (-1) for image data.
        """
        if ndim < 2:
            return (-1,)
        return ("auto",) * (ndim - 2) + (-1, -1)

    @staticmethod
    def _rand_array(size: tuple, chunks: tuple, dtype: np.dtype) -> da.Array:
        """
        Generate a random dask array of a given dtype.
        - Integers: uniform randint across full dtype range.
        - Floats: uniform [0, 1) cast to dtype.
        """
        if np.issubdtype(dtype, np.integer):
            info = np.iinfo(dtype)
            return da.random.randint(info.min, info.max + 1, size=size, chunks=chunks, dtype=dtype)
        # float
        return da.random.random(size, chunks=chunks).astype(dtype)

    @staticmethod
    def _wrap_lazy_signal2d(data: da.Array) -> hs.signals.BaseSignal:
        """
        Wrap a dask array as a lazy HyperSpy Signal2D and set a small cache pad.
        """
        s = hs.signals.Signal2D(data).as_lazy()
        s.cache_pad = 2
        return s

    def get_data(self) -> hs.signals.BaseSignal:
        """
        Create and return a synthetic dataset according to the selected tab.
        """
        current_tab = self.tabs.tabText(self.tabs.currentIndex())
        dtype = np.dtype(self.dtype_combo.currentText())

        if current_tab == "insitu TEM":
            # Keep dims with size > 1 and ensure at least 2D spatial data.
            size = (self.it_t_input.value(), self.it_x_input.value(), self.it_y_input.value())
            size = tuple(s for s in size if s > 1)
            if len(size) < 2:
                size = (max(2, self.it_x_input.value()), max(2, self.it_y_input.value()))
            data = self._rand_array(size, chunks=self._auto_chunks(len(size)), dtype=dtype)
            return self._wrap_lazy_signal2d(data)

        if current_tab == "4D STEM":
            if self.fs_random_radio.isChecked():
                size = (
                    self.fs_x_input.value(),
                    self.fs_y_input.value(),
                    self.fs_kx_input.value(),
                    self.fs_ky_input.value(),
                )
                data = self._rand_array(size, chunks=("auto", "auto", -1, -1), dtype=dtype)
                return self._wrap_lazy_signal2d(data)
            # Multiphase synthetic pattern from pyxem.
            s = pyxem.data.fe_multi_phase_grains(
                size=self.fs_x_input.value(),
                recip_pixels=self.fs_kx_input.value(),
                num_grains=4,
            ).as_lazy(chunks=("auto", "auto", -1, -1))
            s.cache_pad = 2
            # Cast to selected dtype (clip+round for integer)
            if np.issubdtype(dtype, np.integer):
                info = np.iinfo(dtype)
                s.data = da.clip(s.data, info.min, info.max).round().astype(dtype)
            else:
                s.data = s.data.astype(dtype)
            return s

        # Random tab: drop dims with size <= 1
        size = (
            self.r_t_input.value(),
            self.r_x_input.value(),
            self.r_y_input.value(),
            self.r_kx_input.value(),
            self.r_ky_input.value(),
        )
        size = tuple(s for s in size if s > 1)
        data = self._rand_array(size, chunks=self._auto_chunks(len(size)), dtype=dtype)
        return self._wrap_lazy_signal2d(data)