"""
Explore Building Data Genome 2.

This script inspects the raw metadata and electricity
datasets before any preprocessing or campus mapping.
"""

from pathlib import Path

import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIRECTORY = Path(__file__).resolve().parent

BDG2_DIRECTORY = BASE_DIRECTORY / "data" / "raw" / "building_data_genome"

METADATA_PATH = BDG2_DIRECTORY / "metadata.txt"

ELECTRICITY_PATH = BDG2_DIRECTORY / "electricity_cleaned.txt"


# =========================================================
# LOAD METADATA
# =========================================================


def load_metadata():
    """
    Load the original BDG2 building metadata.
    """

    metadata_dataframe = pd.read_csv(METADATA_PATH)

    return metadata_dataframe


# =========================================================
# EXPLORE METADATA
# =========================================================


def explore_metadata(metadata_dataframe):
    """
    Display important information about the metadata.
    """

    print("\n" + "=" * 60)
    print("BDG2 METADATA EXPLORATION")
    print("=" * 60)

    print("\nDataset shape:", metadata_dataframe.shape)

    print("\nColumns:")

    for column_name in metadata_dataframe.columns:
        print(f"- {column_name}")

    print("\nFirst 5 rows:")

    print(metadata_dataframe.head())

    print("\nMissing values:")

    print(metadata_dataframe.isnull().sum())


# =========================================================
# EXPLORE BUILDING TYPES
# =========================================================


def explore_building_types(metadata_dataframe):
    """
    Display the available primary building-use categories.
    """

    print("\n" + "=" * 60)
    print("PRIMARY BUILDING TYPES")
    print("=" * 60)

    building_type_counts = metadata_dataframe["primaryspaceusage"].value_counts(
        dropna=False
    )

    print(building_type_counts)


# =========================================================
# EXPLORE SUB BUILDING TYPES
# =========================================================


def explore_sub_building_types(metadata_dataframe):
    """
    Display the available detailed building-use categories.
    """

    print("\n" + "=" * 60)
    print("SUB PRIMARY BUILDING TYPES")
    print("=" * 60)

    sub_building_type_counts = metadata_dataframe["sub_primaryspaceusage"].value_counts(
        dropna=False
    )

    print(sub_building_type_counts.to_string())


# =========================================================
# FIND COMMON CAMPUS SITES
# =========================================================


def find_common_campus_sites(metadata_dataframe):
    """
    Find sites containing all three building types needed
    for our smart campus.
    """

    target_types = [
        "Office",
        "College Laboratory",
        "College Classroom",
    ]

    valid_buildings = metadata_dataframe[
        metadata_dataframe["electricity"].notna()
    ].copy()

    site_type_table = pd.crosstab(
        valid_buildings["site_id"],
        valid_buildings["sub_primaryspaceusage"],
    )

    print("\n" + "=" * 60)
    print("SITES WITH ALL REQUIRED CAMPUS BUILDING TYPES")
    print("=" * 60)

    available_target_columns = [
        building_type
        for building_type in target_types
        if building_type in site_type_table.columns
    ]

    if len(available_target_columns) != len(target_types):
        print("Not all target building types exist in the dataset.")
        return

    common_sites = site_type_table[
        (site_type_table["Office"] > 0)
        & (site_type_table["College Laboratory"] > 0)
        & (site_type_table["College Classroom"] > 0)
    ]

    if common_sites.empty:
        print("No single site contains all three target types.")
        return

    result = common_sites[target_types].copy()

    result["total_target_buildings"] = (
        result["Office"] + result["College Laboratory"] + result["College Classroom"]
    )

    result = result.sort_values(
        by="total_target_buildings",
        ascending=False,
    )

    print(result.to_string())


# =========================================================
# FIND CAMPUS BUILDING CANDIDATES
# =========================================================


def find_campus_building_candidates(metadata_dataframe):
    """
    Find candidate BDG2 buildings that can represent
    the three buildings in our smart campus.

    Campus mapping:
        B001 -> Office
        B002 -> College Laboratory
        B003 -> College Classroom
    """

    target_building_types = {
        "B001": "Office",
        "B002": "College Laboratory",
        "B003": "College Classroom",
    }

    print("\n" + "=" * 60)
    print("CAMPUS BUILDING CANDIDATES")
    print("=" * 60)

    selected_columns = [
        "building_id",
        "site_id",
        "primaryspaceusage",
        "sub_primaryspaceusage",
        "sqm",
        "electricity",
        "lat",
        "lng",
        "timezone",
        "yearbuilt",
        "numberoffloors",
        "occupants",
        "eui",
    ]

    for campus_building_id, target_type in target_building_types.items():

        print("\n" + "-" * 60)

        print(f"{campus_building_id} target type: " f"{target_type}")

        print("-" * 60)

        candidate_buildings = metadata_dataframe[
            metadata_dataframe["sub_primaryspaceusage"].eq(target_type)
        ].copy()

        # Keep only buildings with electricity data
        candidate_buildings = candidate_buildings[
            candidate_buildings["electricity"].notna()
        ]

        # Keep buildings with valid floor area
        candidate_buildings = candidate_buildings[candidate_buildings["sqm"] > 0]

        print("Valid candidates:", len(candidate_buildings))

        print(candidate_buildings[selected_columns].head(15).to_string(index=False))


# =========================================================
# EXPLORE ELECTRICITY FILE STRUCTURE
# =========================================================


