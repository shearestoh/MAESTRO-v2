"""
Optuna TPE optimiser adapter for MAESTRO.

Install with: pip install optuna
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.optimisers.base import BaseOptimiser


class OptunaOptimiser(BaseOptimiser):
    name = "Optuna (TPE)"
    description = (
        "Tree-structured Parzen Estimator via Optuna. "
        "Good for mixed continuous/categorical spaces and pruning of bad trials."
    )

    def __init__(self):
        self._study = None
        self._bounds: List[Tuple[float, float]] = []
        self._history_x: List[List[float]] = []
        self._history_y: List[float] = []
        self._current_trial = None

    def initialise(
        self,
        bounds:           List[Tuple[float, float]],
        n_initial_points: int = 5,
        random_state:     int = 42,
    ) -> None:
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError:
            raise ImportError(
                "Optuna is not installed. Run: pip install optuna"
            )
        self._bounds = bounds
        sampler = optuna.samplers.TPESampler(
            seed=random_state,
            n_startup_trials=n_initial_points,
        )
        self._study = optuna.create_study(direction="maximize", sampler=sampler)

    def suggest(self) -> List[float]:
        if self._study is None:
            raise RuntimeError("Optimiser not initialised.")
        self._current_trial = self._study.ask()
        return [
            self._current_trial.suggest_float(f"x{i}", lo, hi)
            for i, (lo, hi) in enumerate(self._bounds)
        ]

    def update(self, x: List[float], y: float) -> None:
        if self._study is None or self._current_trial is None:
            raise RuntimeError("Optimiser not initialised or suggest() not called.")
        self._study.tell(self._current_trial, y)
        self._history_x.append(list(x))
        self._history_y.append(y)
        self._current_trial = None

    def best_so_far(self) -> Tuple[Optional[List[float]], Optional[float]]:
        if not self._history_y:
            return None, None
        import numpy as np
        best_idx = int(np.argmax(self._history_y))
        return self._history_x[best_idx], self._history_y[best_idx]