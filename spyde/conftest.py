import pytest
from typing import Dict, Any

from spyde.qt.shared import open_window as _open_window
from spyde.qt.shared import create_data as _create_data


@pytest.fixture()
def tem_2d_dataset(qtbot) -> Dict[str, Any]:
    win = _open_window()
    _create_data(win, "Image")
    # Wait for 1 subwindow
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 1, timeout=5000)
    return {
        "window": win,
        "mdi_area": win.mdi_area,
        "subwindows": win.mdi_area.subWindowList(),
        "signal_trees": getattr(win, "signal_trees", []),
    }


@pytest.fixture
def insitu_tem_2d_dataset(qtbot) -> Dict[str, Any]:
    win = _open_window()
    _create_data(win, "Insitu TEM")
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)
    return {
        "window": win,
        "mdi_area": win.mdi_area,
        "subwindows": win.mdi_area.subWindowList(),
        "signal_trees": getattr(win, "signal_trees", []),
    }


@pytest.fixture
def stem_4d_dataset(qtbot) -> Dict[str, Any]:
    win = _open_window()
    _create_data(win, "4D STEM")
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)
    return {
        "window": win,
        "mdi_area": win.mdi_area,
        "subwindows": win.mdi_area.subWindowList(),
        "signal_trees": getattr(win, "signal_trees", []),
    }
