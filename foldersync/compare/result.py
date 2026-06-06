"""Comparison result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from ..fs.base import FileStat


class DiffStatus(Enum):
    SAME = "same"
    DIFFERENT = "different"
    LEFT_ONLY = "left_only"
    RIGHT_ONLY = "right_only"


@dataclass
class ComparePair:
    relpath: str
    status: DiffStatus
    left: Optional[FileStat] = None
    right: Optional[FileStat] = None


@dataclass
class CompareReport:
    pairs: List[ComparePair] = field(default_factory=list)

    def counts(self) -> dict:
        out = {s: 0 for s in DiffStatus}
        for p in self.pairs:
            out[p.status] += 1
        return out

    def differing(self) -> List[ComparePair]:
        return [p for p in self.pairs if p.status is not DiffStatus.SAME]
