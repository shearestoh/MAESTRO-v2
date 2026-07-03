"""
Adapter for the Potentiostat (demo simulation).

Measures specific energy of a prepared electrode sample using a validated
surrogate model of a 4680-format battery cell.

To replace with a real instrument:
  - Implement measure() to call the potentiostat's measurement API
  - Remove the surrogate model and noise injection
  - Return actual measured values from the instrument
"""
from __future__ import annotations
import numpy as np
from typing import Dict

from app.adapters.surrogate import predict_specific_energy

NOISE_SIGMA = 0.5


def measure(params: Dict[str, float], conditions: Dict[str, float]) -> float:
    am    = params.get("active_material", 93.0)
    por   = params.get("porosity", 40.0)
    power = conditions.get("power_W", 150.0)

    true_val = predict_specific_energy(float(am), float(por), float(power))
    return float(true_val + np.random.normal(0.0, NOISE_SIGMA))