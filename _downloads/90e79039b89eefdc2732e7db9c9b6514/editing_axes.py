"""
Changing Scales and Axes
========================

This example demonstrates how to modify the scales and axes of a plot. These are rendered as QLabels but
can be edited by left-clicking on them which will change them into QLineEdits for text input.

"""

# sphinx_gallery_start_ignore

from spyde.qt.shared import open_window, register_window_for_gallery, create_data
from PySide6 import Qt

win = open_window()

create_data(win, "Insitu TEM")

register_window_for_gallery(win)
# sphinx_gallery_end_ignore


# %%
# After opening the example data, we can see that the plot has default axis labels and scales.
# By left-clicking on the axis labels (e.g., "X Axis" or "Y Axis"), we can edit them to more meaningful names.
# Similarly, by left-clicking on the scale labels (e.g., "1.0" on the X-axis), we can change the scale values.
# This allows us to customize the plot to better represent the data being visualized.

# sphinx_gallery_start_ignore

group_widget = win.axes_layout.itemAt(0).widget()

register_window_for_gallery(group_widget)

# sphinx_gallery_end_ignore

# %%
# There is some limited support for mathematical expressions in the axis labels using LaTeX syntax.
# For example, we can label an axis as "$nm^{-1}$" to represent nanometers.

# sphinx_gallery_start_ignore
vlay = group_widget.layout()
scroll_area = vlay.itemAt(0).widget()
content_widget = scroll_area.widget()

grid_layout = content_widget.layout()
widg = grid_layout.itemAtPosition(1, 0).widget()

widg._start_editing()
widg._line_edit.setText("time")
register_window_for_gallery(group_widget)
# sphinx_gallery_end_ignore


# %%

# After editing the axis labels and scales, the plot now reflects these changes with the updated labels and scales.
# This enhances the clarity and interpretability of the plot, making it easier to understand the data being presented.

# sphinx_gallery_start_ignore
widg._finish_editing()
units_widg = grid_layout.itemAtPosition(1, 3).widget()
units_widg._start_editing()
units_widg._line_edit.setText("$s^{-1}$")
register_window_for_gallery(group_widget)
# sphinx_gallery_end_ignore

# %%
# Finally, we can see the main window with the updated axis labels and scales reflected in the plot.

# sphinx_gallery_start_ignore
units_widg._finish_editing()
register_window_for_gallery(win)

win.close()
# sphinx_gallery_end_ignore

# %%
