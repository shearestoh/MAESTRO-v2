from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple


class BaseOptimiser(ABC):
    """Abstract base for all optimisation algorithms available to MAESTRO."""

    name:        str
    description: str

    @abstractmethod
    def initialise(
        self,
        bounds:           List[Tuple[float, float]],
        n_initial_points: int,
        random_state:     int = 42,
    ) -> None:
        pass

    @abstractmethod
    def suggest(self) -> List[float]:
        pass

    @abstractmethod
    def update(self, x: List[float], y: float) -> None:
        pass

    @abstractmethod
    def best_so_far(self) -> Tuple[Optional[List[float]], Optional[float]]:
        pass