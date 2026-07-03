from __future__ import annotations
import numpy as np
from typing import List, Optional, Tuple
from app.optimisers.base import BaseOptimiser


class RandomSearchOptimiser(BaseOptimiser):
    name        = "Random Search"
    description = (
        "Uniform random sampling of the parameter space. "
        "No surrogate model — each suggestion is independent. "
        "Useful as a baseline for comparison with model-based methods."
    )

    def __init__(self):
        self._bounds:    List[Tuple[float, float]] = []
        self._rng:       np.random.Generator = np.random.default_rng(42)
        self._history_x: List[List[float]] = []
        self._history_y: List[float]       = []

    def initialise(self, bounds, n_initial_points=5, random_state=42):
        self._bounds = bounds
        self._rng    = np.random.default_rng(random_state)

    def suggest(self) -> List[float]:
        return [float(self._rng.uniform(lo, hi)) for lo, hi in self._bounds]

    def update(self, x: List[float], y: float) -> None:
        self._history_x.append(x)
        self._history_y.append(y)

    def best_so_far(self) -> Tuple[Optional[List[float]], Optional[float]]:
        if not self._history_y:
            return None, None
        best_idx = int(np.argmax(self._history_y))
        return self._history_x[best_idx], self._history_y[best_idx]