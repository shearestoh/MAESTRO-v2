"""
The ground-truth surrogate function for the battery optimisation problem.

This is a 2D rotated Gaussian that models specific energy (Wh/kg) as a
function of active material (%), porosity (%), and discharge power (W).

In a real SDL, this would be replaced by actual instrument measurements.
Here it lets us simulate a realistic, non-trivial optimisation landscape
with a known global optimum — useful for benchmarking BO strategies.
"""
import numpy as np

# Gaussian parameters fitted at 5 power levels: 70, 110, 150, 170, 190 W
_A   = np.array([32.83, 19.41, 5.12, 3.86, 3.16])
_x0  = np.array([96.86, 94.92, 93.86, 93.48, 93.11])
_y0  = np.array([29.53, 36.95, 40.96, 42.32, 43.48])
_sx  = np.array([4.92,  5.06,  2.88, 2.68, 2.64])
_sy  = np.array([28.29, 30.01, 16.42, 14.88, 14.80])
_th  = np.array([0.200, 0.204, 0.210, 0.194, 0.184])
_B   = np.array([84.90, 44.07, 31.27, 24.48, 19.58])
_Z   = np.array([70.0, 110.0, 150.0, 170.0, 190.0])


def predict_f(x: float, y: float, z: float) -> float:
    """
    Predict specific energy (Wh/kg) at:
      x = active_material (%)
      y = porosity (%)
      z = power_W (W)
    
    Uses linear interpolation between the 5 calibrated power levels.
    """
    x, y, z = float(x), float(y), float(z)

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