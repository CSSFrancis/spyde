"""Stacked 1-D navigator lanes: one master, the rest followers.

The failure this pins is an interaction bug you cannot see in a screenshot and
cannot see in a synchronous unit test either — it needs the write-back to
arrive AFTER the drag handler has returned, which is exactly what
``_dispatch_to_main`` does in the app.

While a lane is being dragged its line is the MASTER. The selector's index hook
fires on the ``_NavDispatcher`` thread with the committed (index-quantised)
position and is marshalled onto the main thread, landing some milliseconds
later — by which time the synchronous ``_busy`` guard is long since false. If
that write-back touches the held line, it snaps back to the last committed
frame while the pointer is somewhere else, the next ``pointer_move`` drags it
forward again, and the cursor oscillates for the whole drag.
"""
from __future__ import annotations

import numpy as np
import pytest

from spyde.actions.navigator_views import _StackedNavCursor


class _FakeWidget:
    """A VLine stand-in. ``set`` fires ``pointer_move`` like the real one."""

    def __init__(self, x=0.0):
        self._x = float(x)
        self._handlers: dict[str, list] = {}

    def add_event_handler(self, fn, event_type):
        self._handlers.setdefault(event_type, []).append(fn)

    def get(self, key):
        assert key == "x"
        return self._x

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        self._x = float(value)

    def set(self, x=None, **_kw):
        if x is None:
            return
        self._x = float(x)
        # The real widget echoes a pointer_move on a programmatic set — the
        # whole reason _busy exists.
        self._fire("pointer_move")

    def _fire(self, event_type):
        for fn in list(self._handlers.get(event_type, ())):
            fn()

    def drag_to(self, x: float):
        self._x = float(x)
        self._fire("pointer_move")

    def release(self):
        self._fire("pointer_up")


class _FakeSelector:
    def __init__(self, scale=0.03276):
        self.index_hooks: list = []
        self._widget = _FakeWidget()
        self.current_indices = np.array([0])
        self.scale = scale
        self.updates = 0
        self.current_plot = self

    # `_selector_axis` reads current_plot.plot_state.current_signal…
    @property
    def plot_state(self):
        return self

    @property
    def current_signal(self):
        scale = self.scale

        class _Axis:
            pass

        ax = _Axis()
        ax.scale, ax.offset = scale, 0.0

        class _AM:
            signal_axes = [ax]

        class _Sig:
            axes_manager = _AM()

        return _Sig()

    def delayed_update_data(self, force=False):
        self.updates += 1


class _FakeSession:
    """Defers marshalled work, so a test can land it at a chosen moment —
    the app's ``_dispatch_to_main`` is likewise asynchronous."""

    def __init__(self):
        self.pending: list = []

    def _dispatch_to_main(self, fn):
        self.pending.append(fn)

    def flush(self):
        pending, self.pending = self.pending, []
        for fn in pending:
            fn()


@pytest.fixture
def stacked():
    session = _FakeSession()
    widgets = [_FakeWidget(), _FakeWidget(), _FakeWidget()]
    sel = _FakeSelector()
    cursor = _StackedNavCursor(session, 1, widgets, sel)
    return session, widgets, sel, cursor


class TestMasterFollower:
    def test_drag_mirrors_to_the_other_lanes(self, stacked):
        _session, widgets, sel, _cursor = stacked
        widgets[0].drag_to(4.2)
        assert [w.x for w in widgets] == [4.2, 4.2, 4.2]
        assert sel._widget.x == pytest.approx(4.2)
        assert sel.updates == 1

    def test_late_writeback_does_not_move_the_held_line(self, stacked):
        """THE regression: the index hook lands after the handler returned."""
        session, widgets, sel, cursor = stacked

        widgets[0].drag_to(4.2)          # user drags lane 0 to 4.2
        # The dispatcher commits frame 128 (128 * 0.03276 = 4.19328) and fires
        # the hook on its own thread; the write-back is marshalled.
        for hook in sel.index_hooks:
            hook(np.array([128]))
        widgets[0].drag_to(4.9)          # user keeps dragging BEFORE it lands
        session.flush()                  # …and now it lands

        assert widgets[0].x == pytest.approx(4.9), (
            "the held line was yanked back to the committed position"
        )
        # The followers do take the committed position — that is their job.
        assert widgets[1].x == pytest.approx(4.19328)
        assert widgets[2].x == pytest.approx(4.19328)

    def test_release_hands_the_master_role_back(self, stacked):
        """After pointer_up every line settles on the committed position."""
        session, widgets, sel, cursor = stacked

        widgets[0].drag_to(4.2)
        widgets[0].release()
        assert cursor._master is None

        for hook in sel.index_hooks:
            hook(np.array([128]))
        session.flush()

        assert [pytest.approx(w.x) for w in widgets] == [pytest.approx(4.19328)] * 3

    def test_only_one_master_at_a_time(self, stacked):
        """Mirroring fires the followers' own pointer_move handlers; they must
        not steal the master role from the line actually under the pointer."""
        _session, widgets, _sel, cursor = stacked
        widgets[1].drag_to(2.0)
        assert cursor._master is widgets[1]
        assert [w.x for w in widgets] == [2.0, 2.0, 2.0]

    def test_programmatic_move_with_no_drag_syncs_every_line(self, stacked):
        """Playback moves the selector with nobody dragging — all lanes follow."""
        session, widgets, sel, _cursor = stacked
        for hook in sel.index_hooks:
            hook(np.array([64]))
        session.flush()
        assert [pytest.approx(w.x) for w in widgets] == [pytest.approx(64 * 0.03276)] * 3

    def test_drag_does_not_re_enter_via_the_mirror_echo(self, stacked):
        """`set` echoes a pointer_move; one drag must drive the selector once."""
        _session, widgets, sel, _cursor = stacked
        widgets[2].drag_to(1.5)
        assert sel.updates == 1

    def test_close_releases_the_master_and_stops_syncing(self, stacked):
        session, widgets, sel, cursor = stacked
        widgets[0].drag_to(4.2)
        cursor.close()
        assert cursor._master is None
        assert sel.index_hooks == []
