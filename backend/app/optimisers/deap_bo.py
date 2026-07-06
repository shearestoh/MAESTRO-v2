"""
DEAP evolutionary algorithm optimiser adapter for MAESTRO.

Uses a (μ + λ) Evolution Strategy with real-valued encoding.
No surrogate model — evaluates each candidate directly.
Best for discrete, combinatorial, or high-dimensional spaces.

Install with: pip install deap
"""
from __future__ import annotations

import random
from typing import List, Optional, Tuple

from app.optimisers.base import BaseOptimiser


class DEAPOptimiser(BaseOptimiser):
    name = "DEAP (Evolution Strategy)"
    description = (
        "Real-valued (μ+λ) Evolution Strategy via DEAP. "
        "No surrogate model — evaluates each candidate directly. "
        "Good for combinatorial, discrete, or noisy high-dimensional spaces."
    )

    def __init__(self):
        self._bounds:      List[Tuple[float, float]] = []
        self._population:  list = []
        self._toolbox      = None
        self._history_x:   List[List[float]] = []
        self._history_y:   List[float] = []
        self._pending_ind  = None
        self._mu           = 10   # population size
        self._lambda       = 20   # offspring per generation
        self._gen          = 0
        self._offspring_queue: list = []

    def initialise(
        self,
        bounds:           List[Tuple[float, float]],
        n_initial_points: int = 5,
        random_state:     int = 42,
    ) -> None:
        try:
            from deap import base, creator, tools, algorithms
        except ImportError:
            raise ImportError(
                "DEAP is not installed. Run: pip install deap"
            )

        self._bounds = bounds
        random.seed(random_state)

        # Avoid duplicate creator registration across multiple calls
        if not hasattr(creator, "FitnessMax_MAESTRO"):
            creator.create("FitnessMax_MAESTRO", base.Fitness, weights=(1.0,))
        if not hasattr(creator, "Individual_MAESTRO"):
            creator.create("Individual_MAESTRO", list, fitness=creator.FitnessMax_MAESTRO)

        toolbox = base.Toolbox()

        def random_individual():
            return creator.Individual_MAESTRO(
                [random.uniform(lo, hi) for lo, hi in bounds]
            )

        toolbox.register("individual", random_individual)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)
        toolbox.register("mate",    tools.cxBlend, alpha=0.5)
        toolbox.register("mutate",  tools.mutGaussian,
                         mu=0, sigma=[0.1 * (hi - lo) for lo, hi in bounds], indpb=0.3)
        toolbox.register("select",  tools.selTournament, tournsize=3)

        self._toolbox     = toolbox
        self._population  = toolbox.population(n=max(self._mu, n_initial_points))
        # Queue up initial population for evaluation
        self._offspring_queue = list(self._population[:])

    def suggest(self) -> List[float]:
        if self._toolbox is None:
            raise RuntimeError("Optimiser not initialised.")

        # If we have queued offspring, return the next one
        if self._offspring_queue:
            ind = self._offspring_queue.pop(0)
            # Clip to bounds
            for i, (lo, hi) in enumerate(self._bounds):
                ind[i] = max(lo, min(hi, ind[i]))
            self._pending_ind = ind
            return list(ind)

        # Generate new offspring via crossover + mutation
        from deap import tools
        offspring = self._toolbox.select(self._population, self._lambda)
        offspring = list(map(self._toolbox.clone, offspring))

        for child1, child2 in zip(offspring[::2], offspring[1::2]):
            if random.random() < 0.7:
                self._toolbox.mate(child1, child2)
                del child1.fitness.values
                del child2.fitness.values

        for mutant in offspring:
            if random.random() < 0.3:
                self._toolbox.mutate(mutant)
                del mutant.fitness.values

        # Clip to bounds
        for ind in offspring:
            for i, (lo, hi) in enumerate(self._bounds):
                ind[i] = max(lo, min(hi, ind[i]))

        self._offspring_queue = offspring
        ind = self._offspring_queue.pop(0)
        self._pending_ind = ind
        return list(ind)

    def update(self, x: List[float], y: float) -> None:
        if self._pending_ind is None:
            raise RuntimeError("suggest() must be called before update().")
        self._pending_ind.fitness.values = (y,)
        # Add evaluated individual to population, keep best μ
        self._population.append(self._pending_ind)
        self._population = sorted(
            self._population,
            key=lambda ind: ind.fitness.values[0] if ind.fitness.valid else float("-inf"),
            reverse=True,
        )[:self._mu]
        self._history_x.append(list(x))
        self._history_y.append(y)
        self._pending_ind = None

    def best_so_far(self) -> Tuple[Optional[List[float]], Optional[float]]:
        if not self._history_y:
            return None, None
        import numpy as np
        best_idx = int(np.argmax(self._history_y))
        return self._history_x[best_idx], self._history_y[best_idx]