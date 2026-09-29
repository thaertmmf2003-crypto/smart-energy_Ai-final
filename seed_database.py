"""
seed_database.py — Seeds energy.db from processed CSV files (single source of truth).

Processed CSV column → DB column mapping:
  energy_readings.csv : energy            → energy_kw
  hvac_readings.csv   : hvac_power_kw     → hvac_kw
  occupancy.csv       : occupancy_percent → occupancy_pct
  solar_readings.csv  : solar_generation_kw→ solar_kw  (also in solar_readings table)
  ev_charging.csv     : ev_charging_power_kw → ev_kw
  weather_data.csv    : temperature_c     → temperature_c  (joined by timestamp)

Run:
    python seed_database.py

The script is idempotent — safe to run multiple times.
"""

import sys
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"

# Import database using absolute path so it resolves DB_PATH correctly
sys.path.insert(0, str(BASE_DIR))
import database
import init_db

# =========================================================
# EXPECTED ROW COUNTS (validate after seeding)
# =========================================================
EXPECTED_BUILDINGS = {"B001", "B002", "B003"}
EXPECTED_TIMESTAMPS = 17_544          # hourly rows per building
EXPECTED_BUILDINGS_COUNT = 3
EXPECTED_READINGS = EXPECTED_TIMESTAMPS * EXPECTED_BUILDINGS_COUNT  # 52 632


def _load_csv(name: str) -> pd.DataFrame:
    path = PROCESSED_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Processed file not found: {path}")
    return pd.read_csv(path)


def _validate_buildings(df: pd.DataFrame, col: str = "building_id") -> None:
    found = set(df[col].unique())
    if found != EXPECTED_BUILDINGS:
        print(f"  WARNING: building IDs in CSV = {found} (expected {EXPECTED_BUILDINGS})")


