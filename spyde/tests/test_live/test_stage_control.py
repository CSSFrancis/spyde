from PySide6 import QtWidgets

from spyde.live.stage_control_widget import StageControlWidget

class TestStageControlWidget:
    def test_initialization(self, qtbot, window):
        win = window["window"]
        dock = QtWidgets.QDockWidget()
        dock.setFloating(True)
        dock.setWidget(StageControlWidget())
        dock.show()
        qtbot.wait(10000)

    def test_move_stage(self):
        # Test moving the stage to a specific position
        pass

    def test_get_position(self):
        # Test retrieving the current position of the stage
        pass

    def test_invalid_move(self):
        # Test handling of invalid move commands
        pass