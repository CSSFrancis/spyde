from PySide6 import QtWidgets
from pyqtgraph import CircleROI, RectROI

from spyde.drawing.toolbars.caret_group import CaretParams
from spyde.drawing.toolbars.rounded_toolbar import RoundedToolBar, PopoutToolBar


class TestActions:
    def test_center_direct_beam(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.plots
        assert len(subwindows) == 2

        nav, sig = subwindows

        toolbar_bottom = sig.plot_state.toolbar_bottom # type: RoundedToolBar

        actions = toolbar_bottom.actions()
        print("Actions:", actions)

        for action in actions:
            print("Action text:", action.text())
            if action.text() == "Center Zero Beam":
                center_button = action
            elif action.text() == "Rebin":
                rebin = action
        center_zero_beam_roi =  toolbar_bottom.action_widgets["Center Zero Beam"]["plot_items"]["item_0"]
        caret_params = toolbar_bottom.action_widgets["Center Zero Beam"]["widget"]

        # Start hidden
        assert not center_zero_beam_roi.isVisible()
        assert not caret_params.isVisible()

        # Simulate clicking the "Center Zero Beam" action
        center_button.trigger()
        qtbot.wait(500)  # wait for the action to take effect

        # make sure that the caret box was created
        # action widget: "plot_items", "widget", "layout", "tracker", "position_fn"
        caret_params = toolbar_bottom.action_widgets["Center Zero Beam"]["widget"]
        center_zero_beam_roi =  toolbar_bottom.action_widgets["Center Zero Beam"]["plot_items"]["item_0"]
        assert isinstance(caret_params, CaretParams)
        assert caret_params.isVisible()
        assert center_zero_beam_roi.isVisible()

        roi_z_value = center_zero_beam_roi.zValue()
        plot_z = sig.zValue()
        assert roi_z_value > plot_z  # ROI should be above the plot
        # assert roi is on the plot
        assert sig.items.__contains__(center_zero_beam_roi)

        # untoggle the action and make sure that the caret box is hidden and the ROI is removed
        center_button.trigger()
        qtbot.wait(500)
        # make sure that the caret box was removed
        assert not center_zero_beam_roi.isVisible()
        assert not caret_params.isVisible()

        # toggle it back on to make sure it can be re-shown
        center_button.trigger()
        qtbot.wait(500)
        # make sure that the caret box was created
        assert center_zero_beam_roi.isVisible()
        assert caret_params.isVisible()

        # switch to a different action and make sure that the caret box is hidden and the ROI is removed
        rebin_widget = toolbar_bottom.action_widgets["Rebin"]["widget"]
        rebin.trigger()
        qtbot.wait(1000)
        # make sure that the caret box was removed
        assert not center_zero_beam_roi.isVisible()
        assert not caret_params.isVisible()

        # rebin the dataset to get another plot state
        rebin_widget.submit_button.click()
        qtbot.wait(500)
        toolbar_bottom_new = sig.plot_state.toolbar_bottom # type: RoundedToolBar

        for action in actions:
            print("Action text:", action.text())
            if action.text() == "Center Zero Beam":
                center_button_new = action
            elif action.text() == "Rebin":
                rebin_new = action

        center_zero_beam_roi_new =  toolbar_bottom_new.action_widgets["Center Zero Beam"]["plot_items"]["item_0"]
        caret_params_new = toolbar_bottom_new.action_widgets["Center Zero Beam"]["widget"]
        # make sure that the caret box was created
        assert isinstance(caret_params_new, CaretParams)
        assert not center_zero_beam_roi_new.isVisible()
        assert not caret_params_new.isVisible()

        # Simulate clicking the "Center Zero Beam" action
        qtbot.wait(4000)  # wait for the action to take effect
        center_button_new.trigger()
        # make sure that the caret box was created

        # the plot needs to be updated before the toolbars are updated
        assert sig.items.__contains__(center_zero_beam_roi_new)

    def test_rebin(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.plots
        assert len(subwindows) == 2

        nav, sig = subwindows

        toolbar_bottom = sig.plot_state.toolbar_bottom # type: RoundedToolBar

        actions = toolbar_bottom.actions()
        print("Actions:", actions)

        for action in actions:
            print("Action text:", action.text())
            if action.text() == "Rebin":
                rebin = action

        rebin_widget = toolbar_bottom.action_widgets["Rebin"]["widget"]
        # Simulate clicking the "Rebin" action
        rebin.trigger()
        qtbot.wait(500)  # wait for the action to take effect

        assert rebin_widget.isVisible()

        # submit the rebin
        rebin_widget.submit_button.click()
        qtbot.wait(4000)  # wait for the action to take effect

        # check that the data has been rebinned
        current_data = sig.current_data
        print("Current data:", current_data.shape)
        assert current_data.shape[0] == 32
        assert current_data.shape[1] == 32

    def test_virtual_imaging(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.plots
        assert len(subwindows) == 2

        nav, sig = subwindows

        toolbar_bottom = sig.plot_state.toolbar_bottom # type: RoundedToolBar

        actions = toolbar_bottom.actions()
        print("Actions:", actions)

        for action in actions:
            print("Action text:", action.text())
            if action.text() == "Virtual Imaging":
                virtual_imaging = action

        virtual_imaging_widget = toolbar_bottom.action_widgets["Virtual Imaging"]["widget"]
        # Simulate clicking the "Virtual Imaging" action
        virtual_imaging.trigger()
        qtbot.wait(500)  # wait for the action to take effect

        assert virtual_imaging_widget.isVisible()
        assert isinstance(virtual_imaging_widget, PopoutToolBar)

        # add a virtual detector
        virtual_image_actions = virtual_imaging_widget.actions()
        for action in virtual_image_actions:
            print("Action text:", action.text())
            if action.text() == "Add Virtual Image":
                add_virtual_detector = action

        add_virtual_detector.trigger()
        qtbot.wait(500)
        # check that a new virtual detector has been added
        # should be 2 actions now (1 for adding, 1 for the detector)
        assert len(virtual_imaging_widget.actions()) == 2

        # the toolbar should also have new plot items

        print("actions!", toolbar_bottom.action_widgets["Virtual Imaging"])
        # toggle the virtual detector
        virtual_mask_action = virtual_imaging_widget.actions()[1]
        virtual_mask_action.trigger()
        qtbot.wait(500)

        roi = list(toolbar_bottom.action_widgets["Virtual Imaging"]["plot_items"].values())[0]
        assert isinstance(roi, CircleROI)
        assert roi.isVisible()
        # check to make sure the roi is on the right plot?

        plot_z = sig.zValue()
        roi_z = roi.zValue()
        assert roi_z > plot_z  # ROI should be above the plot

        assert sig.items.__contains__(roi)

        # untoggle the virtual detector
        virtual_imaging.trigger()
        qtbot.wait(500)
        assert not roi.isVisible()

        # Change the type of the virtual detector
        virtual_imaging.trigger()
        assert "Virtual Image (green)" in virtual_imaging_widget.action_widgets
        box =  virtual_imaging_widget.action_widgets["Virtual Image (green)"]["widget"]
        box.get_parameter_widget("type").setCurrentText("rectangle")
        roi = list(toolbar_bottom.action_widgets["Virtual Imaging"]["plot_items"].values())[0]
        assert isinstance(roi, RectROI)
        qtbot.wait(500)





