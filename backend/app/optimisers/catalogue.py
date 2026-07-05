"""
Optimisation algorithm catalogue.

Built-in: gp_bo (scikit-optimize), random (uniform random search).
Optional: optuna (TPE) — installed separately with: pip install optuna

To add a new optimiser:
1. Implement BaseOptimiser in a new module under app/optimisers/
2. Add an entry to OPTIMISER_CATALOGUE (or register dynamically below)
"""
from __future__ import annotations

import warnings
from typing import Dict, Type

from app.optimisers.base import BaseOptimiser
from app.optimisers.random_search import RandomSearchOptimiser
from app.optimisers.gp_bo import GPBayesianOptimiser

OPTIMISER_CATALOGUE: Dict[str, Type[BaseOptimiser]] = {
    "random": RandomSearchOptimiser,
    "gp_bo":  GPBayesianOptimiser,
}

try:
    from app.optimisers.optuna_bo import OptunaOptimiser
    OPTIMISER_CATALOGUE["optuna"] = OptunaOptimiser
except ImportError:
    pass


def get_optimiser(name: str) -> BaseOptimiser:
    """
    Return an instantiated optimiser by name.

    Falls back to GP-BO with a warning if the requested optimiser is not
    available (e.g. optional dependency not installed).
    """
    if name in OPTIMISER_CATALOGUE:
        return OPTIMISER_CATALOGUE[name]()

    warnings.warn(
        f"Optimiser '{name}' not found in catalogue. "
        f"Available: {list(OPTIMISER_CATALOGUE.keys())}. "
        f"Falling back to GP-BO.",
        RuntimeWarning,
        stacklevel=2,
    )
    return OPTIMISER_CATALOGUE["gp_bo"]()