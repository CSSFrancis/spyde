"""
A widget for scanning over particle positions.

This will first establish a FOV using the HAADF or a set of virtual images.
Then the user will be able to adjust a threshold and only scan particles over
some threshold value.

For scanning over particles


Buttons:

- [Preview]: Show a preview of the scan positions over the FOV.
- [Scan Particles]: Perform the scan and display the results.

- Use DE Camera [True/False]:
- Integrate Particle DP [True/False]:


"""
from PySide6.QtWidgets import QGroupBox, QLabel, QHBoxLayout, QVBoxLayout, QComboBox, QPushButton, QWidget, QCheckBox
from numpy import dtype
from scipy.ndimage import label
import numpy as np

from spyde.external.qt.labels import EditableLabel


########### utility functions #############

def mask2positions(mask,
                   segment=True,
                   scan_type="raster",
                   frame_repeats=1
                   ):
    """Convert a mask (bool array) to a set of scan positions.

    Parameters
    ----------
    mask : np.ndarray
        A boolean array with the same shape as the image.
    segment : bool, optional
        If True, the mask is segmented into different regions using the `scipy.ndimage.label` function.
    scan_type : str, optional
        The type of scan. Either "raster" or "serpentine"
    frame_repeats : int, optional
        The number of times the frame is repeated.

    Returns
    -------
    np.ndarray
        An array with the integer positions of the scan. [n, 2]
    """

    if segment:
        labels, num_labels = label(mask)
    else:
        labels = mask
        num_labels =1
    all_pos = []
    for i in range(1, num_labels+1):
        if scan_type == "raster":
            pos = np.argwhere(labels==i)
            all_pos.append(pos)
        elif scan_type == "serpentine":
            mask_img = labels==i
            pos_test = np.empty(mask_img.shape+(2,), dtype=int)
            for p in np.argwhere(mask_img):
                pos_test[p[0], p[1]] = p

            mask_img[::2, :]=mask_img[::2, ::-1] # reverse everything
            pos_test[::2, :]=pos_test[::2, ::-1]
            all_pos.append(pos_test[mask_img])
    frame_scan = np.vstack(all_pos)
    if frame_repeats != 1:
        frame_scan = np.tile(frame_scan, (frame_repeats,1) )
    return frame_scan


def mask2positions_file(mask, filename:str, **kwargs):
    """
    Convert a mask to a xy file.

    Parameters
    ----------
    mask : np.ndarray
        A boolean array with the same shape as the image.
    filename : str
        The filename of the xy file.
    kwargs : dict
        Additional arguments for the `mask2positions` function.
    """
    frame_scan = mask2positions(mask, **kwargs)
    width = mask.shape[1]
    height = mask.shape[0]
    num_points = len(frame_scan)

    with open(filename, "w+") as f:
        f.write("[Metadata]\n")
        f.write(f"Width = {width}\n")
        f.write(f"Height = {height}\n")
        f.write(f"Points = {num_points}\n")
        f.write("[Pattern 0]\n")
        for point in frame_scan:
            f.write(f"    {point[1]},    {point[0]}\n")
    return frame_scan

class EditablePropertyLabel(QWidget):
    """A label that can be edited by the user and connects to some property that it can update/ can update it.

    The update_func should take a single argument, the new value and return True if the value was
    successfully updated, False otherwise.

    Parameters
    ----------
    label : str, optional
        The label to the left of the input field, by default ""
    dtype : dtype, optional
        The data type of the input field, by default str
    update_to_client_func : callable, optional
        The function to call when the value is updated, by default None.
        This function should take a single argument, the new value and
        return True if the value was successfully updated, False otherwise.
    update_from_client_func : callable, optional
        The function to call to get the current value from the client, by default None.
    parent : QWidget, optional
        The parent widget, by default None
    """
    def __init__(self,
                 label="",
                 default_value="",
                 dtype=dtype,
                 update_to_client_func=None,
                 update_from_client_func=None,
                 parent=None):

        super().__init__(parent)
        self.layout = QHBoxLayout()
        self.setLayout(self.layout)

        self.layout.addWidget(QLabel(f"{label}:"))
        # input field for x pixels
        self.input_field = EditableLabel(default_value)

        # type, update_to_client_func, update_from_client_func
        self.dtype = dtype
        self.update_to_client_func = update_to_client_func
        self.update_from_client_func = update_from_client_func

        self.input_field.editingFinished.connect(self.update_client)

    def update_client(self, value):
        update_successful = self.update_to_client_func(self.dtype(value))
        if not update_successful: # return to the previous value
            self.input_field.setText(self.input_field.previous_text)

    def update_from_client(self):
        if self.update_from_client_func is not None:
            value = self.update_from_client_func()
            self.input_field.setText(str(value))


class ParticleScanControlWidget(QGroupBox):
    """

    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # Scan parameters
        self.setTitle("Particle Scan Control")
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        scan_group = QGroupBox("Scan Control")
        scan_group.setMaximumHeight(60)
        scan_group.setLayout(QHBoxLayout())
        self.client = None
        # input fields for x, y, scan rep.
        set_x_pixels_func = lambda x: self.client.setitem("Scan - Size X", x)
        get_x_pixels_func = lambda: self.client.getitem("Scan - Size X")
        self.x_pixels_input = EditablePropertyLabel(label="X Points",
                                                    default_value="256",
                                                    dtype=int,
                                                    update_to_client_func=set_x_pixels_func,
                                                    update_from_client_func=get_x_pixels_func)
        scan_group.layout().addWidget(self.x_pixels_input)

        set_y_pixels_func = lambda x: self.client.setitem("Scan - Size Y", x)
        get_y_pixels_func = lambda: self.client.getitem("Scan - Size Y")
        self.y_pixels_input = EditablePropertyLabel(label="Y Points",
                                                    default_value="256",
                                                    dtype=int,
                                                    update_to_client_func=set_y_pixels_func,
                                                    update_from_client_func=get_y_pixels_func)

        scan_group.layout().addWidget(self.y_pixels_input)
        main_layout.addWidget(scan_group)

        # Particle Scan Folder
        scan_folder_layout = QHBoxLayout()
        self.scan_folder_label = QLabel("Scan Folder:")
        scan_folder_layout.addWidget(self.scan_folder_label)
        self.scan_folder_input = EditableLabel("")
        scan_folder_layout.addWidget(self.scan_folder_input)
        main_layout.addLayout(scan_folder_layout)

        # Scan modifiers [Average DP]
        scan_mod_layout = QHBoxLayout()
        self.average_dp_checkbox = QCheckBox("Average DP")
        scan_mod_layout.addWidget(self.average_dp_checkbox)

        main_layout.addLayout(scan_mod_layout)

        # Control buttons [Search] [Acquire]
        control_layout = QHBoxLayout()
        self.search_beam_button = QPushButton("Search HAADF")
        self.start_stop_button = QPushButton("Acquire")
        control_layout.addWidget(self.search_beam_button)
        control_layout.addWidget(self.start_stop_button)
        main_layout.addLayout(control_layout)

