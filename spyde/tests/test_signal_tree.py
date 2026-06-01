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


from unittest.mock import MagicMock
from spyde.signal_tree import BaseSignalTree


def _make_tree():
    """Minimal BaseSignalTree without Qt (mock main_window)."""
    sig = _make_signal((4, 4, 8, 8))  # 4D: nav(4,4) sig(8,8)
    mw = MagicMock()
    mw._heavy_compute_workers = None
    # Prevent MDI/plot construction during __init__
    mw.add_plot_window.return_value = MagicMock()
    mw.add_plot_window.return_value.add_new_plot.return_value = MagicMock()
    tree = BaseSignalTree.__new__(BaseSignalTree)
    tree.root = sig
    tree.main_window = mw
    tree.navigator_signals = {}
    tree.signal_plots = []
    tree.navigator_plot_manager = None
    tree.client = None
    from spyde.signal_node import SignalNode
    tree.root_node = SignalNode(signal=sig, name="root", parent=None)
    return tree, sig


class TestBaseSignalTreeTraversal:
    def test_walk_visits_root(self):
        tree, sig = _make_tree()
        nodes = list(tree.walk())
        assert len(nodes) == 1
        assert nodes[0].signal is sig

    def test_walk_visits_children(self):
        tree, sig = _make_tree()
        from spyde.signal_node import SignalNode
        child_sig = _make_signal((4, 4, 8, 8))
        child = SignalNode(signal=child_sig, name="filtered", parent=tree.root_node)
        tree.root_node.children["filtered"] = child
        nodes = list(tree.walk())
        assert len(nodes) == 2
        signals_visited = [n.signal for n in nodes]
        assert sig in signals_visited
        assert child_sig in signals_visited

    def test_walk_branching_tree(self):
        tree, sig = _make_tree()
        from spyde.signal_node import SignalNode
        child_a = SignalNode(signal=_make_signal(), name="a", parent=tree.root_node)
        child_b = SignalNode(signal=_make_signal(), name="b", parent=tree.root_node)
        grandchild = SignalNode(signal=_make_signal(), name="c", parent=child_a)
        tree.root_node.children["a"] = child_a
        tree.root_node.children["b"] = child_b
        child_a.children["c"] = grandchild
        assert len(list(tree.walk())) == 4

    def test_signals_list_includes_root(self):
        tree, sig = _make_tree()
        assert sig in tree.signals()

    def test_signals_list_includes_descendants(self):
        tree, sig = _make_tree()
        from spyde.signal_node import SignalNode
        child_sig = _make_signal()
        child = SignalNode(signal=child_sig, name="filtered", parent=tree.root_node)
        tree.root_node.children["filtered"] = child
        sigs = tree.signals()
        assert any(s is sig for s in sigs)
        assert any(s is child_sig for s in sigs)

    def test_get_node_finds_signal(self):
        tree, sig = _make_tree()
        node = tree.get_node(sig)
        assert node is not None
        assert node.signal is sig

    def test_get_node_unknown_returns_none(self):
        tree, _ = _make_tree()
        unknown = _make_signal()
        assert tree.get_node(unknown) is None

    def test_get_node_finds_child(self):
        tree, _ = _make_tree()
        from spyde.signal_node import SignalNode
        child_sig = _make_signal()
        child = SignalNode(signal=child_sig, name="filtered", parent=tree.root_node)
        tree.root_node.children["filtered"] = child
        node = tree.get_node(child_sig)
        assert node is child
