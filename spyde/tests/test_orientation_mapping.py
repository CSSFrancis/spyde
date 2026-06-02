# spyde/tests/test_orientation_mapping.py
import pytest
from pytestqt.qtbot import QtBot
from spyde.drawing.toolbars.caret_group import CaretParams
from PySide6 import QtWidgets


def test_file_drop_widget_created(qtbot):
    params = {
        "cif_files": {
            "name": "CIF Files",
            "type": "file_drop",
            "extensions": [".cif"],
        }
    }
    widget = CaretParams(parameters=params)
    qtbot.addWidget(widget)
    # The kwargs entry should be a QWidget (the file drop widget)
    assert "cif_files" in widget.kwargs
    drop_widget = widget.kwargs["cif_files"]
    assert hasattr(drop_widget, "get_files")
    assert drop_widget.get_files() == []