def seed():
    print("=" * 60)
    print("SMART ENERGY AI — DATABASE SEEDING")
    print("=" * 60)

    # ── Init schema ──────────────────────────────────────────
    print("\n[1/7] Initialising schema ...")
    init_db.init_db(str(database.DB_PATH))
    print(f"      DB path: {database.DB_PATH}")

    # ── Buildings ────────────────────────────────────────────
    print("\n[2/7] Ensuring canonical buildings ...")
    buildings = [
        ("B001", "Administration", "Administration & Executive Offices"),
        ("B002", "Labs",           "Research & Computer Laboratories"),
        ("B003", "Classrooms",     "Lectures & Teaching Classrooms"),
    ]
    for b_id, name, desc in buildings:
        database.add_building(b_id, name, desc)
    print(f"      Buildings OK: {[b[0] for b in buildings]}")

    # ── Load all processed CSVs ───────────────────────────────
    print("\n[3/7] Loading processed CSVs ...")

    energy_df   = _load_csv("energy_readings.csv")   # cols: timestamp, building_id, energy
    hvac_df     = _load_csv("hvac_readings.csv")      # cols: timestamp, building_id, hvac_power_kw
    occupancy_df= _load_csv("occupancy.csv")          # cols: timestamp, building_id, occupancy_percent
    solar_df    = _load_csv("solar_readings.csv")     # cols: timestamp, building_id, solar_generation_kw
    ev_df       = _load_csv("ev_charging.csv")        # cols: timestamp, building_id, ev_charging_power_kw
    weather_df  = _load_csv("weather_data.csv")       # cols: timestamp, temperature_c, ...

    # Validate shape
    for name, df in [("energy", energy_df), ("hvac", hvac_df),
                     ("occupancy", occupancy_df), ("solar", solar_df), ("ev", ev_df)]:
        if len(df) != EXPECTED_READINGS:
            raise ValueError(
                f"ABORT: {name} CSV has {len(df)} rows — expected {EXPECTED_READINGS}. "
                "Do not seed from inconsistent data."
            )
        _validate_buildings(df)

    if len(weather_df) != EXPECTED_TIMESTAMPS:
        raise ValueError(
            f"ABORT: weather_data CSV has {len(weather_df)} rows — "
            f"expected {EXPECTED_TIMESTAMPS} hourly rows."
        )

    print(f"      energy_readings : {len(energy_df):,} rows  ✓")
    print(f"      hvac_readings   : {len(hvac_df):,} rows  ✓")
    print(f"      occupancy       : {len(occupancy_df):,} rows  ✓")
    print(f"      solar_readings  : {len(solar_df):,} rows  ✓")
    print(f"      ev_charging     : {len(ev_df):,} rows  ✓")
    print(f"      weather_data    : {len(weather_df):,} rows  ✓")

    # ── Merge into master DataFrame ───────────────────────────
    print("\n[4/7] Merging datasets (key: timestamp + building_id) ...")

    # Rename CSV columns → DB columns
    energy_df   = energy_df.rename(columns={"energy": "energy_kw"})
    hvac_df     = hvac_df.rename(columns={"hvac_power_kw": "hvac_kw"})
    occupancy_df= occupancy_df.rename(columns={"occupancy_percent": "occupancy_pct"})
    solar_df    = solar_df.rename(columns={"solar_generation_kw": "solar_kw"})
    ev_df       = ev_df.rename(columns={"ev_charging_power_kw": "ev_kw"})
    weather_df  = weather_df[["timestamp", "temperature_c"]]   # campus-level, join by timestamp only

    master = (
        energy_df[["timestamp", "building_id", "energy_kw"]]
        .merge(hvac_df[["timestamp", "building_id", "hvac_kw"]],
               on=["timestamp", "building_id"], how="left")
        .merge(occupancy_df[["timestamp", "building_id", "occupancy_pct"]],
               on=["timestamp", "building_id"], how="left")
        .merge(solar_df[["timestamp", "building_id", "solar_kw"]],
               on=["timestamp", "building_id"], how="left")
        .merge(ev_df[["timestamp", "building_id", "ev_kw"]],
               on=["timestamp", "building_id"], how="left")
        .merge(weather_df,                        # campus weather — join by timestamp only
               on="timestamp", how="left")
    )

    # Fill any NaN introduced by left-joins with 0.0
    for col in ["energy_kw", "hvac_kw", "occupancy_pct", "solar_kw", "ev_kw", "temperature_c"]:
        master[col] = master[col].fillna(0.0)

    if len(master) != EXPECTED_READINGS:
        raise ValueError(
            f"ABORT: merged master has {len(master)} rows — "
            f"expected {EXPECTED_READINGS}. Check for missing join keys."
        )

    print(f"      Master rows: {len(master):,}  ✓")

    # ── Clear old operational data ────────────────────────────
    print("\n[5/7] Clearing old operational data ...")
    with database.get_connection() as conn:
        conn.execute("DELETE FROM energy_readings;")
        conn.execute("DELETE FROM solar_readings;")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('energy_readings','solar_readings');")
    print("      energy_readings cleared  ✓")
    print("      solar_readings  cleared  ✓")

    # ── Seed energy_readings ──────────────────────────────────
    print("\n[6/7] Seeding energy_readings ...")
    energy_records = [
        (
            str(row["timestamp"]),
            str(row["building_id"]),
            float(row["energy_kw"]),
            float(row["hvac_kw"]),
            float(row["occupancy_pct"]),
            float(row["solar_kw"]),
            float(row["ev_kw"]),
            float(row["temperature_c"]),
        )
        for _, row in master.iterrows()
    ]
    with database.get_connection() as conn:
        conn.executemany("""
            INSERT INTO energy_readings
                (timestamp, building_id, energy_kw, hvac_kw, occupancy_pct, solar_kw, ev_kw, temperature_c)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, energy_records)

    # ── Seed solar_readings ───────────────────────────────────
    print("      Seeding solar_readings ...")
    solar_records = [
        (
            str(row["timestamp"]),
            str(row["building_id"]),
            float(row["solar_kw"]),
            float(row["temperature_c"]),
        )
        for _, row in master.iterrows()
    ]
    with database.get_connection() as conn:
        conn.executemany("""
            INSERT INTO solar_readings (timestamp, building_id, solar_kw, temperature_c)
            VALUES (?, ?, ?, ?);
        """, solar_records)

    # ── Validate row counts ───────────────────────────────────
    print("\n[7/7] Validating seeded row counts ...")
    with database.get_connection() as conn:
        er_count = conn.execute("SELECT COUNT(*) FROM energy_readings").fetchone()[0]
        sr_count = conn.execute("SELECT COUNT(*) FROM solar_readings").fetchone()[0]

    errors = []
    if er_count != EXPECTED_READINGS:
        errors.append(f"energy_readings: got {er_count}, expected {EXPECTED_READINGS}")
    if sr_count != EXPECTED_READINGS:
        errors.append(f"solar_readings:  got {sr_count}, expected {EXPECTED_READINGS}")

    if errors:
        raise RuntimeError("POST-SEED VALIDATION FAILED:\n  " + "\n  ".join(errors))

    print(f"      energy_readings : {er_count:,}  ✓")
    print(f"      solar_readings  : {sr_count:,}  ✓")
    print("\n" + "=" * 60)
    print("SEEDING COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    seed()
