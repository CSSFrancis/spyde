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


def _make_mock_toolbar(qtbot):
    """Build a minimal mock toolbar that orientation_mapping expects.

    orientation_mapping now reads the caret from toolbar.action_widgets (set by
    the toolbar infrastructure from YAML) rather than calling toolbar.add_action
    itself. We set up a real CaretParams widget as the caret so layout manipulation
    inside orientation_mapping works correctly.
    """
    from PySide6 import QtWidgets
    from spyde.drawing.toolbars.caret_group import CaretParams

    toolbar = MagicMock()
    plot = MagicMock()
    signal = MagicMock()
    ax0 = MagicMock(); ax0.scale = 0.01; ax0.size = 128; ax0.offset = 0.0
    ax1 = MagicMock(); ax1.scale = 0.01; ax1.size = 128; ax1.offset = 0.0
    signal.axes_manager.signal_axes = [ax0, ax1]
    signal.axes_manager.navigation_axes = []
    plot.plot_state.current_signal = signal
    plot.main_window = MagicMock()
    toolbar.plot = plot

    # Simulate what _create_parameter_popout does: caret stored in action_widgets
    caret = CaretParams(parameters={})
    qtbot.addWidget(caret)
    toolbar.action_widgets = {"Orientation Mapping": {"widget": caret}}
    toolbar._om_state = None  # no prior state
    return toolbar, caret


def test_orientation_mapping_builds_ui(qtbot):
    from spyde.actions.pyxem import orientation_mapping
    toolbar, caret = _make_mock_toolbar(qtbot)
    orientation_mapping(toolbar, action_name="Orientation Mapping")
    # State should be stored on toolbar after first call
    assert hasattr(toolbar, "_om_state")
    assert toolbar._om_state is not None
    # Caret layout should have content (step bar + stack)
    assert caret.layout().count() > 0


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


def test_extract_orientation_map_outputs():
    """_extract_orientation_outputs returns a list of (signal, title) tuples."""
    from spyde.actions.pyxem import _extract_orientation_outputs

    mock_om = MagicMock()
    mock_om.correlation = MagicMock()
    mock_om.correlation.data = np.zeros((4, 4))
    mock_om.mirror_symmetry = MagicMock()
    mock_om.mirror_symmetry.data = np.zeros((4, 4))
    mock_om.phase_index = MagicMock()
    mock_om.phase_index.data = np.zeros((4, 4), dtype=int)

    nav_axes = []

    results = _extract_orientation_outputs(mock_om, nav_axes, n_phases=2)
    titles = [r[1] for r in results]
    assert "Orientation Map" in titles
    assert "Correlation Score" in titles
    assert "Mirror Symmetry" in titles
    assert "Phase Map" in titles
    assert len(results) == 4

    # Single-phase: Phase Map should not be in results
    results_single = _extract_orientation_outputs(mock_om, nav_axes, n_phases=1)
    titles_single = [r[1] for r in results_single]
    assert "Phase Map" not in titles_single
    assert len(results_single) == 3
