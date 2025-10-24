
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from despy.drawing.toolbars import RoundedToolBar


ZOOM_STEP = 0.8


def zoom_in(toolbar: "RoundedToolBar"):
    """
    Zoom in action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to zoom in.
    """
    vb = toolbar.plot.plot_item.getViewBox()
    vb.scaleBy((ZOOM_STEP, ZOOM_STEP))


def zoom_out(toolbar: "RoundedToolBar"):
    """
    Zoom out action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to zoom out.
    """
    vb = toolbar.plot.plot_item.getViewBox()
    factor = 1.0 / ZOOM_STEP
    vb.scaleBy((factor, factor))


def reset_view(toolbar: "RoundedToolBar"):
    """
    Reset view action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to reset the view.
    """
    vb = toolbar.plot.plot_item.getViewBox()
    vb.autoRange()


def add_selector(toolbar: "RoundedToolBar"):
    """
    Add selector action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to add the selector.
    """
    toolbar.plot.nav_plot_manager.add_navigation_selector_and_signal_plot()


def add_fft_selector(toolbar: "RoundedToolBar"):
    """
    Add FFT selector action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to add the FFT selector.
    """
    toolbar.plot.add_fft_selector()


def toggle_navigation_plots(toolbar: "RoundedToolBar"):
    """
    Makes a series of buttons to the side of the action bar for toggling/ adding
    additional navigation plots.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to toggle navigation plots.
    """
    if toolbar.plot.nav_plot_manager is None:
        raise RuntimeError("Plot does not have a navigation plot manager.")

    signal_options = toolbar.plot.nav_plot_manager.navigation_signals

