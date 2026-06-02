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


def test_generate_library():
    """_generate_library_from_phases returns a Simulation2D given valid phases."""
    from spyde.actions.pyxem import _generate_library_from_phases

    mock_sim = MagicMock()
    mock_generator_cls = MagicMock()
    mock_generator_cls.return_value.calculate_diffraction2d.return_value = mock_sim

    mock_rotations = MagicMock()
    mock_phase = MagicMock()
    mock_phase.point_group = MagicMock()

    with patch("spyde.actions.pyxem.SimulationGenerator", mock_generator_cls), \
         patch("spyde.actions.pyxem.get_sample_reduced_fundamental",
               return_value=mock_rotations):
        result = _generate_library_from_phases(
            phases=[mock_phase],
            accelerating_voltage=200.0,
            resolution=1.0,
            minimum_intensity=0.05,
            reciprocal_radius=0.64,
        )

    assert result is mock_sim
    mock_generator_cls.assert_called_once_with(200.0, minimum_intensity=0.05)
    mock_generator_cls.return_value.calculate_diffraction2d.assert_called_once()
    call_args = mock_generator_cls.return_value.calculate_diffraction2d.call_args
    assert call_args[0][0] is mock_phase
    assert call_args[1]["rotation"] is mock_rotations
    assert call_args[1]["with_direct_beam"] is False


def test_filter_sim_by_radius():
    """Spots beyond max_radius are excluded from the filtered simulation."""
    from spyde.actions.pyxem import _filter_sim_by_radius

    coords = np.array([[0.1, 0.2], [0.3, 0.3], [0.6, 0.0], [0.0, 0.8]])
    intensities = np.array([1.0, 0.8, 0.5, 0.3])

    filtered_coords, filtered_intensities = _filter_sim_by_radius(
        coords, intensities, max_radius=0.5
    )
    assert len(filtered_coords) == 2
    assert len(filtered_intensities) == 2
    assert np.allclose(filtered_coords, coords[:2])
    assert np.allclose(filtered_intensities, intensities[:2])
    # boundary case: point exactly at radius should be included
    coords_boundary = np.array([[0.5, 0.0]])
    intensities_boundary = np.array([1.0])
    fc, fi = _filter_sim_by_radius(coords_boundary, intensities_boundary, 0.5)
    assert len(fc) == 1
