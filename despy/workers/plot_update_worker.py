from PySide6 import QtCore

from typing import Callable, Optional, Set

from dask.distributed import Future


class PlotUpdateWorker(QtCore.QObject):
    """
    Worker that periodically scans plots for completed Dask Futures and emits results.
    Runs in its own thread; GUI updates happen via a signal on the main thread.
    """
    plot_ready = QtCore.Signal(object, object)  # (plot, result)

    def __init__(
        self,
        get_plots_callable: Callable[[], list["Plot"]],
        interval_ms: int = 20,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._get_plots = get_plots_callable
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check)
        self._seen: Set[int] = set()  # prevent duplicate emits for the same Future

    @QtCore.Slot()
    def start(self) -> None:
        """Start polling in the worker thread."""
        self._timer.start()

    @QtCore.Slot()
    def stop(self) -> None:
        """Stop polling and clear seen cache."""
        self._timer.stop()
        self._seen.clear()

    @QtCore.Slot()
    def _check(self) -> None:
        """Poll plots for completed Futures and emit results."""
        try:
            plots = self._get_plots() or []
        except Exception:
            plots = []
        for p in plots:
            try:
                fut = getattr(p, "current_data", None)
                if isinstance(fut, Future) and fut.done():
                    fid = id(fut)
                if fid in self._seen:
                    continue
                self._seen.add(fid)
                try:
                    result = fut.result()
                except Exception as e:
                    result = e
                self.plot_ready.emit(p, result)
            except Exception:
                # Keep worker resilient to individual plot errors
                pass