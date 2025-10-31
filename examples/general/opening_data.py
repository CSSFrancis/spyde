"""
Opening Data:
-------------

This example demonstrates how to open and visualize data using the SpyDE application.

We will start by opening the SpyDE main window as shown below.
"""

# sphinx_gallery_start_ignore
from spyde.qt.shared import open_window, register_window_for_gallery, create_data, _find_menu_action
from PySide6 import QtWidgets
from PySide6 import QtCore

import numpy as np
import hyperspy.api as hs
import os

s = hs.signals.Signal2D(np.random.rand(100, 64, 64))
s.save("example_data.hspy", overwrite=True)

win = open_window()

register_window_for_gallery(win)

# sphinx_gallery_end_ignore


# %%
# Here we have the SpyDE main window opened!
# Now, let's open some example data. We can do this by navigating to the "File" menu and selecting "Open".
# SpyDe can open all the file formats supported by HyperSpy. That being said, files which support `distributed`
# loading will work much better.  If there is a specific file format that you would like to see supported,
# please open an issue on the RosettaSciIo GitHub page.

# sphinx_gallery_start_ignore

menubar = win.menuBar()
file_menu_action = _find_menu_action(menubar, "File")

# Resolve the actual 'Open' action (ignore 'Open Recent' submenu)
open_action = None
if file_menu_action and hasattr(file_menu_action, "menu"):
    file_menu = file_menu_action.menu()
    if file_menu:
        for act in file_menu.actions():
            txt = (act.text() or "").strip().lower()
            if txt.startswith("open") and act.menu() is None:
                open_action = act
                break
assert open_action is not None, "'Open' action not found in File menu"

def _register_dialog():
    app = win.app
    # Prefer the active modal widget (works during exec() nested loop)
    dlg = app.activeModalWidget()
    if isinstance(dlg, QtWidgets.QDialog) and dlg.isVisible():
        register_window_for_gallery(dlg)
        return
    # Fallback: scan top-level widgets
    for w in app.topLevelWidgets():
        if isinstance(w, QtWidgets.QDialog) and w.isVisible():
            register_window_for_gallery(w)
            return
    # Try again shortly until the dialog appears
    QtCore.QTimer.singleShot(50, _register_dialog)

def _set_and_accept_open_dialog():
    app = win.app
    file_path = os.path.abspath("example_data.hspy")

    # Prefer the active modal widget
    dlg = app.activeModalWidget()
    if isinstance(dlg, QtWidgets.QFileDialog) and dlg.isVisible():
        register_window_for_gallery(dlg)
        dlg.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptOpen)
        dlg.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        dlg.setDirectory(os.path.dirname(file_path))

        # Put the path in the filename input box if available; otherwise select the file
        line_edit = dlg.findChild(QtWidgets.QLineEdit)
        if line_edit is not None:
            line_edit.setText(file_path)
        else:
            dlg.selectFile(file_path)

        # Click the "Open" button to mimic user action; fallback to accept()
        def _click_open():
            for btn in dlg.findChildren(QtWidgets.QPushButton):
                txt = (btn.text() or "").strip().lower()
                if "open" in txt and btn.isEnabled():
                    btn.click()
                    return
            dlg.accept()

        QtCore.QTimer.singleShot(0, _click_open)
        return

    # Try again shortly until the dialog appears
    QtCore.QTimer.singleShot(50, _set_and_accept_open_dialog)

QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
QtWidgets.QApplication.processEvents()

# Open the dialog asynchronously and then register it once visible
QtCore.QTimer.singleShot(0, open_action.trigger)
#QtCore.QTimer.singleShot(25, _register_dialog)
QtCore.QTimer.singleShot(2, _set_and_accept_open_dialog)

# sphinx_gallery_end_ignore

# %%
# Now we can see the opened data in the SpyDE application!


# sphinx_gallery_start_ignore
# Let queued timers/dialog interactions run and UI settle

for _ in range(20):
    QtWidgets.QApplication.processEvents()
    QtCore.QThread.msleep(50)

register_window_for_gallery(win)
# sphinx_gallery_end_ignore
# %%
# We can now explore and visualize the data using SpyDE's powerful tools and features!

# sphinx_gallery_start_ignore
win.close()
# sphinx_gallery_end_ignore

# %%
# sphinx_gallery_thumbnail_number = 2
