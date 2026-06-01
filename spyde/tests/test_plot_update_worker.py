import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from spyde.workers.plot_update_worker import PlotUpdateWorker


def _make_done_future(value=None, key="test_key"):
    fut = MagicMock()
    fut.done.return_value = True
    fut.result.return_value = value if value is not None else np.zeros((4, 4))
    fut.key = key
    return fut


def _make_pending_future():
    fut = MagicMock()
    fut.done.return_value = False
    fut.key = "pending_key"
    return fut


class TestPlotUpdateWorker:
    def test_emits_plot_ready_when_future_done(self, qtbot):
        fut = _make_done_future(key="done_key")
        plot = MagicMock()
        plot.current_data = fut
        plot.plot_state = MagicMock()
        plot.plot_state.current_signal = MagicMock()
        plot.plot_state.current_signal.data = None

        worker = PlotUpdateWorker(get_plots_callable=lambda: [plot], interval_ms=5)

        received = []
        worker.plot_ready.connect(lambda p, r, fid: received.append((p, r, fid)))

        # Patch Future so MagicMock passes isinstance check
        with patch("spyde.workers.plot_update_worker.Future", type(fut)):
            with qtbot.waitSignal(worker.plot_ready, timeout=1000):
                worker._check()

        assert len(received) == 1
        assert received[0][0] is plot

    def test_skips_pending_future(self, qtbot):
        fut = _make_pending_future()
        plot = MagicMock()
        plot.current_data = fut
        plot.plot_state = MagicMock()
        plot.plot_state.current_signal = MagicMock()
        plot.plot_state.current_signal.data = None

        worker = PlotUpdateWorker(get_plots_callable=lambda: [plot], interval_ms=5)
        received = []
        worker.plot_ready.connect(lambda p, r, fid: received.append((p, r, fid)))

        with patch("spyde.workers.plot_update_worker.Future", type(fut)):
            worker._check()

        assert len(received) == 0

    def test_deduplicates_same_future(self, qtbot):
        fut = _make_done_future(key="dup_key")
        plot = MagicMock()
        plot.current_data = fut
        plot.plot_state = MagicMock()
        plot.plot_state.current_signal = MagicMock()
        plot.plot_state.current_signal.data = None

        worker = PlotUpdateWorker(get_plots_callable=lambda: [plot], interval_ms=5)
        received = []
        worker.plot_ready.connect(lambda p, r, fid: received.append((p, r, fid)))

        with patch("spyde.workers.plot_update_worker.Future", type(fut)):
            worker._check()
            worker._check()  # second call — same future, already seen

        assert len(received) == 1

    def test_handles_exception_in_future(self, qtbot):
        fut = MagicMock()
        fut.done.return_value = True
        fut.result.side_effect = RuntimeError("compute failed")
        fut.key = "err_key"

        plot = MagicMock()
        plot.current_data = fut
        plot.plot_state = MagicMock()
        plot.plot_state.current_signal = MagicMock()
        plot.plot_state.current_signal.data = None

        worker = PlotUpdateWorker(get_plots_callable=lambda: [plot], interval_ms=5)
        received = []
        worker.plot_ready.connect(lambda p, r, fid: received.append((p, r, fid)))

        with patch("spyde.workers.plot_update_worker.Future", type(fut)):
            worker._check()  # must not raise

        assert len(received) == 1
        assert isinstance(received[0][1], RuntimeError)
