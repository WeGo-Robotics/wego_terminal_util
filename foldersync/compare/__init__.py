"""File comparison engine."""

from .result import ComparePair, CompareReport, DiffStatus
from .engine import CompareEngine

__all__ = ["ComparePair", "CompareReport", "DiffStatus", "CompareEngine"]
