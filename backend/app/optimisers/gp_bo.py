from __future__ import annotations
from typing import List, Optional, Tuple
from app.optimisers.base import BaseOptimiser


class GPBayesianOptimiser(BaseOptimiser):
    name        = "GP-Bayesian Optimisation"
    description = (
        "Gaussian Process Bayesian Optimisation with Expected Improvement "
        "acquisition function. Builds a probabilistic surrogate model and "
        "balances exploration vs. exploitation. Powered by scikit-optimize."
    )

    def __init__(self):
        self._opt        = None
        self._history_x: List[List[float]] = []
        self._history_y: List[float]       = []

    def initialise(
        self,
        bounds:           List[Tuple[float, float]],
        n_initial_points: int = 6,
        random_state:     int = 42,
    ) -> None:
        from skopt import Optimizer
        from skopt.space import Real
        self._opt = Optimizer(
            dimensions=[Real(lo, hi) for lo, hi in bounds],
            base_estimator="GP",
            n_initial_points=n_initial_points,
            acq_func="EI",
            random_state=random_state,
        )

    def suggest(self) -> List[float]:
        if self._opt is None:
            raise RuntimeError("Optimiser not initialised.")
        return [float(v) for v in self._opt.ask()]

    def update(self, x: List[float], y: float) -> None:
        if self._opt is None:
            raise RuntimeError("Optimiser not initialised.")
        self._opt.tell(x, -y)
        self._history_x.append(x)
        self._history_y.append(y)

    def best_so_far(self) -> Tuple[Optional[List[float]], Optional[float]]:
        if not self._history_y:
            return None, None
        import numpy as np
        best_idx = int(np.argmax(self._history_y))
        return self._history_x[best_idx], self._history_y[best_idx]