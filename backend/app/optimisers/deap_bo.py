"""
DEAP Evolutionary Algorithm optimiser adapter for MAESTRO.

Uses a real-valued genetic algorithm with simulated binary crossover
and polynomial mutation. Install with: pip install deap
"""
from __future__ import annotations

import random
from typing import List, Optional, Tuple

import numpy as np

from app.optimisers.base import BaseOptimiser


class DEAPOptimiser(BaseOptimiser):
    name = "DEAP (Evolutionary Algorithm)"
    description = (
        "Real-valued genetic algorithm via DEAP. "
        "Uses tournament selection, simulated binary crossover, and polynomial mutation. "
        "Good for combinatorial, discrete, or multi-modal search spaces."
    )

    def __init__(self):
        self._bounds:              List[Tuple[float, float]] = []
        self._history_x:          List[List[float]]         = []
        self._history_y:          List[float]               = []
        self._population                                     = None
        self._toolbox                                        = None
        self._pop_size:           int                        = 30
        self._rng:                random.Random              = random.Random(42)
        self._pending_individual                             = None

    def initialise(
        self,
        bounds:           List[Tuple[float, float]],
        n_initial_points: int = 5,
        random_state:     int = 42,
    ) -> None:
        try:
            import deap.base
            import deap.creator
            import deap.tools
        except ImportError:
            raise ImportError("DEAP is not installed. Run: pip install deap")

        self._bounds = bounds
        self._rng    = random.Random(random_state)
        np.random.seed(random_state)

        # Guard against re-creating types in the same process
        if not hasattr(deap.creator, "FitnessMax_MAESTRO"):
            deap.creator.create("FitnessMax_MAESTRO", deap.base.Fitness, weights=(1.0,))
        if not hasattr(deap.creator, "Individual_MAESTRO"):
            deap.creator.create(
                "Individual_MAESTRO", list,
                fitness=deap.creator.FitnessMax_MAESTRO,
            )

        toolbox = deap.base.Toolbox()

        def _random_individual():
            return deap.creator.Individual_MAESTRO(
                [self._rng.uniform(lo, hi) for lo, hi in bounds]
            )

        toolbox.register("individual", _random_individual)
        toolbox.register("population", deap.tools.initRepeat, list, toolbox.individual)
        toolbox.register(
            "mate", deap.tools.cxSimulatedBinaryBounded,
            low=[lo for lo, _ in bounds],
            up=[hi for _, hi in bounds],
            eta=20.0,
        )
        toolbox.register(
            "mutate", deap.tools.mutPolynomialBounded,
            low=[lo for lo, _ in bounds],
            up=[hi for _, hi in bounds],
            eta=20.0, indpb=0.2,
        )
        toolbox.register("select", deap.tools.selTournament, tournsize=3)

        self._toolbox    = toolbox
        self._population = toolbox.population(n=self._pop_size)

    def suggest(self) -> List[float]:
        if self._toolbox is None or self._population is None:
            raise RuntimeError("Optimiser not initialised.")

        if not self._history_y:
            ind = self._toolbox.individual()
            self._pending_individual = ind
            return list(ind)

        # Assign fitness to previously evaluated individuals
        evaluated_count = min(len(self._history_y), len(self._population))
        for ind, y in zip(self._population[:evaluated_count], self._history_y[-evaluated_count:]):
            ind.fitness.values = (y,)

        # Evolve one generation
        offspring = self._toolbox.select(self._population, len(self._population))
        offspring = list(map(self._toolbox.clone, offspring))

        for child1, child2 in zip(offspring[::2], offspring[1::2]):
            if self._rng.random() < 0.7:
                self._toolbox.mate(child1, child2)
                del child1.fitness.values
                del child2.fitness.values

        for mutant in offspring:
            if self._rng.random() < 0.2:
                self._toolbox.mutate(mutant)
                del mutant.fitness.values

        self._population[:] = offspring

        # Return first unevaluated individual
        for ind in self._population:
            if not ind.fitness.valid:
                self._pending_individual = ind
                return list(ind)

        # Fallback: fresh random individual
        ind = self._toolbox.individual()
        self._pending_individual = ind
        return list(ind)

    def update(self, x: List[float], y: float) -> None:
        self._history_x.append(list(x))
        self._history_y.append(y)
        if self._pending_individual is not None:
            self._pending_individual.fitness.values = (y,)
            self._pending_individual = None

    def best_so_far(self) -> Tuple[Optional[List[float]], Optional[float]]:
        if not self._history_y:
            return None, None
        best_idx = int(np.argmax(self._history_y))
        return self._history_x[best_idx], self._history_y[best_idx]