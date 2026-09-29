"""
live_simulator.py - Live Operational Simulation & NASA POWER Weather Engine
Smart Energy, Solar & Grid-Aware Operations AI

This module implements:
1. One Central Shared Live Operational State (updating every ~5 seconds) using current calendar time (e.g., 2026-09-24)
   mapped to historical building profiles (2016-2017 BDG2/ComStock data).
2. Physical consistency: Solar follows daylight/irradiance, load follows time-of-day/occupancy/temperature,
   grid import maintains conservation of energy.
3. NASA POWER Weather Integration for Amman, Jordan (31.95°N, 35.93°E) with timezone-aware conversion
   (NASA UTC Observation vs Asia/Amman Civil Time) with caching & graceful fallback.
4. Complete separation: Does NOT alter historical database records or original datasets.
"""

from __future__ import annotations
import datetime as dt
import math
import random
import time
import requests
import database

# Location: Amman, Jordan (default)
LATITUDE = 31.9539
LONGITUDE = 35.9106

# NASA POWER Cache
_weather_cache = {
    "data": None,
    "last_fetched": 0.0,
    "observation_time": None,
    "source": "NASA POWER",
    "is_fallback": False,
    "error_msg": None
}

CACHE_TTL_SECONDS = 1800  # 30 minutes cache for NASA POWER API


