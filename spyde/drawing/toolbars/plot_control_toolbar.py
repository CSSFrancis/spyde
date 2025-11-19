from __future__ import annotations
import importlib
from typing import TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from spyde.drawing.plot_states import PlotState

from spyde import TOOLBAR_ACTIONS

from functools import partial


def resolve_icon_path(icon_value: str) -> str:
    """Resolve an icon specification into an absolute path or Qt resource path."""
    # Keep Qt resource paths (e.g., ":/icons/foo.png") as-is
    if isinstance(icon_value, str) and icon_value.startswith(":"):
        return icon_value

    p = Path(icon_value)
    if p.is_absolute():
        return str(p)

    # Resolve relative to the spyde package directory
    try:
        import spyde

        base = Path(spyde.__file__).resolve().parent
    except Exception:
        base = Path(__file__).resolve().parent

    return str((base / icon_value).resolve())


def get_toolbar_actions_for_plot(
    plot_state: "PlotState",
) -> tuple[
    list, list[str], list[str], list[str], list[bool], list[dict], list[list[tuple]]
]:
    """
    Build the action metadata lists for a given PlotState by filtering TOOLBAR_ACTIONS.

    Returns
    -------
    (functions, icons, names, toolbar_sides, toggles, parameters, sub_toolbars)
      functions: list[Callable] (each partially applied with action_name)
      icons: list[str] (resolved icon paths)
      names: list[str] (action identifiers)
      toolbar_sides: list[str] ("left"/"right"/"top"/"bottom")
      toggles: list[bool] (whether action is checkable)
      parameters: list[dict] (parameter definitions for CaretParams popouts)
      sub_toolbars: list[list[tuple]] (each inner list holds sub-action tuples)
    """
    functions = []
    icons = []
    names = []
    toolbar_sides = []
    toggles = []
    parameters = []
    sub_toolbars = []  # Parallel list: each entry is a list of subfunction tuples

    for action, meta in TOOLBAR_ACTIONS["functions"].items():
        signal_types = meta.get("signal_types")
        plot_dim = meta.get("plot_dim", [1, 2])
        navigation_only = meta.get("navigation")
        params = meta.get("parameters", {})

        plot_signal_type = plot_state.current_signal._signal_type

        add_action = (
            (signal_types is None or plot_signal_type in signal_types)
            and (plot_state.dimensions in plot_dim)
            and (
                navigation_only is None
                or navigation_only == plot_state.plot.is_navigator
            )
        )

        if not add_action:
            continue

        function_path = meta["function"]
        module_path, _, attr = function_path.rpartition(".")
        base_func = getattr(importlib.import_module(module_path), attr)
        wrapped_func = partial(base_func, action_name=action)
        functions.append(wrapped_func)
        icons.append(resolve_icon_path(meta["icon"]))
        names.append(action)
        toolbar_sides.append(meta.get("toolbar_side", "left"))
        toggles.append(meta.get("toggle", False))
        parameters.append(params)

        # Collect optional subfunctions
        sub_defs = meta.get("subfunctions", {})
        sub_entries = []
        for sub_meta in sub_defs:
            print(sub_meta)
            print(sub_defs)
            sub_function_path = sub_defs[sub_meta]["function"]
            sub_module_path, _, sub_attr = sub_function_path.rpartition(".")
            sub_func = getattr(importlib.import_module(sub_module_path), sub_attr)
            sub_func = partial(sub_func, action_name=sub_meta)
            sub_entries.append(
                (
                    sub_func,
                    resolve_icon_path(
                        sub_defs[sub_meta].get("icon", meta.get("icon", ""))
                    ),
                    sub_defs[sub_meta].get("name", sub_meta),
                    sub_defs[sub_meta].get("toggle", False),
                    sub_defs[sub_meta].get("parameters", {}),
                )
            )
            print("Sub Entries", sub_entries)
        sub_toolbars.append(sub_entries)
        print("SubTB:", sub_toolbars)

    return functions, icons, names, toolbar_sides, toggles, parameters, sub_toolbars
