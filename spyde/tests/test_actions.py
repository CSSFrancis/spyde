from spyde.drawing.toolbars.caret_group import CaretParams
from spyde.drawing.toolbars.rounded_toolbar import RoundedToolBar


class TestActions:
    def test_center_direct_beam(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.mdi_area.subWindowList()
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

        center_zero_beam_roi =  toolbar_bottom.action_widgets["Center Zero Beam"]["plot_items"][0]
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
        center_zero_beam_roi =  toolbar_bottom.action_widgets["Center Zero Beam"]["plot_items"][0]
        assert isinstance(caret_params, CaretParams)
        assert caret_params.isVisible()
        assert center_zero_beam_roi.isVisible()

        roi_z_value = center_zero_beam_roi.zValue()
        plot_z = sig.plot_item.zValue()
        assert roi_z_value > plot_z  # ROI should be above the plot
        # assert roi is on the plot
        assert sig.plot_item.items.__contains__(center_zero_beam_roi)

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

        center_zero_beam_roi_new =  toolbar_bottom_new.action_widgets["Center Zero Beam"]["plot_items"][0]
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
        assert sig.plot_item.items.__contains__(center_zero_beam_roi_new)


















