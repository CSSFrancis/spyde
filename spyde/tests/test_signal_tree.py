import numpy as np
import hyperspy.api as hs
import pytest
from spyde.signal_node import SignalNode


def _make_signal(shape=(4, 4)):
    data = np.zeros(shape)
    return hs.signals.Signal2D(data)


class TestSignalNode:
    def test_fields(self):
        sig = _make_signal()
        node = SignalNode(signal=sig, name="root", parent=None)
        assert node.signal is sig
        assert node.name == "root"
        assert node.parent is None
        assert node.children == {}
        assert node.transformation is None
        assert node.args == ()
        assert node.kwargs == {}

    def test_parent_linkage(self):
        sig_a = _make_signal()
        sig_b = _make_signal()
        parent = SignalNode(signal=sig_a, name="root", parent=None)
        child = SignalNode(signal=sig_b, name="filtered", parent=parent)
        assert child.parent is parent

    def test_children_dict(self):
        sig_a = _make_signal()
        sig_b = _make_signal()
        parent = SignalNode(signal=sig_a, name="root", parent=None)
        child = SignalNode(signal=sig_b, name="filtered", parent=parent)
        parent.children["filtered"] = child
        assert "filtered" in parent.children
        assert parent.children["filtered"] is child

    def test_transformation_stored(self):
        sig = _make_signal()
        node = SignalNode(
            signal=sig,
            name="rebinned",
            parent=None,
            transformation="rebin",
            args=(2,),
            kwargs={"scale": [1, 1, 2, 2]},
        )
        assert node.transformation == "rebin"
        assert node.args == (2,)
        assert node.kwargs == {"scale": [1, 1, 2, 2]}
