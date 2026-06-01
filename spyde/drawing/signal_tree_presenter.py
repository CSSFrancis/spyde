from __future__ import annotations
from functools import partial
from typing import TYPE_CHECKING

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from spyde.signal_tree import BaseSignalTree
    from spyde.drawing.plots.plot import Plot
from hyperspy.signal import BaseSignal
from spyde.external.qt.labels import EditableLabel
from spyde import METADATA_WIDGET_CONFIG


def _on_axis_field_edit(
    signal_tree: "BaseSignalTree",
    signal: BaseSignal,
    axis,
    field: str,
    line_edit: QtWidgets.QLineEdit,
    is_nav: bool,
    text: str = "",
):
    """Update an axis field on edit. If is_nav, updates all signals in the tree."""
    if is_nav:
        for sig in signal_tree.signals():
            index = sig.axes_manager._axes.index(axis)
            sig.axes_manager._axes[index].__setattr__(field, line_edit.text())
        for plot in signal_tree.navigator_plot_manager.plots.values():
            plot.update_image_rectangle()
    else:
        index = signal.axes_manager._axes.index(axis)
        signal.axes_manager._axes[index].__setattr__(field, line_edit.text())
        for plot in signal_tree.signal_plots:
            if plot.plot_state.current_signal is signal:
                plot.update_image_rectangle()


def build_axes_groups(
    signal_tree: "BaseSignalTree",
    signal: BaseSignal | None,
    plot: "Plot",
) -> list[QtWidgets.QGroupBox]:
    """Build Navigation Axes + Signal Axes QGroupBoxes with editable fields."""
    groups: list[QtWidgets.QGroupBox] = []

    def _make_group(title: str, axes_list, is_nav=False) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(title)
        group.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed
        )
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setMaximumHeight(160)

        container = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(container)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)

        header_style = "font-size: 9px; font-weight: 600;"
        for col, label in enumerate(["Name", "Scale", "Offset", "Units"]):
            h = QtWidgets.QLabel(label)
            h.setStyleSheet(header_style)
            if col == 0:
                h.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(h, 0, col)

        for row, axis in enumerate(axes_list, start=1):
            name_edit = EditableLabel(str(axis.name))
            scale_edit = EditableLabel(str(axis.scale))
            offset_edit = EditableLabel(str(axis.offset))
            units_edit = EditableLabel(str(axis.units))

            for w in (name_edit, scale_edit, offset_edit, units_edit):
                w.setStyleSheet("font-size: 8px;")
                w.setFixedWidth(72)
                w.setFixedHeight(18)

            for w, field in zip(
                (name_edit, scale_edit, offset_edit, units_edit),
                ("name", "scale", "offset", "units"),
            ):
                w.editingFinished.connect(
                    partial(_on_axis_field_edit, signal_tree, signal, axis, field, w, is_nav)
                )

            grid.addWidget(name_edit, row, 0)
            grid.addWidget(scale_edit, row, 1)
            grid.addWidget(offset_edit, row, 2)
            grid.addWidget(units_edit, row, 3)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)

        scroll.setWidget(container)
        v = QtWidgets.QVBoxLayout(group)
        v.setContentsMargins(4, 4, 4, 4)
        v.addWidget(scroll)
        return group

    groups.append(
        _make_group(
            "Navigation Axes",
            signal_tree.root.axes_manager.navigation_axes,
            is_nav=True,
        )
    )
    if signal is not None and not plot.is_navigator:
        groups.append(_make_group("Signal Axes", signal.axes_manager.signal_axes))
    return groups


def build_metadata_dict(signal_tree: "BaseSignalTree") -> dict[str, dict[str, str]]:
    """Return metadata as a plain dict. Callers turn this into widgets."""
    subsections: dict[str, dict[str, str]] = {}
    for subsection, props in METADATA_WIDGET_CONFIG["metadata_widget"].items():
        subsections[subsection] = {}
        for prop, value in props.items():
            if "key" in value:
                current_value = signal_tree.root.metadata.get_item(
                    item_path=value["key"], default=value.get("default", "--")
                )
            elif "attr" in value:
                current_value = signal_tree.get_nested_attr(value["attr"])
            elif "function" in value:
                fun = signal_tree.get_nested_attr(value["function"])
                current_value = fun() if callable(fun) else "--"
            else:
                current_value = "--"
            subsections[subsection][prop] = (
                f"{current_value} {value.get('units', '')}".strip()
            )
    return subsections
