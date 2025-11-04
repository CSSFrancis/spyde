from spyde.drawing.toolbars.rounded_toolbar import RoundedToolBar
from spyde.drawing.selector import RectangleSelector
from typing import Tuple

def center_zero_beam(toolbar: RoundedToolBar,
                     make_flat_field: bool = False,
                     method: str = "com",
                     signal_slice: Tuple[int, int, int, int] = None,
                     action_name: str = "Center zero-beam",
                     *args, **kwargs
                     ):
    """
    Center the zero-beam of a 4D STEM dataset by a couple of different methods.

    Parameters
    ----------
    toolbar : spyde.plugins.toolbar.Toolbar
        The toolbar instance from which to get the current signal.
    selector : spyde.plugins.selector.Selector
        The selector instance from which to get the current signal.

    """

    print("Centering zero-beam...")
    print("arguments:", make_flat_field, method)
    print("kwargs", kwargs)
    print("args", args)

    signal = toolbar.plot.plot_state.current_signal
    if signal is None:
        print("No signal selected.")
        return

    signal.set_signal_type("electron_diffraction")

    sl = (signal_slice[0], signal_slice[0]+signal_slice[2], signal_slice[1], signal_slice[1]+signal_slice[3])

    shifts = signal.get_direct_beam_position(method=method, signal_slice=sl, **kwargs)

    print(make_flat_field)
    if make_flat_field:
        if shifts._lazy:
            shifts.compute()
        shifts.get_linear_plane()

    new_signal = toolbar.plot.signal_tree.add_transformation(parent_signal=signal,
                                                node_name="Centered",
                                                method="center_direct_beam",
                                                shifts=shifts,
                                                inplace=False)
    print("Done centering zero-beam.")

    toolbar.plot.set_plot_state(new_signal)




