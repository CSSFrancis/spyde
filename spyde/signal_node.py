from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from hyperspy.signal import BaseSignal


@dataclass
class SignalNode:
    signal: BaseSignal
    name: str
    parent: Optional["SignalNode"]
    children: dict[str, "SignalNode"] = field(default_factory=dict)
    transformation: Optional[str] = None
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
