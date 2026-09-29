"""
impact_translation.py — turn a kW reduction into money and carbon.

Why this exists
---------------
Every action in this project is scored in kW. A judge, an operator, or a
sustainability officer does not think in kW — they think in dinars on the
bill and in kilograms of CO2 avoided. This module is the single place that
converts one into the other, so the dashboard, the Digital Twin experiment
and the PDF report all quote the same numbers.

Nothing here controls equipment or writes files. It is pure arithmetic over
constants, exposed through small functions and one factors dict.

Units
-----
A recommendation reduces load by `reduction_kw` for the one-hour event
window. Energy avoided in that hour is therefore:

    energy_kwh = reduction_kw * DURATION_HOURS   (DURATION_HOURS = 1.0)

Money and carbon are then linear in energy.

Constants
---------
TARIFF_JOD_PER_KWH
    Jordan large-consumer / commercial electricity price. Public EDCO / JEPCO
    commercial tariffs sit around 0.10-0.16 JOD/kWh depending on band; 0.14 is
    a representative mid-band figure. Override with the ELECTRICITY_TARIFF_JOD
    environment variable to match a specific site's bill.

GRID_CO2_KG_PER_KWH
    Grid emission factor for Jordan's mostly gas-and-oil generation mix, about
    0.55 kg CO2e per kWh. Override with GRID_CO2_FACTOR.

These are estimates, and the code labels them as such. They are not measured
from the site.
"""

from __future__ import annotations

import os
from typing import Any, Dict

# One event covers a single hour of the dataset.
DURATION_HOURS = 1.0


def _env_float(name: str, default: float) -> float:
    """Read a float from the environment, falling back to default on anything odd."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


# JOD per kWh — representative Jordan commercial mid-band tariff.
TARIFF_JOD_PER_KWH = _env_float("ELECTRICITY_TARIFF_JOD", 0.14)

# kg CO2e per kWh — representative Jordan grid emission factor.
GRID_CO2_KG_PER_KWH = _env_float("GRID_CO2_FACTOR", 0.55)


def energy_kwh(reduction_kw: float) -> float:
    """kWh avoided in the one-hour event window."""
    return max(0.0, float(reduction_kw)) * DURATION_HOURS


def money_jod(reduction_kw: float) -> float:
    """Bill saving in Jordanian dinars for one event."""
    return energy_kwh(reduction_kw) * TARIFF_JOD_PER_KWH


def carbon_kg(reduction_kw: float) -> float:
    """CO2e avoided in kilograms for one event."""
    return energy_kwh(reduction_kw) * GRID_CO2_KG_PER_KWH


def translate(reduction_kw: float) -> Dict[str, Any]:
    """
    Full translation of one reduction into energy, money and carbon.

    Returns rounded, display-ready numbers plus the factors used, so the
    caller can show 'at 0.14 JOD/kWh' next to the figure.
    """
    kwh = energy_kwh(reduction_kw)
    return {
        "reduction_kw": round(float(reduction_kw), 2),
        "energy_kwh": round(kwh, 2),
        "money_jod": round(kwh * TARIFF_JOD_PER_KWH, 3),
        "carbon_kg": round(kwh * GRID_CO2_KG_PER_KWH, 2),
        "is_estimate": True,
    }


def factors() -> Dict[str, Any]:
    """The constants themselves, for endpoints and client-side mirroring."""
    return {
        "tariff_jod_per_kwh": TARIFF_JOD_PER_KWH,
        "grid_co2_kg_per_kwh": GRID_CO2_KG_PER_KWH,
        "duration_hours": DURATION_HOURS,
        "currency": "JOD",
        "note": (
            "Estimates. Tariff is a representative Jordan commercial mid-band "
            "price; carbon uses a national grid emission factor. Not measured "
            "on site. Override with the ELECTRICITY_TARIFF_JOD and "
            "GRID_CO2_FACTOR environment variables."
        ),
    }


if __name__ == "__main__":
    print("factors:", factors())
    for kw in (10, 34.47, 100):
        print(kw, "kW ->", translate(kw))
