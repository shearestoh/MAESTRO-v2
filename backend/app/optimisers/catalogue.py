"""
Optimisation algorithm catalogue.

Built-in (always available):
  gp_bo   — scikit-optimize Gaussian Process BO
  random  — uniform random search

Optional (install separately):
  optuna   — pip install optuna
  honegumi — pip install ax-platform
  deap     — pip install deap
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

# ── Register optional optimisers if installed ─────────────────────────────────

try:
    from app.optimisers.optuna_bo import OptunaOptimiser
    OPTIMISER_CATALOGUE["optuna"] = OptunaOptimiser
except (ImportError, Exception):
    pass

try:
    from app.optimisers.honegumi_bo import HonegumiOptimiser
    OPTIMISER_CATALOGUE["honegumi"] = HonegumiOptimiser
    OPTIMISER_CATALOGUE["ax"]       = HonegumiOptimiser  # alias
except (ImportError, Exception):
    pass

try:
    from app.optimisers.deap_bo import DEAPOptimiser
    OPTIMISER_CATALOGUE["deap"]        = DEAPOptimiser
    OPTIMISER_CATALOGUE["evolutionary"] = DEAPOptimiser  # alias
except (ImportError, Exception):
    pass

try:
    from app.optimisers.llm_bo import MAESTROLLMOptimiser
    OPTIMISER_CATALOGUE["llm_bo"]    = MAESTROLLMOptimiser
    OPTIMISER_CATALOGUE["oracle_bo"] = MAESTROLLMOptimiser
except Exception:
    pass


def get_optimiser(name: str) -> BaseOptimiser:
    """
    Return an instantiated optimiser by name.

    Normalises common aliases before lookup.
    Falls back to GP-BO with a warning if not found.
    """
    # Normalise aliases
    aliases = {
        "gp-bo":          "gp_bo",
        "gp bo":          "gp_bo",
        "bayesian":       "gp_bo",
        "scikit":         "gp_bo",
        "scikit-optimize":"gp_bo",
        "skopt":          "gp_bo",
        "random search":  "random",
        "random_search":  "random",
        "tpe":            "optuna",
        "ax":             "honegumi",
        "ax-platform":    "honegumi",
        "evolution":      "deap",
        "evolutionary":   "deap",
        "genetic":        "deap",
        "llm":       "llm_bo",
        "oracle":    "llm_bo",
        "llm-bo":    "llm_bo",
        "oracle-bo": "llm_bo",
    }
    normalised = aliases.get(name.lower().strip(), name.lower().strip())

    if normalised in OPTIMISER_CATALOGUE:
        return OPTIMISER_CATALOGUE[normalised]()

    warnings.warn(
        f"Optimiser '{name}' (normalised: '{normalised}') not found. "
        f"Available: {list(OPTIMISER_CATALOGUE.keys())}. "
        f"Falling back to GP-BO. "
        f"Install optional optimisers: pip install optuna ax-platform deap",
        RuntimeWarning,
        stacklevel=2,
    )
    return OPTIMISER_CATALOGUE["gp_bo"]()


def list_available() -> Dict[str, str]:
    """Return dict of {key: description} for all registered optimisers."""
    return {
        key: cls().description
        for key, cls in OPTIMISER_CATALOGUE.items()
    }