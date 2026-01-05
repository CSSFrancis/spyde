from skimage.morphology import opening
class TestPlotStates:
    def test_add_plot_state(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subplots = win.plots
        subwindows = win.plot_subwindows
        assert len(subwindows) == 2

        nav, sig = subplots  # type: Plot
        nav_window, sig_window = subwindows
        nav_manager = nav.multiplot_manager  # type: MultiplotManager

        # Verify initial plot states is only 1 long
        signal_tree = win.signal_trees[0]
        assert len(sig.plot_states) == 1

        # Add a new plot state
        def fun(signal):
            return signal.map(opening, inplace=False).isig[0:10,0:10]

        old_sig = sig.plot_state.current_signal
        new_sig = signal_tree.add_transformation(parent_signal=sig.plot_state.current_signal,
                                       function=fun,
                                       node_name ="Opened"
                                       )
        sig.set_plot_state(new_sig)
        assert len(sig.plot_states) == 2
        # asser that the plot state has updated
        assert sig.plot_states[new_sig] == sig.plot_state

        # assert that the current signal is the new signal
        assert sig.plot_state.current_signal == new_sig

        # assert the image is the right shape

        fut = sig.current_data
        # make sure the future is applied
        qtbot.waitUntil(lambda: fut.done(), timeout=5000)


        qtbot.wait(100)
        assert sig.image_item.image.shape == (10,10)



