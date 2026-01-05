"""
Navigating with Selectors
-------------------------

This example demonstrates how to navigate through a high-dimensional dataset using selectors.
"""

# sphinx_gallery_start_ignore
from spyde.qt.shared import open_window, register_window_for_gallery, create_data
from PySide6 import Qt

win = open_window()
create_data(win, "4D STEM")
register_window_for_gallery(win)
win.close()
# sphinx_gallery_end_ignore
# %%
