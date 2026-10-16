"""Brier-score calibration + isotonic-free binned recalibration of Jev's confidence."""
from collections import defaultdict


def brier(preds, outcomes) -> float:
    return sum((p - o) ** 2 for p, o in zip(preds, outcomes)) / len(preds) if preds else float("nan")


class Calibrator:
    """Maps raw confidence -> empirical hit rate by bin. Shrinks to the raw value when data is thin,
    and never returns more than the raw confidence (we only trust Jev downward)."""
    def __init__(self, bins=10, min_n=20):
        self.bins, self.min_n = bins, min_n
        self.hits, self.n = defaultdict(int), defaultdict(int)

    def _bin(self, p):
        return min(int(p * self.bins), self.bins - 1)

    def update(self, p: float, outcome: int):
        b = self._bin(p)
        self.n[b] += 1
        self.hits[b] += outcome

    def calibrated(self, p: float) -> float:
        b = self._bin(p)
        if self.n[b] < self.min_n:
            return min(p, 0.5 + (p - 0.5) * self.n[b] / self.min_n)  # shrink toward coin flip
        return min(p, self.hits[b] / self.n[b])
