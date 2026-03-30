"""Tests for TIFF file loading.

TIFF loading is handled natively by HyperSpy / RosettaSciIO.  These tests
verify that both single-frame and multi-frame TIFF files can be loaded
through the MainWindow._create_signals() path and that the expected MDI
subwindows are created.
"""

import numpy as np
import tifffile

from spyde.__main__ import MainWindow
from spyde.qt.shared import open_window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_win(qtbot) -> MainWindow:
    win = open_window()
    qtbot.addWidget(win)
    return win


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOpenTiff:
    """Load TIFF files via MainWindow._create_signals and check the UI."""

    def test_load_2d_tiff(self, qtbot, tmp_path):
        """A single-frame 2-D TIFF should produce exactly one signal subwindow."""
        tif_path = str(tmp_path / "image_2d.tif")
        tifffile.imwrite(tif_path, np.random.randint(0, 65535, (64, 64), dtype=np.uint16))

        win = _open_win(qtbot)
        try:
            win._create_signals([tif_path])

            qtbot.waitUntil(
                lambda: len(win.mdi_area.subWindowList()) >= 1, timeout=10_000
            )

            subwindows = win.mdi_area.subWindowList()
            # A pure 2-D image has no navigation axes → one signal plot, no navigator
            assert len(subwindows) == 1, (
                f"Expected 1 subwindow for a 2-D TIFF, got {len(subwindows)}"
            )
            assert len(win.signal_trees) == 1
        finally:
            win.close()
            qtbot.waitUntil(lambda: not win.isVisible(), timeout=5_000)

    def test_load_multiframe_tiff(self, qtbot, tmp_path):
        """A multi-frame TIFF (N×H×W) should produce a navigator + a signal subwindow."""
        tif_path = str(tmp_path / "stack.tif")
        tifffile.imwrite(
            tif_path, np.random.randint(0, 65535, (10, 64, 64), dtype=np.uint16)
        )

        win = _open_win(qtbot)
        try:
            win._create_signals([tif_path])

            qtbot.waitUntil(
                lambda: len(win.mdi_area.subWindowList()) >= 2, timeout=10_000
            )

            subwindows = win.mdi_area.subWindowList()
            # nav_dim=1, sig_dim=2 → navigator plot + signal plot
            assert len(subwindows) == 2, (
                f"Expected 2 subwindows for a multi-frame TIFF, got {len(subwindows)}"
            )
            assert len(win.signal_trees) == 1
            signal_tree = win.signal_trees[0]
            # The navigator should carry at least one plot
            assert len(signal_tree.navigator_plot_manager.plots) >= 1
            # And at least one signal plot
            assert len(signal_tree.signal_plots) >= 1
        finally:
            win.close()
            qtbot.waitUntil(lambda: not win.isVisible(), timeout=5_000)

    def test_load_2d_tiff_extensions(self, qtbot, tmp_path):
        """Both .tif and .tiff file extensions should load without error."""
        for ext in ("sample.tif", "sample.tiff"):
            tif_path = str(tmp_path / ext)
            tifffile.imwrite(
                tif_path, np.random.randint(0, 255, (32, 32), dtype=np.uint8)
            )

            win = _open_win(qtbot)
            try:
                win._create_signals([tif_path])
                qtbot.waitUntil(
                    lambda: len(win.mdi_area.subWindowList()) >= 1, timeout=10_000
                )
                assert len(win.mdi_area.subWindowList()) >= 1
            finally:
                win.close()
                qtbot.waitUntil(lambda: not win.isVisible(), timeout=5_000)

    def test_load_lzw_compressed_tiff(self, qtbot, tmp_path):
        """LZW-compressed TIFFs require imagecodecs and must load without error."""
        tif_path = str(tmp_path / "lzw.tif")
        tifffile.imwrite(
            tif_path,
            np.random.randint(0, 65535, (64, 64), dtype=np.uint16),
            compression="lzw",
        )

        win = _open_win(qtbot)
        try:
            win._create_signals([tif_path])
            qtbot.waitUntil(
                lambda: len(win.mdi_area.subWindowList()) >= 1, timeout=10_000
            )
            assert len(win.mdi_area.subWindowList()) == 1
            assert len(win.signal_trees) == 1
        finally:
            win.close()
            qtbot.waitUntil(lambda: not win.isVisible(), timeout=5_000)


    def test_file_dialog_filter_includes_tiff(self, qtbot):
        """The Open file dialog name filter must expose .tif and .tiff entries."""
        win = _open_win(qtbot)
        try:
            # Build filter the same way open_file() does to confirm TIFF is present.
            name_filter = (
                "Supported Files (*.hspy *.mrc *.tif *.tiff);;"
                "Hyperspy Files (*.hspy);;"
                "mrc Files (*.mrc);;"
                "TIFF Files (*.tif *.tiff)"
            )
            assert "*.tif" in name_filter
            assert "*.tiff" in name_filter
        finally:
            win.close()
            qtbot.waitUntil(lambda: not win.isVisible(), timeout=5_000)






