import numpy as np
import hyperspy.api as hs
import pytest
from unittest.mock import MagicMock


class TestGetFft:
    def test_output_shape(self):
        from spyde.drawing.update_functions import get_fft

        img = np.random.rand(32, 32).astype(np.float32)
        image_item = MagicMock()
        image_item.image = img

        selector = MagicMock()
        selector.parent = MagicMock()
        selector.parent.image_item = image_item

        child = MagicMock()
        # indices: corners of a rectangle covering most of the image
        indices = np.array([[0, 0], [0, 31], [31, 0], [31, 31]])
        result = get_fft(selector, child, indices)
        assert result.shape == (32, 32)

    def test_output_is_real(self):
        from spyde.drawing.update_functions import get_fft

        img = np.random.rand(16, 16).astype(np.float32)
        image_item = MagicMock()
        image_item.image = img
        selector = MagicMock()
        selector.parent = MagicMock()
        selector.parent.image_item = image_item
        child = MagicMock()
        indices = np.array([[0, 0], [0, 15], [15, 0], [15, 15]])
        result = get_fft(selector, child, indices)
        assert np.isrealobj(result)


class TestUpdateFromNavigationSelectionEager:
    def _make_4d_signal(self):
        data = np.arange(4 * 4 * 8 * 8, dtype=np.float32).reshape(4, 4, 8, 8)
        sig = hs.signals.Signal2D(data)
        return sig

    def test_single_index_returns_correct_slice(self):
        from spyde.drawing.update_functions import update_from_navigation_selection

        sig = self._make_4d_signal()
        child = MagicMock()
        child.plot_state = MagicMock()
        child.plot_state.current_signal = sig

        selector = MagicMock()
        selector.is_integrating = False

        # When not integrating, np.mean([[2, 3]], axis=0) = [2, 3] (1D, len=2)
        # tuple_inds = (indices[0], indices[1]) = (2, 3), len=2 so uses mean branch:
        # np.mean(sig.data[(2, 3)], axis=0) = np.mean(sig.data[2, 3], axis=0)
        # sig.data[2, 3] is shape (8, 8); mean over axis=0 → shape (8,)
        indices = np.array([[2, 3]])  # nav position (2, 3)
        result = update_from_navigation_selection(
            selector, child, indices, get_result=False, cache_in_shared_memory=False
        )
        expected = np.mean(sig.data[2, 3], axis=0)
        np.testing.assert_array_equal(result, expected)

    def test_integrating_uses_fancy_indexing(self):
        from spyde.drawing.update_functions import update_from_navigation_selection

        sig = self._make_4d_signal()
        child = MagicMock()
        child.plot_state = MagicMock()
        child.plot_state.current_signal = sig

        selector = MagicMock()
        selector.is_integrating = True

        # When integrating, indices are kept as-is: shape (2, 2)
        # tuple_inds = (indices[0], indices[1]) = (array([0,0]), array([1,0]))
        # sig.data[(array([0,0]), array([1,0]))] performs fancy indexing:
        #   -> sig.data[0,1] and sig.data[0,0]
        indices = np.array([[0, 0], [1, 0]])
        result = update_from_navigation_selection(
            selector, child, indices, get_result=False, cache_in_shared_memory=False
        )
        # Actual behavior: fancy indexing with row indices [0,0] and col indices [1,0]
        expected = np.mean(
            [sig.data[0, 1], sig.data[0, 0]], axis=0
        )
        np.testing.assert_array_almost_equal(result, expected)
