"""
Prepare selected BDG2 building electricity data
for the Smart Energy AI project.
"""

from pathlib import Path
import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIRECTORY = Path(__file__).resolve().parent

RAW_DIRECTORY = BASE_DIRECTORY / "data" / "raw" / "building_data_genome"

PROCESSED_DIRECTORY = BASE_DIRECTORY / "data" / "processed"

ELECTRICITY_PATH = RAW_DIRECTORY / "electricity_cleaned.txt"

METADATA_PATH = RAW_DIRECTORY / "metadata.txt"


# =========================================================
# CAMPUS MAPPING
# =========================================================

CAMPUS_BUILDINGS = {
    "B001": {
        "building_name": "Administration",
        "building_type": "administration",
        "source_building_id": "Robin_office_Gayle",
    },
    "B002": {
        "building_name": "Labs",
        "building_type": "laboratory",
        "source_building_id": "Robin_education_Megan",
    },
    "B003": {
        "building_name": "Classrooms",
        "building_type": "classroom",
        "source_building_id": "Robin_education_Kiera",
    },
}


# =========================================================
# CREATE OUTPUT DIRECTORY
# =========================================================

PROCESSED_DIRECTORY.mkdir(
    parents=True,
    exist_ok=True,
)


# =========================================================
# PREPARE BUILDING METADATA
# =========================================================


def prepare_buildings():

    metadata = pd.read_csv(METADATA_PATH)

    records = []

    for campus_id, config in CAMPUS_BUILDINGS.items():

        source_id = config["source_building_id"]

        source_row = metadata[metadata["building_id"] == source_id]

        if source_row.empty:
            raise ValueError(f"Building not found: {source_id}")

        source_row = source_row.iloc[0]

        records.append(
            {
                "building_id": campus_id,
                "building_name": config["building_name"],
                "building_type": config["building_type"],
                "floor_area_m2": source_row["sqm"],
                "source_building_id": source_id,
                "source_site_id": source_row["site_id"],
                "source_type": source_row["sub_primaryspaceusage"],
                "data_source": "Building Data Genome 2",
            }
        )

    buildings = pd.DataFrame(records)

    output_path = PROCESSED_DIRECTORY / "buildings.csv"

    buildings.to_csv(
        output_path,
        index=False,
    )

    print("\nBuildings:")
    print(buildings.to_string(index=False))

    print(f"\nSaved: {output_path}")

    return buildings


# =========================================================
# PREPARE ENERGY DATA
# =========================================================


def prepare_energy_readings():

    source_mapping = {
        config["source_building_id"]: campus_id
        for campus_id, config in CAMPUS_BUILDINGS.items()
    }

    columns = [
        "timestamp",
        *source_mapping.keys(),
    ]

    electricity = pd.read_csv(
        ELECTRICITY_PATH,
        usecols=columns,
        parse_dates=["timestamp"],
    )

    # Wide format -> Long format
    energy = electricity.melt(
        id_vars="timestamp",
        var_name="source_building_id",
        value_name="energy",
    )

    # Convert source IDs to campus IDs
    energy["building_id"] = energy["source_building_id"].map(source_mapping)

    energy = energy[
        [
            "timestamp",
            "building_id",
            "source_building_id",
            "energy",
        ]
    ]

    energy = energy.sort_values(
        by=[
            "timestamp",
            "building_id",
        ]
    )

    energy = energy.reset_index(drop=True)

    output_path = PROCESSED_DIRECTORY / "energy_readings.csv"

    energy.to_csv(
        output_path,
        index=False,
    )

    print("\nEnergy readings:")
    print(energy.head(10).to_string(index=False))

    print("\nRows:", len(energy))

    print("Missing energy values:", energy["energy"].isna().sum())

    print("Start:", energy["timestamp"].min())

    print("End:", energy["timestamp"].max())

    print(f"\nSaved: {output_path}")

    return energy


# =========================================================
# MAIN
# =========================================================


def main():

    print("=" * 60)
    print("SMART ENERGY AI - PREPARE BDG2 DATA")
    print("=" * 60)

    prepare_buildings()

    prepare_energy_readings()

    print("\n" + "=" * 60)
    print("BDG2 DATA PREPARATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
