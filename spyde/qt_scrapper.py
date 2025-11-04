from __future__ import annotations
import os
import logging
from typing import List
from PySide6 import QtWidgets, QtTest

from spyde.qt.shared import (
    ensure_app,
    iter_registered_windows,
    clear_registered_windows,
    grab_and_save,
)
from sphinx_gallery.scrapers import figure_rst

logger = logging.getLogger(__name__)


def qt_sg_scraper(block, block_vars, gallery_conf) -> List[str]:
    """
    Sphinx-Gallery image scraper for Qt.
    Strategy:
      1) Use explicitly registered windows, if any.
      2) Otherwise, capture all visible QMainWindow/QDialog top-levels.
    Saves to the 'image_path' prefix provided by Sphinx-Gallery.
    """

    logger.debug("Qt scraper activated!!")
    ensure_app()
    QtWidgets.QApplication.processEvents()
    QtTest.QTest.qWait(50)
    logger.debug("Qt scraper after wait")

    # Preferred: explicitly registered windows
    targets = list(iter_registered_windows())
    logger.debug("Registered windows found: %s", targets)

    # Fallback: visible top-level windows (main windows and dialogs)
    if not targets:
        logger.debug("Falling back to top-level visible windows")
        for w in QtWidgets.QApplication.topLevelWidgets():
            if (
                isinstance(w, (QtWidgets.QMainWindow, QtWidgets.QDialog))
                and w.isVisible()
            ):
                targets.append(w)
    logger.debug("Total target windows to capture: %d", len(targets))

    saved: List[str] = []
    image_path_iterator = block_vars["image_path_iterator"]

    # Normalize base without extension; append _N.png
    for image, image_path in zip(targets, image_path_iterator):
        saved.append(grab_and_save(image, image_path))

    # Reset registry between blocks
    clear_registered_windows()
    logger.debug("Stored images: %s", saved)
    logger.info("Qt scraper saved %d images.", len(saved))
    return figure_rst(saved, gallery_conf["src_dir"])
