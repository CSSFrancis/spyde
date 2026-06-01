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