def fetch_nasa_power_weather() -> dict:
    """
    Retrieves hourly weather & solar radiation from NASA POWER API.
    Handles UTC to Asia/Amman timezone conversion cleanly.
    Uses local caching and provides graceful fallback if network/API is unavailable.
    """
    now = time.time()
    if _weather_cache["data"] and (now - _weather_cache["last_fetched"] < CACHE_TTL_SECONDS):
        return _weather_cache["data"]

    today = dt.date.today()
    start_date = (today - dt.timedelta(days=3)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    url = (
        "https://power.larc.nasa.gov/api/temporal/hourly/point"
        f"?parameters=T2M,RH2M,ALLSKY_SFC_SW_DWN,WS10M"
        f"&community=RE"
        f"&longitude={LONGITUDE}&latitude={LATITUDE}"
        f"&start={start_date}&end={end_date}"
        f"&format=JSON"
    )

    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            payload = res.json()
            params = payload.get("properties", {}).get("parameter", {})
            t2m_dict = params.get("T2M", {})
            rh_dict = params.get("RH2M", {})
            sw_dict = params.get("ALLSKY_SFC_SW_DWN", {})
            ws_dict = params.get("WS10M", {})

            # Filter valid keys (NASA POWER uses -999.0 for missing data)
            valid_keys = [k for k, v in t2m_dict.items() if v is not None and v > -100]

            if valid_keys:
                latest_key = sorted(valid_keys)[-1]  # Format: YYYYMMDDHH
                year = int(latest_key[:4])
                month = int(latest_key[4:6])
                day = int(latest_key[6:8])
                hour = int(latest_key[8:10])

                utc_dt = dt.datetime(year, month, day, hour)
                # Convert UTC to Asia/Amman (UTC+3)
                jordan_dt = utc_dt + dt.timedelta(hours=3)

                nasa_utc_str = f"{utc_dt.strftime('%Y-%m-%d %H:00')} UTC"
                jordan_local_str = f"{jordan_dt.strftime('%Y-%m-%d %I:00 %p')} (Asia/Amman)"

                temp = t2m_dict.get(latest_key, 25.0)
                rh = rh_dict.get(latest_key, 45.0)
                irradiance = max(0.0, sw_dict.get(latest_key, 0.0))
                wind = ws_dict.get(latest_key, 3.5)

                if temp > -100 and rh > -100 and irradiance > -100 and wind > -100:
                    result = {
                        "temperature_c": round(float(temp), 1),
                        "humidity_pct": round(float(rh), 1),
                        "solar_irradiance_wm2": round(float(irradiance), 1),
                        "wind_speed_ms": round(float(wind), 1),
                        "source": "NASA POWER",
                        "nasa_observation_utc": nasa_utc_str,
                        "jordan_local_time": jordan_local_str,
                        "observation_hour": f"{jordan_dt.strftime('%I:%00 %p')}",
                        "is_fallback": False,
                        "last_retrieved_at": dt.datetime.now().strftime("%H:%M:%S")
                    }

                    _weather_cache["data"] = result
                    _weather_cache["last_fetched"] = now
                    return result
    except Exception as exc:
        _weather_cache["error_msg"] = str(exc)

    # Fallback if NASA POWER API fails, returns invalid fill values, or is unreachable
    last_valid = _weather_cache["data"]
    if last_valid:
        fallback = dict(last_valid)
        fallback["is_fallback"] = True
        fallback["source"] = "NASA POWER (Cached Fallback)"
        return fallback

    # Climatological fallback for Amman, Jordan
    now_dt = dt.datetime.now()
    current_hour = now_dt.hour
    is_day = 6 <= current_hour <= 18
    est_temp = 28.0 if is_day else 18.0
    est_sw = max(0.0, 700.0 * math.sin(math.pi * (current_hour - 6) / 12)) if is_day else 0.0

    return {
        "temperature_c": round(est_temp, 1),
        "humidity_pct": 42.0,
        "solar_irradiance_wm2": round(est_sw, 1),
        "wind_speed_ms": 3.8,
        "source": "NASA POWER (Climatological Fallback)",
        "nasa_observation_utc": now_dt.strftime("%Y-%m-%d %H:00 UTC"),
        "jordan_local_time": f"{now_dt.strftime('%Y-%m-%d %I:00 %p')} (Asia/Amman)",
        "observation_hour": now_dt.strftime("%I:00 %p"),
        "is_fallback": True,
        "last_retrieved_at": now_dt.strftime("%H:%M:%S")
    }


def get_live_operational_state(building_id: str = "CAMPUS") -> dict:
    """
    Computes the live operational state updating every ~5 seconds.
    Uses the current calendar date (2026-09-24 HH:MM:SS) while mapping
    building load profiles from historical dataset truth.
    """
    now = dt.datetime.now()
    weather = fetch_nasa_power_weather()

    # Map current calendar month/day/hour/minute to historical row
    hist_year = 2017
    hist_month = now.month
    hist_day = min(now.day, 28 if hist_month == 2 else 30)
    hist_hour = now.hour
    hist_minute = (now.minute // 15) * 15  # 15-min step

    historical_timestamp_str = f"{hist_year:04d}-{hist_month:02d}-{hist_day:02d} {hist_hour:02d}:{hist_minute:02d}:00"

    # Query historical record as baseline profile
    b_target = "B001" if building_id == "CAMPUS" else building_id
    hist_reading = database.get_energy_reading_at(b_target, historical_timestamp_str)

    if not hist_reading:
        hist_reading = database.get_latest_energy_reading(b_target) or {}

    base_load = hist_reading.get("energy_kw", 300.0) or 300.0
    base_hvac = hist_reading.get("hvac_kw", 100.0) or 100.0
    base_occ = hist_reading.get("occupancy_pct", 50.0) or 50.0

    # Apply realistic current environmental adjustment & small sensor noise (+/- 1.5%)
    noise_factor = 1.0 + random.uniform(-0.015, 0.015)
    temp_c = weather["temperature_c"]

    temp_hvac_factor = 1.0 + max(0.0, (temp_c - 22.0) * 0.02)
    adjusted_hvac = round(base_hvac * temp_hvac_factor * noise_factor, 1)

    adjusted_load = round((base_load + (adjusted_hvac - base_hvac)) * noise_factor, 1)
    adjusted_load = max(10.0, adjusted_load)

    # Solar generation strictly follows solar irradiance & daylight hour
    irradiance = weather["solar_irradiance_wm2"]
    pv_capacity_kw = 200.0 if building_id == "CAMPUS" else 60.0
    
    # Night time check (before 06:00 or after 19:00)
    if now.hour < 6 or now.hour >= 19:
        solar_kw = 0.0
    else:
        solar_kw = round((irradiance / 1000.0) * pv_capacity_kw * 0.85 * noise_factor, 1)
        solar_kw = max(0.0, solar_kw)

    # Conservation of Energy: Grid Import = Total Load - Solar
    grid_import_kw = round(max(0.0, adjusted_load - solar_kw), 1)

    current_operational_time = now.strftime("%B %d, %Y %H:%M:%S")
    iso_operational_time = now.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "status": "LIVE_SIMULATION",
        "operational_time": current_operational_time,
        "iso_operational_time": iso_operational_time,
        "historical_source_time": historical_timestamp_str,
        "building_id": building_id,
        "current_load_kw": adjusted_load,
        "hvac_kw": adjusted_hvac,
        "solar_kw": solar_kw,
        "grid_import_kw": grid_import_kw,
        "occupancy_pct": round(base_occ, 1),
        "weather": weather,
        "provenance": {
            "building_load": "Historical profile + environmental simulation",
            "solar": "PV model + NASA POWER irradiance",
            "weather": weather["source"],
            "prediction": "Existing ML model",
            "anomaly": "Existing anomaly detection",
            "decision": "Existing AI agent"
        },
        "last_updated": now.strftime("%H:%M:%S")
    }
