"""Verify the session-scoped window is reused across tests."""


def test_session_window_identity_a(stem_4d_dataset):
    """Record the MainWindow id from first fixture call."""
    win = stem_4d_dataset["window"]
    import spyde.tests.test_fixture_session as _self
    _self._win_id = id(win)


def test_session_window_identity_b(stem_4d_dataset):
    """Verify second fixture call returns the same MainWindow instance."""
    import spyde.tests.test_fixture_session as _self
    win = stem_4d_dataset["window"]
    assert id(win) == _self._win_id, (
        "stem_4d_dataset must return the same MainWindow instance each time"
    )


def test_reset_clears_subwindows_a(tem_2d_dataset):
    """After loading a 2D dataset, there should be exactly 1 subwindow."""
    win = tem_2d_dataset["window"]
    assert len(win.mdi_area.subWindowList()) == 1, (
        f"Expected 1 subwindow after 2D dataset load, got {len(win.mdi_area.subWindowList())}"
    )


def test_reset_clears_subwindows_b(stem_4d_dataset):
    """After switching to 4D STEM dataset, old subwindows must be gone."""
    win = stem_4d_dataset["window"]
    assert len(win.mdi_area.subWindowList()) == 2, (
        f"Expected 2 subwindows after 4D STEM load, got {len(win.mdi_area.subWindowList())}"
    )
    assert len(win.signal_trees) == 1, (
        f"Expected 1 signal tree after reset, got {len(win.signal_trees)}"
    )
