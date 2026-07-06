"""
Ax Platform optimiser adapter for MAESTRO.

Uses Meta's Ax Service API directly for Bayesian optimisation.
Supports single-objective continuous optimisation out of the box.
For multi-objective, multi-task, or constrained problems, use Honegumi
to generate a custom Ax configuration.

Install with: pip install ax-platform
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.optimisers.base import BaseOptimiser


class HonegumiOptimiser(BaseOptimiser):
    name = "Ax Platform (Honegumi)"
    description = (
        "Bayesian optimisation via Meta's Ax Service API. "
        "Uses BOTORCH under the hood with GP surrogate and Expected Improvement. "
        "Supports single-objective continuous optimisation. "
        "For multi-objective or constrained problems, configure via Honegumi."
    )

    def __init__(self):
        self._ax_client  = None
        self._bounds:    List[Tuple[float, float]] = []
        self._param_names: List[str] = []
        self._history_x: List[List[float]] = []
        self._history_y: List[float] = []
        self._trial_index: Optional[int] = None

    def initialise(
        self,
        bounds:           List[Tuple[float, float]],
        n_initial_points: int = 5,
        random_state:     int = 42,
    ) -> None:
        try:
            from ax.service.ax_client import AxClient, ObjectiveProperties
        except ImportError:
            raise ImportError(
                "Ax Platform is not installed. Run: pip install ax-platform"
            )

        self._bounds      = bounds
        self._param_names = [f"x{i}" for i in range(len(bounds))]

        self._ax_client = AxClient(random_seed=random_state, verbose_logging=False)
        self._ax_client.create_experiment(
            name="maestro_optimisation",
            parameters=[
                {
                    "name":          name,
                    "type":          "range",
                    "bounds":        list(bound),
                    "value_type":    "float",
                }
                for name, bound in zip(self._param_names, bounds)
            ],
            objectives={"objective": ObjectiveProperties(minimize=False)},
            # Sobol quasi-random initialisation
            choose_generation_strategy_kwargs={
                "num_initialization_trials": n_initial_points,
            },
        )

    def suggest(self) -> List[float]:
        if self._ax_client is None:
            raise RuntimeError("Optimiser not initialised.")
        parameters, self._trial_index = self._ax_client.get_next_trial()
        return [float(parameters[name]) for name in self._param_names]

    def update(self, x: List[float], y: float) -> None:
        if self._ax_client is None or self._trial_index is None:
            raise RuntimeError("Optimiser not initialised or suggest() not called.")
        self._ax_client.complete_trial(
            trial_index=self._trial_index,
            raw_data={"objective": (y, None)},  # (mean, sem) — None = no noise estimate
        )
        self._history_x.append(list(x))
        self._history_y.append(y)
        self._trial_index = None

    def best_so_far(self) -> Tuple[Optional[List[float]], Optional[float]]:
        if not self._history_y:
            return None, None
        import numpy as np
        best_idx = int(np.argmax(self._history_y))
        return self._history_x[best_idx], self._history_y[best_idx]