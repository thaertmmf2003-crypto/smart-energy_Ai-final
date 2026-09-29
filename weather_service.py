"""
Weather Service
Smart Energy, Solar & Grid-Aware Operations AI

Downloads historical hourly weather data from Open-Meteo
for the selected BDG2 Robin campus.
"""

from pathlib import Path
import requests
import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIRECTORY = Path(__file__).resolve().parent

PROCESSED_DIRECTORY = BASE_DIRECTORY / "data" / "processed"

WEATHER_OUTPUT_PATH = PROCESSED_DIRECTORY / "weather_data.csv"


# =========================================================
# CAMPUS LOCATION
# Robin site - BDG2
# =========================================================

LATITUDE = 51.51879
LONGITUDE = -0.134556

START_DATE = "2016-01-01"
END_DATE = "2017-12-31"


# =========================================================
# DOWNLOAD HISTORICAL WEATHER
# =========================================================


def get_historical_weather():

    print("=" * 60)
    print("DOWNLOADING HISTORICAL WEATHER")
    print("=" * 60)

    url = "https://archive-api.open-meteo.com/v1/archive"

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "hourly": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "cloud_cover",
                "shortwave_radiation",
                "wind_speed_10m",
                "precipitation",
            ]
        ),
        "timezone": "Europe/London",
    }

    response = requests.get(
        url,
        params=params,
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    hourly = data["hourly"]

    weather = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(hourly["time"]),
            "temperature_c": hourly["temperature_2m"],
            "relative_humidity_percent": hourly["relative_humidity_2m"],
            "cloud_cover_percent": hourly["cloud_cover"],
            "shortwave_radiation_w_m2": hourly["shortwave_radiation"],
            "wind_speed_kmh": hourly["wind_speed_10m"],
            "precipitation_mm": hourly["precipitation"],
        }
    )

    return weather


# =========================================================
# SAVE DATA
# =========================================================


def save_weather_data(weather):

    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    weather.to_csv(
        WEATHER_OUTPUT_PATH,
        index=False,
    )

    print("\nFirst rows:")
    print(weather.head().to_string(index=False))

    print("\nRows:", len(weather))

    print("Start:", weather["timestamp"].min())

    print("End:", weather["timestamp"].max())

    print("\nMissing values:")
    print(weather.isnull().sum())

    print(f"\nSaved: {WEATHER_OUTPUT_PATH}")


# =========================================================
# MAIN
# =========================================================


def main():

    weather = get_historical_weather()

    save_weather_data(weather)

    print("\n" + "=" * 60)
    print("WEATHER DATA PREPARATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
