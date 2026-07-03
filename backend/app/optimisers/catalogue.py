"""
Optimisation algorithm catalogue.

Add new optimisers here by:
1. Implementing BaseOptimiser in a new module
2. Adding an entry to OPTIMISER_CATALOGUE

The agent reads the catalogue descriptions to select the appropriate
algorithm for any given task.
"""
from __future__ import annotations
from typing import Dict, Type
from app.optimisers.base import BaseOptimiser
from app.optimisers.random_search import RandomSearchOptimiser
from app.optimisers.gp_bo import GPBayesianOptimiser

OPTIMISER_CATALOGUE: Dict[str, Type[BaseOptimiser]] = {
    "random": RandomSearchOptimiser,
    "gp_bo":  GPBayesianOptimiser,
}


def get_optimiser(name: str) -> BaseOptimiser:
    if name not in OPTIMISER_CATALOGUE:
        available = list(OPTIMISER_CATALOGUE.keys())
        raise ValueError(f"Unknown optimiser '{name}'. Available: {available}")
    return OPTIMISER_CATALOGUE[name]()