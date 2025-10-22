import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from despy.drawing.multiplot import Plot

from despy import TOOLBAR_ACTIONS


def get_toolbar_actions_for_plot(plot: "Plot"):
    functions = []
    icons = []
    names = []
    toolbar_sides = []

    for action in TOOLBAR_ACTIONS["functions"]:

        signal_types = TOOLBAR_ACTIONS["functions"][action].get('signal_types', None)
        plot_dim = TOOLBAR_ACTIONS["functions"][action].get('plot_dim', [1, 2])
        navigation_only = TOOLBAR_ACTIONS["functions"][action].get('navigation', None)

        plot_signal_type = plot.plot_state.current_signal._signal_type

        add_action = ((signal_types is None or plot_signal_type in signal_types) and
                      (plot.plot_state.dimensions in plot_dim) and
                      (navigation_only is None or navigation_only == plot.is_navigator))

        print("Add Action", add_action)
        print(action)
        if add_action:
            print(f"Adding toolbar action: {action}")
            function = TOOLBAR_ACTIONS["functions"][action]['function']
            module_path, _, attr = function.rpartition('.')
            resolved_func = getattr(importlib.import_module(module_path), attr)

            functions.append(resolved_func)
            icons.append(TOOLBAR_ACTIONS["functions"][action]['icon'])
            names.append(action)
            toolbar_sides.append(TOOLBAR_ACTIONS["functions"][action].get('toolbar_side', 'left'))

    return functions, icons, names, toolbar_sides


