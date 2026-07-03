"""
Adapter for the Electrode Coater (demo simulation).

Simulates slurry coating and calendering for battery electrode preparation.
Failure probability increases at high active material content and low porosity,
reflecting real-world processing constraints.

To replace with a real instrument:
  - Implement prepare() to call the instrument's control API
  - Remove the stochastic failure model
  - Return actual preparation status from the instrument
"""
from __future__ import annotations
import numpy as np
from typing import Dict


BASE_FAIL_PROB = 0.06


def failure_probability(params: Dict[str, float]) -> float:
    am  = params.get("active_material", 93.0)
    por = params.get("porosity", 40.0)
    am_factor  = max(0.0, (float(am)  - 94.5) / 1.5)
    por_factor = max(0.0, (35.0 - float(por)) / 5.0)
    p = BASE_FAIL_PROB + 0.06 * am_factor + 0.07 * por_factor
    return float(min(0.25, max(0.0, p)))


def prepare(params: Dict[str, float]) -> Dict:
    fail_prob = failure_probability(params)
    if np.random.rand() < fail_prob:
        return {
            "status":              "failed",
            "reason":              "Sample preparation defect",
            "failure_probability": fail_prob,
        }
    return {
        "status":              "ok",
        "params":              params,
        "failure_probability": fail_prob,
    }