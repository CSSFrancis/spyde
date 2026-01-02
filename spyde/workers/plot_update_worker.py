import time

import numpy as np
from PySide6 import QtCore

from typing import Callable, Optional, Set, Dict

from dask.distributed import Future
from spyde.drawing.update_functions import read_shared_array

class PlotUpdateWorker(QtCore.QObject):
    """
    Worker that periodically scans plots for completed Dask Futures and emits results.
    Runs in its own thread; GUI updates happen via a signal on the main thread.
    """

    plot_ready = QtCore.Signal(object, object, object)  # (plot, result, fid)
    signal_ready = QtCore.Signal(object, object, object)  # (signal, result)
    debug_print = QtCore.Signal(str)  # debug messages routed to main thread

    def __init__(
        self,
        get_plots_callable: Callable[[], list["Plot"]],
        interval_ms: int = 2,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._seen_plots: Dict[int:int] = dict()
        self._get_plots = get_plots_callable
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check)
        self._seen: Set[int] = set()  # prevent duplicate emits for the same Future
        # Flag used to request a clean shutdown from outside the worker thread
        self._quit_requested = False

    @QtCore.Slot()
    def start(self) -> None:
        """Start polling in the worker thread."""
        self._quit_requested = False
        if not self._timer.isActive():
            self._timer.start()

    @QtCore.Slot()
    def stop(self) -> None:
        """
        Request the worker to stop.

        Note:
            This slot runs in the worker's thread (when invoked via queued connection).
            Call it from other threads using QtCore.QMetaObject.invokeMethod or a signal.
        """
        self._quit_requested = True
        if self._timer.isActive():
            self._timer.stop()
        self._seen.clear()

    @QtCore.Slot()
    def _check(self) -> None:
        if self._quit_requested:
            if self._timer.isActive():
                self._timer.stop()
            return

        try:
            plots = self._get_plots() or []
        except Exception:
            plots = []

        for plot in plots:
            self._maybe_emit_plot_ready(plot)
            self._maybe_emit_signal_ready(plot)

    def _maybe_emit_plot_ready(self, plot: "Plot") -> None:
        try:
            fut = getattr(plot, "current_data", None)
            self._maybe_emit_future(fut, self.plot_ready.emit, plot)
        except Exception:
            pass

    def _maybe_emit_signal_ready(self, plot: "Plot") -> None:
        try:
            sig = getattr(plot.plot_state, "current_signal", None)
            if sig is None:
                return
            fut = self._future_from_signal(sig)
            self._maybe_emit_future(fut, self.signal_ready.emit, sig, plot)
        except Exception:
            pass

    def _future_from_signal(self, sig) -> Optional[Future]:
        data = getattr(sig, "data", None)
        if isinstance(data, Future):
            return data
        if isinstance(data, (list, tuple, np.ndarray)) and data and isinstance(data[0], Future):
            return data[0]
        return None

    def _maybe_emit_future(
        self,
        fut: Optional[Future],
        emitter: Callable[[object, object, Optional[object]], None],
        plot: Optional["Plot"] = None,
    ) -> None:
        if not isinstance(fut, Future) or not fut.done():
            return
        fid = id(fut)
        if fid in self._seen and self._seen_plots.get(fid, None) == id(plot):
            return
        self._seen.add(fid)
        self._seen_plots[fid] = id(plot)
        try:
            self.debug_print.emit(
                f"Emitting Future, {fut.key} for plot: {plot}")  # avoid blocking on shared arrays
            if "write_shared_array" in fut.key and plot is not None:
                start_read = time.time()
                result  = read_shared_array(plot.shared_memory)
                self.debug_print.emit(f"Read shared array in {(time.time() - start_read)*1000:.2f} ms")  # avoid blocking on shared arrays
            else:
                start_transfer = time.time()
                result = fut.result()
                self.debug_print.emit(f"Transferred Future over TCP in {(time.time() - start_transfer)*1000:.2f} ms")
        except Exception as e:
            result = e
        emitter(plot, result, fid)
