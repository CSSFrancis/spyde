import pytest
from typing import Dict, Union, List, Iterator

from spyde.qt.shared import open_window as _open_window
from spyde.qt.shared import create_data as _create_data
from spyde.__main__ import MainWindow
from spyde.drawing.plots.plot import Plot
from spyde.signal_tree import BaseSignalTree
from PySide6.QtWidgets import QMdiArea


def _close_window(qtbot, win) -> None:
    win.close()
    qtbot.waitUntil(lambda: not win.isVisible(), timeout=2000)


@pytest.fixture()
def tem_2d_dataset(
    qtbot,
) -> Iterator[Dict[str, Union[MainWindow, QMdiArea, List[Plot], List[BaseSignalTree]]]]:
    win = _open_window()
    _create_data(win, "Image")
    # Wait for 1 subwindow
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 1, timeout=5000)
    try:
        yield {
            "window": win,
            "mdi_area": win.mdi_area,
            "subwindows": win.mdi_area.subWindowList(),
            "signal_trees": getattr(win, "signal_trees", []),
        }
    finally:
        _close_window(qtbot, win)


@pytest.fixture
def insitu_tem_2d_dataset(
    qtbot,
) -> Iterator[Dict[str, Union[MainWindow, QMdiArea, List[Plot], List[BaseSignalTree]]]]:
    win = _open_window()
    _create_data(win, "Insitu TEM")
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)
    try:
        yield {
            "window": win,
            "mdi_area": win.mdi_area,
            "subwindows": win.mdi_area.subWindowList(),
            "signal_trees": getattr(win, "signal_trees", []),
        }
    finally:
        _close_window(qtbot, win)


@pytest.fixture
def stem_4d_dataset(
    qtbot,
) -> Iterator[Dict[str, Union[MainWindow, QMdiArea, List[Plot], List[BaseSignalTree]]]]:
    win = _open_window()
    _create_data(win, "4D STEM")
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)
    try:
        yield {
            "window": win,
            "mdi_area": win.mdi_area,
            "subwindows": win.mdi_area.subWindowList(),
            "signal_trees": getattr(win, "signal_trees", []),
        }
    finally:
        _close_window(qtbot, win)


@pytest.fixture
def stem_5d_dataset(
    qtbot,
) -> Iterator[Dict[str, Union[MainWindow, QMdiArea, List[Plot], List[BaseSignalTree]]]]:
    win = _open_window()
    _create_data(win, "5D STEM")
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 3, timeout=10000)
    try:
        yield {
            "window": win,
            "mdi_area": win.mdi_area,
            "subwindows": win.mdi_area.subWindowList(),
            "signal_trees": getattr(win, "signal_trees", []),
        }
    finally:
        _close_window(qtbot, win)
