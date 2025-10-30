import importlib
from typing import TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from despy.drawing.multiplot import Plot

from despy import TOOLBAR_ACTIONS

from functools import partial


def resolve_icon_path(icon_value: str) -> str:
    # Keep Qt resource paths (e.g., ":/icons/foo.png") as-is
    if isinstance(icon_value, str) and icon_value.startswith(":"):
        return icon_value

    p = Path(icon_value)
    if p.is_absolute():
        return str(p)

    # Resolve relative to the despy package directory
    try:
        import despy
        base = Path(despy.__file__).resolve().parent
    except Exception:
        base = Path(__file__).resolve().parent

    return str((base / icon_value).resolve())

def get_toolbar_actions_for_plot(plot: "Plot"):
    functions = []
    icons = []
    names = []
    toolbar_sides = []
    toggles = []
    parameters = []

    for action in TOOLBAR_ACTIONS["functions"]:

        signal_types = TOOLBAR_ACTIONS["functions"][action].get('signal_types', None)
        plot_dim = TOOLBAR_ACTIONS["functions"][action].get('plot_dim', [1, 2])
        navigation_only = TOOLBAR_ACTIONS["functions"][action].get('navigation', None)
        params = TOOLBAR_ACTIONS["functions"][action].get('parameters', {})

        plot_signal_type = plot.plot_state.current_signal._signal_type

        add_action = ((signal_types is None or plot_signal_type in signal_types) and
                      (plot.plot_state.dimensions in plot_dim) and
                      (navigation_only is None or navigation_only == plot.is_navigator))

        if add_action:
            print(f"Adding toolbar action: {action}")
            function = TOOLBAR_ACTIONS["functions"][action]['function']
            module_path, _, attr = function.rpartition('.')
            resolved_func = getattr(importlib.import_module(module_path), attr)

            print(f"Resolved function: {TOOLBAR_ACTIONS["functions"][action]}")
            print("toggle is ", TOOLBAR_ACTIONS["functions"][action].get('toggle', False))
            resolved_func = partial(resolved_func,
                                    action_name=action,
                                    )
            functions.append(resolved_func)
            icons.append(resolve_icon_path(TOOLBAR_ACTIONS["functions"][action]['icon']))
            names.append(action)
            toolbar_sides.append(TOOLBAR_ACTIONS["functions"][action].get('toolbar_side', 'left'))
            toggles.append(TOOLBAR_ACTIONS["functions"][action].get('toggle', False))
            parameters.append(params)

    return functions, icons, names, toolbar_sides, toggles, parameters


