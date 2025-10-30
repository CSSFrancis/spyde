from __future__ import annotations
import os
from typing import List
from PySide6 import QtWidgets, QtTest

from spyde.qt.shared import ensure_app, iter_registered_windows, clear_registered_windows, grab_and_save

def qt_sg_scraper(block, block_vars, gallery_conf) -> List[str]:
    """
    Sphinx-Gallery image scraper for Qt.
    Strategy:
      1) Use explicitly registered windows, if any.
      2) Otherwise, capture all visible QMainWindow/QDialog top-levels.
    Saves to the 'image_path' prefix provided by Sphinx-Gallery.
    """
    ensure_app()
    QtWidgets.QApplication.processEvents()
    QtTest.QTest.qWait(50)

    # Preferred: explicitly registered windows
    targets = list(iter_registered_windows())

    # Fallback: visible top-level windows (main windows and dialogs)
    if not targets:
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(w, (QtWidgets.QMainWindow, QtWidgets.QDialog)) and w.isVisible():
                targets.append(w)

    saved: List[str] = []
    base = block_vars.get("image_path", "")
    if not base:
        return saved

    # Normalize base without extension; append _N.png
    root, _ = os.path.splitext(base)
    for i, w in enumerate(targets):
        path = f"{root}_{i}.png"
        saved.append(grab_and_save(w, path))

    # Reset registry between blocks
    clear_registered_windows()
    return saved