
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from despy.drawing.multiplot import Plot


ZOOM_STEP = 0.8


def zoom_in(plot: "Plot"):
    """
    Zoom in action for the plot.

    Parameters
    ----------
    plot : Plot
        The plot to zoom in.
    """
    vb = plot.plot_item.getViewBox()
    vb.scaleBy((ZOOM_STEP, ZOOM_STEP))


def zoom_out(plot: "Plot"):
    """
    Zoom out action for the plot.

    Parameters
    ----------
    plot : Plot
        The plot to zoom out.
    """
    vb = plot.plot_item.getViewBox()
    factor = 1.0 / ZOOM_STEP
    vb.scaleBy((factor, factor))


def reset_view(plot: "Plot"):
    """
    Reset view action for the plot.

    Parameters
    ----------
    plot : Plot
        The plot to reset the view.
    """
    vb = plot.plot_item.getViewBox()
    vb.autoRange()


def add_selector(plot: "Plot"):
    """
    Add selector action for the plot.

    Parameters
    ----------
    plot : Plot
        The plot to add the selector.
    """
    plot.nav_plot_manager.add_navigation_selector_and_signal_plot()


def add_fft_selector(plot: "Plot"):
    """
    Add FFT selector action for the plot.

    Parameters
    ----------
    plot : Plot
        The plot to add the FFT selector.
    """
    plot.add_fft_selector()