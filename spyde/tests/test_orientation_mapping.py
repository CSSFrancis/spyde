# spyde/tests/test_orientation_mapping.py
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from pytestqt.qtbot import QtBot
from spyde.drawing.toolbars.caret_group import CaretParams
from PySide6 import QtWidgets


def test_file_drop_widget_created(qtbot):
    params = {
        "cif_files": {
            "name": "CIF Files",
            "type": "file_drop",
            "extensions": [".cif"],
        }
    }
    widget = CaretParams(parameters=params)
    qtbot.addWidget(widget)
    # The kwargs entry should be a QWidget (the file drop widget)
    assert "cif_files" in widget.kwargs
    drop_widget = widget.kwargs["cif_files"]
    assert hasattr(drop_widget, "get_files")
    assert drop_widget.get_files() == []


def _make_mock_toolbar():
    """Build a minimal mock toolbar that orientation_mapping expects."""
    toolbar = MagicMock()
    plot = MagicMock()
    signal = MagicMock()
    ax0 = MagicMock(); ax0.scale = 0.01; ax0.size = 128
    ax1 = MagicMock(); ax1.scale = 0.01; ax1.size = 128
    signal.axes_manager.signal_axes = [ax0, ax1]
    signal.axes_manager.navigation_axes = []
    plot.plot_state.current_signal = signal
    plot.main_window = MagicMock()
    plot.main_window.dask_manager.client = MagicMock()
    plot.main_window.dask_manager.gpu_worker_address = None
    toolbar.parent_toolbar.plot = plot
    toolbar.plot = plot
    toolbar.num_actions.return_value = 0
    toolbar.add_action.return_value = (MagicMock(), MagicMock())
    return toolbar


def test_orientation_mapping_creates_action(qtbot):
    from spyde.actions.pyxem import orientation_mapping
    toolbar = _make_mock_toolbar()
    orientation_mapping(toolbar, action_name="Orientation Mapping")
    toolbar.add_action.assert_called_once()
    assert toolbar.add_action.call_args[1]["name"] == "Orientation Mapping"