def explore_electricity_structure():
    """
    Inspect the electricity dataset structure without
    loading the entire dataset into memory.
    """

    print("\n" + "=" * 60)
    print("ELECTRICITY DATASET STRUCTURE")
    print("=" * 60)

    electricity_sample = pd.read_csv(
        ELECTRICITY_PATH,
        nrows=5,
    )

    print("\nShape of sample:")
    print(electricity_sample.shape)

    print("\nFirst 20 column names:")

    for column_name in electricity_sample.columns[:20]:
        print(f"- {column_name}")

    print("\nFirst 5 rows:")
    print(electricity_sample.iloc[:, :10].to_string(index=False))

    print("\nTotal number of columns:")

    # Read only the header
    electricity_header = pd.read_csv(
        ELECTRICITY_PATH,
        nrows=0,
    )

    print(len(electricity_header.columns))


# =========================================================
# ANALYZE ELECTRICITY DATA QUALITY
# =========================================================


def analyze_electricity_data_quality(metadata_dataframe):
    """
    Analyze electricity data quality for candidate campus
    buildings from sites that contain Office, Laboratory,
    and Classroom buildings.
    """

    print("\n" + "=" * 60)
    print("ELECTRICITY DATA QUALITY ANALYSIS")
    print("=" * 60)

    target_sites = [
        "Hog",
        "Fox",
        "Bull",
        "Cockatoo",
        "Robin",
        "Peacock",
    ]

    target_types = [
        "Office",
        "College Laboratory",
        "College Classroom",
    ]

    # -----------------------------------------------------
    # Select candidate buildings from metadata
    # -----------------------------------------------------

    candidate_metadata = metadata_dataframe[
        metadata_dataframe["site_id"].isin(target_sites)
        & metadata_dataframe["sub_primaryspaceusage"].isin(target_types)
        & metadata_dataframe["electricity"].notna()
    ].copy()

    candidate_building_ids = candidate_metadata["building_id"].tolist()

    print("\nCandidate buildings from metadata:", len(candidate_building_ids))

    # -----------------------------------------------------
    # Read electricity header
    # -----------------------------------------------------

    electricity_header = pd.read_csv(
        ELECTRICITY_PATH,
        nrows=0,
    )

    electricity_columns = set(electricity_header.columns)

    # Keep only buildings that actually exist
    # in electricity_cleaned.txt
    available_buildings = [
        building_id
        for building_id in candidate_building_ids
        if building_id in electricity_columns
    ]

    print("Candidates found in electricity dataset:", len(available_buildings))

    # -----------------------------------------------------
    # Load only timestamp + candidate buildings
    # -----------------------------------------------------

    columns_to_load = [
        "timestamp",
        *available_buildings,
    ]

    print("\nLoading candidate electricity data...")

    electricity_dataframe = pd.read_csv(
        ELECTRICITY_PATH,
        usecols=columns_to_load,
        parse_dates=["timestamp"],
    )

    print("Electricity data loaded.")

    print("Number of timestamps:", len(electricity_dataframe))

    print("Start:", electricity_dataframe["timestamp"].min())

    print("End:", electricity_dataframe["timestamp"].max())

    # -----------------------------------------------------
    # Calculate quality statistics
    # -----------------------------------------------------

    quality_records = []

    total_readings = len(electricity_dataframe)

    for building_id in available_buildings:

        building_series = electricity_dataframe[building_id]

        valid_readings = building_series.notna().sum()

        missing_readings = building_series.isna().sum()

        missing_percent = missing_readings / total_readings * 100

        building_metadata = candidate_metadata[
            candidate_metadata["building_id"] == building_id
        ].iloc[0]

        quality_record = {
            "building_id": building_id,
            "site_id": building_metadata["site_id"],
            "building_type": building_metadata["sub_primaryspaceusage"],
            "sqm": building_metadata["sqm"],
            "total_readings": total_readings,
            "valid_readings": valid_readings,
            "missing_readings": missing_readings,
            "missing_percent": round(
                missing_percent,
                2,
            ),
            "mean_energy": round(
                building_series.mean(),
                2,
            ),
            "max_energy": round(
                building_series.max(),
                2,
            ),
            "min_energy": round(
                building_series.min(),
                2,
            ),
        }

        quality_records.append(quality_record)

    quality_dataframe = pd.DataFrame(quality_records)

    # -----------------------------------------------------
    # Show best candidates
    # -----------------------------------------------------

    print("\n" + "=" * 60)
    print("BEST CANDIDATES BY SITE AND TYPE")
    print("=" * 60)

    for site_id in target_sites:

        print("\n" + "#" * 60)
        print(f"SITE: {site_id}")
        print("#" * 60)

        for building_type in target_types:

            print(f"\n{building_type}")

            best_candidates = (
                quality_dataframe[
                    (quality_dataframe["site_id"] == site_id)
                    & (quality_dataframe["building_type"] == building_type)
                ]
                .sort_values(
                    by=[
                        "missing_percent",
                        "valid_readings",
                    ],
                    ascending=[
                        True,
                        False,
                    ],
                )
                .head(5)
            )

            if best_candidates.empty:
                print("No candidates.")
            else:
                print(best_candidates.to_string(index=False))

    return quality_dataframe


# =========================================================
# MAIN
# =========================================================


def main():

    print("=" * 60)
    print("BUILDING DATA GENOME 2 - EXPLORATION")
    print("=" * 60)

    print("\nBDG2 directory:")
    print(BDG2_DIRECTORY)

    print("\nMetadata file:")
    print(METADATA_PATH)

    print("\nMetadata exists:", METADATA_PATH.exists())

    print("Electricity file exists:", ELECTRICITY_PATH.exists())

    metadata_dataframe = load_metadata()

    explore_metadata(metadata_dataframe)
    explore_building_types(metadata_dataframe)

    explore_sub_building_types(metadata_dataframe)
    find_campus_building_candidates(metadata_dataframe)
    find_common_campus_sites(metadata_dataframe)
    explore_electricity_structure()
    quality_dataframe = analyze_electricity_data_quality(metadata_dataframe)


if __name__ == "__main__":
    main()
