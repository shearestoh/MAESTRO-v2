"""
Surrogate model for the battery electrode specific energy prediction.

Fitted to experimental data from a 4680-format cell at five power levels.
Used by the Potentiostat adapter to simulate electrochemical measurements.

This file is specific to the demo instruments. Remove or replace when
deploying MAESTRO with real instruments.
"""
import numpy as np

_A   = np.array([32.83, 19.41, 5.12, 3.86, 3.16])
_x0  = np.array([96.86, 94.92, 93.86, 93.48, 93.11])
_y0  = np.array([29.53, 36.95, 40.96, 42.32, 43.48])
_sx  = np.array([4.92,  5.06,  2.88, 2.68, 2.64])
_sy  = np.array([28.29, 30.01, 16.42, 14.88, 14.80])
_th  = np.array([0.200, 0.204, 0.210, 0.194, 0.184])
_B   = np.array([84.90, 44.07, 31.27, 24.48, 19.58])
_Z   = np.array([70.0, 110.0, 150.0, 170.0, 190.0])


def predict_specific_energy(active_material: float, porosity: float, power_W: float) -> float:
    z = float(power_W)
    x = float(active_material)
    y = float(porosity)

    A  = float(np.interp(z, _Z, _A))
    x0 = float(np.interp(z, _Z, _x0))
    y0 = float(np.interp(z, _Z, _y0))
    sx = float(np.interp(z, _Z, _sx))
    sy = float(np.interp(z, _Z, _sy))
    th = float(np.interp(z, _Z, _th))
    B  = float(np.interp(z, _Z, _B))

    ct, st = np.cos(th), np.sin(th)
    Xp = ct * (x - x0) + st * (y - y0)
    Yp = -st * (x - x0) + ct * (y - y0)
    Q  = (Xp**2) / (2 * sx**2) + (Yp**2) / (2 * sy**2)
    return float(A * np.exp(-Q) + B)