"""
Smart Energy AI - Agent Tools

This module provides the tool layer used by the Agent.

Architecture:

    Agent
      |
      v
    tools.py
      |
      +----------------------+
      |                      |
      v                      v
 Database Tools          ML Tools
      |                      |
      v                      v
 database.py           ml_service.py

Important:
- The Agent must NOT read CSV files directly.
- The Agent must NOT implement ML logic directly.
- ML tools call ml_service.py.
- Approval and execution are handled by the Backend.
- Verification must only be requested after execution.
"""

from typing import Dict, Any, Optional
import datetime
import os

# =========================================================
# CONFIGURATION
# =========================================================

# Mock data is disabled by default.
#
# For temporary local Day-1 testing only:
#
# Windows CMD:
#     set SMART_ENERGY_ALLOW_MOCK=true
#
# PowerShell:
#     $env:SMART_ENERGY_ALLOW_MOCK="true"
#
# Final demo should use:
#     false
#
ALLOW_MOCK_DATA = os.getenv("SMART_ENERGY_ALLOW_MOCK", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


# =========================================================
# DATABASE IMPORT
# =========================================================

try:
    import database as data

    DATABASE_AVAILABLE = True

except ImportError:
    data = None
    DATABASE_AVAILABLE = False


# =========================================================
# ML SERVICE IMPORT
# =========================================================

try:
    from ml_service import (
        get_prediction_events,
        get_peak_events,
        get_energy_anomalies,
        get_events_at_timestamp,
        get_simulation_for_event,
        get_recommended_action,
        get_verification_result,
        get_verification_for_action,
        get_replanning_events,
        get_event_context,
        get_ml_summary,
    )

    ML_SERVICE_AVAILABLE = True
    ML_SERVICE_ERROR = None

except ImportError as exc:
    ML_SERVICE_AVAILABLE = False
    ML_SERVICE_ERROR = str(exc)


# =========================================================
# SHARED CONSTANTS
# =========================================================

VALID_BUILDINGS = {
    "B001",
    "B002",
    "B003",
}


# =========================================================
# GENERIC RESPONSE HELPERS
# =========================================================


def _success(data: Any) -> Dict[str, Any]:
    """
    Create a standard successful tool response.
    """

    return {
        "success": True,
        "data": data,
        "error": None,
    }


def _error(message: str) -> Dict[str, Any]:
    """
    Create a standard failed tool response.
    """

    return {
        "success": False,
        "data": None,
        "error": message,
    }


# =========================================================
# VALIDATION HELPERS
# =========================================================


def _validate_building_id(
    building_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Validate a building ID.

    Returns:
        None if valid.
        Error response if invalid.
    """

    if not isinstance(building_id, str):
        return _error("Invalid building_id: must be a string.")

    building_id = building_id.strip().upper()

    if not building_id:
        return _error("Invalid building_id: must not be empty.")

    if building_id not in VALID_BUILDINGS:
        return _error(
            "Unknown building_id "
            f"'{building_id}'. "
            f"Valid buildings are: "
            f"{sorted(VALID_BUILDINGS)}"
        )

    return None


def _normalize_building_id(
    building_id: str,
) -> str:
    """
    Normalize a building ID.

    Validation should be performed before calling this.
    """

    return building_id.strip().upper()


def _validate_limit(
    limit: Optional[int],
) -> Optional[Dict[str, Any]]:
    """
    Validate an optional result limit.
    """

    if limit is None:
        return None

    if isinstance(limit, bool):
        return _error("Invalid limit: must be a positive integer.")

    if not isinstance(limit, int):
        return _error("Invalid limit: must be an integer.")

    if limit <= 0:
        return _error("Invalid limit: must be greater than zero.")

    return None


def _validate_timestamp(
    timestamp: str,
) -> Optional[Dict[str, Any]]:
    """
    Validate that timestamp is a non-empty string.

    The ML service performs the actual normalization.
    """

    if not isinstance(timestamp, str):
        return _error("Invalid timestamp: must be a string.")

    if not timestamp.strip():
        return _error("Invalid timestamp: must not be empty.")

    return None


# =========================================================
# DATABASE AVAILABILITY
# =========================================================


def _database_unavailable_error() -> Dict[str, Any]:
    """
    Standard error when database is unavailable
    and mock data is disabled.
    """

    return _error(
        "Database service is not available. "
        "Connect database.py or enable mock data "
        "only for local testing."
    )


# =========================================================
# TOOL 1: CURRENT CONSUMPTION
# =========================================================


def get_current_consumption(
    building_id: str,
    at_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get the latest energy consumption reading
    for a building.

    Args:
        building_id:
            B001, B002, or B003.

        at_time:
            Optional timestamp. When given, returns the reading
            at or before that time instead of the latest one.

    Returns:
        Standard tool response.
    """

    validation_error = _validate_building_id(building_id)

    if validation_error:
        return validation_error

    b_id = _normalize_building_id(building_id)

    if at_time is not None:
        ts_error = _validate_timestamp(at_time)
        if ts_error:
            return ts_error
        if DATABASE_AVAILABLE and hasattr(data, "get_energy_reading_at"):
            try:
                reading = data.get_energy_reading_at(b_id, at_time)
                if reading:
                    return _success(reading)
                return _error(
                    f"No energy reading found for building '{b_id}' at or before {at_time}."
                )
            except Exception as exc:
                return _error(
                    f"Database error while retrieving consumption at {at_time}: {exc}"
                )

    # ---------------------------------------------
    # Database
    # ---------------------------------------------

    if DATABASE_AVAILABLE and hasattr(data, "get_latest_energy_reading"):
        try:
            reading = data.get_latest_energy_reading(b_id)

            if reading:
                return _success(reading)

            return _error(f"No energy reading found " f"for building '{b_id}'.")

        except Exception as exc:
            return _error(
                f"Database error while retrieving " f"current consumption: {exc}"
            )

    # ---------------------------------------------
    # Mock data - local testing only
    # ---------------------------------------------

    if not ALLOW_MOCK_DATA:
        return _database_unavailable_error()

    mock_data = {
        "building_id": b_id,
        "timestamp": (datetime.datetime.now(datetime.timezone.utc).isoformat()),
        "total_kw": (300.0 if b_id == "B001" else 450.0 if b_id == "B002" else 150.0),
        "hvac_kw": 120.0,
        "lighting_kw": 50.0,
        "equipment_kw": 130.0,
        "ev_charging_kw": 0.0,
        "data_source": "mock",
    }

    return _success(mock_data)


# =========================================================
# TOOL 2: HISTORICAL CONSUMPTION
# =========================================================


def get_historical_consumption(
    building_id: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get historical energy consumption readings.

    Args:
        building_id:
            B001, B002, or B003.

        start_time:
            Optional ISO-8601 timestamp.

        end_time:
            Optional ISO-8601 timestamp.

    Returns:
        Standard tool response.
    """

    validation_error = _validate_building_id(building_id)

    if validation_error:
        return validation_error

    b_id = _normalize_building_id(building_id)

    if DATABASE_AVAILABLE and hasattr(data, "get_energy_readings"):
        try:
            readings = data.get_energy_readings(
                b_id,
                start_time,
                end_time,
            )

            return _success(readings or [])

        except Exception as exc:
            return _error(
                f"Database error while retrieving " f"historical consumption: {exc}"
            )

    # Mock only for local testing
    if not ALLOW_MOCK_DATA:
        return _database_unavailable_error()

    now = datetime.datetime.now(datetime.timezone.utc)

    mock_readings = [
        {
            "building_id": b_id,
            "timestamp": (now - datetime.timedelta(minutes=15 * i)).isoformat(),
            "total_kw": 300.0 + (i * 10),
            "hvac_kw": 100.0 + (i * 5),
            "lighting_kw": 40.0,
            "equipment_kw": 160.0,
            "data_source": "mock",
        }
        for i in range(5)
    ]

    return _success(mock_readings)


# =========================================================
# TOOL 3: HVAC LOAD
# =========================================================


def get_hvac_load(
    building_id: str,
    at_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get current HVAC load and HVAC percentage.

    at_time: optional timestamp; see get_current_consumption.
    """

    validation_error = _validate_building_id(building_id)

    if validation_error:
        return validation_error

    b_id = _normalize_building_id(building_id)

    consumption_result = get_current_consumption(b_id, at_time=at_time)

    if not consumption_result["success"] or not consumption_result["data"]:
        return _error(
            consumption_result.get(
                "error",
                "Failed to retrieve consumption " "data for HVAC analysis.",
            )
        )

    data = consumption_result["data"]

    hvac_kw = data.get("hvac_kw", 0.0)
    # The DB uses energy_kw (total building consumption).
    # Fall back to legacy "total_kw" key for mock-data compatibility.
    total_kw = data.get("energy_kw") or data.get("total_kw", 0.0)

    if total_kw is None:
        total_kw = 0.0

    try:
        hvac_kw = float(hvac_kw)
        total_kw = float(total_kw)
    except (TypeError, ValueError):
        return _error(
            "Invalid numeric HVAC or total consumption "
            "values returned by the data source."
        )

    if total_kw > 0:
        hvac_pct = round(
            (hvac_kw / total_kw) * 100,
            2,
        )
    else:
        hvac_pct = 0.0

    return _success(
        {
            "building_id": b_id,
            "timestamp": data.get("timestamp"),
            "hvac_kw": hvac_kw,
            "total_kw": total_kw,
            "hvac_pct": hvac_pct,
        }
    )


# =========================================================
# TOOL 4: OCCUPANCY
# =========================================================


def get_occupancy(
    building_id: str,
    at_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get current occupancy percentage
    and estimated people.

    at_time: optional timestamp; see get_current_consumption.
    """

    validation_error = _validate_building_id(building_id)

    if validation_error:
        return validation_error

    b_id = _normalize_building_id(building_id)

    if at_time is not None:
        ts_error = _validate_timestamp(at_time)
        if ts_error:
            return ts_error
        if DATABASE_AVAILABLE and hasattr(data, "get_occupancy_at"):
            try:
                occupancy = data.get_occupancy_at(b_id, at_time)
                if occupancy:
                    return _success(occupancy)
                return _error(
                    f"No occupancy data found for '{b_id}' at or before {at_time}."
                )
            except Exception as exc:
                return _error(
                    f"Database error while retrieving occupancy at {at_time}: {exc}"
                )

    if DATABASE_AVAILABLE and hasattr(data, "get_latest_occupancy"):
        try:
            occupancy = data.get_latest_occupancy(b_id)

            if occupancy:
                return _success(occupancy)

            return _error(f"No occupancy data found " f"for '{b_id}'.")

        except Exception as exc:
            return _error(f"Database error while retrieving " f"occupancy: {exc}")

    if not ALLOW_MOCK_DATA:
        return _database_unavailable_error()

    mock_occupancy = {
        "building_id": b_id,
        "timestamp": (datetime.datetime.now(datetime.timezone.utc).isoformat()),
        "occupancy_pct": (15.0 if b_id == "B002" else 75.0),
        "estimated_people": (30 if b_id == "B002" else 150),
        "data_source": "mock",
    }

    return _success(mock_occupancy)


# =========================================================
# TOOL 5: SOLAR GENERATION
# =========================================================


def get_solar_generation(
    building_id: Optional[str] = None,
    at_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get current solar generation.

    If building_id is None, request campus-wide solar data.

    Args:
        building_id:
            Optional B001, B002, or B003.
    """

    if building_id:
        validation_error = _validate_building_id(building_id)

        if validation_error:
            return validation_error

        b_id = _normalize_building_id(building_id)
    else:
        b_id = "CAMPUS"

    if at_time is not None and b_id != "CAMPUS":
        ts_error = _validate_timestamp(at_time)
        if ts_error:
            return ts_error
        if DATABASE_AVAILABLE and hasattr(data, "get_solar_reading_at"):
            try:
                solar = data.get_solar_reading_at(b_id, at_time)
                if solar:
                    return _success(solar)
                return _error(
                    f"No solar data found for '{b_id}' at or before {at_time}."
                )
            except Exception as exc:
                return _error(
                    f"Database error while retrieving solar generation at {at_time}: {exc}"
                )

    if DATABASE_AVAILABLE and hasattr(data, "get_latest_solar_reading"):
        try:
            # Keep None for campus-wide request.
            database_building_id = None if b_id == "CAMPUS" else b_id

            solar = data.get_latest_solar_reading(database_building_id)

            if solar:
                # For campus-wide requests, tag result as CAMPUS
                # regardless of which building row was returned.
                if b_id == "CAMPUS":
                    solar = dict(solar)
                    solar["building_id"] = "CAMPUS"
                return _success(solar)

            return _error(f"No solar data found " f"for '{b_id}'.")

        except Exception as exc:
            return _error(
                f"Database error while retrieving " f"solar generation: {exc}"
            )

    if not ALLOW_MOCK_DATA:
        return _database_unavailable_error()

    mock_solar = {
        "building_id": b_id,
        "timestamp": (datetime.datetime.now(datetime.timezone.utc).isoformat()),
        "generation_kw": 120.0,
        "expected_kw": 150.0,
        "capacity_kwp": 200.0,
        "irradiance_wm2": 650.0,
        "data_source": "mock",
    }

    return _success(mock_solar)


# =========================================================
# TOOL 6: GRID STATUS
# =========================================================


def get_grid_status() -> Dict[str, Any]:
    """
    Get current grid stress, status,
    and tariff signals.
    """

    if DATABASE_AVAILABLE and hasattr(data, "get_latest_grid_status"):
        try:
            status = data.get_latest_grid_status()

            if status:
                return _success(status)

            return _error("No grid status found.")

        except Exception as exc:
            return _error(f"Database error while retrieving " f"grid status: {exc}")

    if not ALLOW_MOCK_DATA:
        return _database_unavailable_error()

    mock_grid = {
        "timestamp": (datetime.datetime.now(datetime.timezone.utc).isoformat()),
        "event_type": "NORMAL",
        "severity": "LOW",
        "grid_load_pct": 65.0,
        "price_signal": 0.12,
        "currency": "JOD",
        "description": ("Grid operating under normal conditions."),
        "data_source": "mock",
    }

    return _success(mock_grid)


# =========================================================
# ML SERVICE AVAILABILITY
# =========================================================


def _ml_unavailable_error() -> Dict[str, Any]:
    """
    Standard ML service unavailable response.
    """

    if ML_SERVICE_ERROR:
        return _error(
            "ML service is not available. " f"Import error: {ML_SERVICE_ERROR}"
        )

    return _error("ML service is not available.")


# =========================================================
# TOOL 7: ML PREDICTION EVENTS
# =========================================================


def get_ml_prediction_events(
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get prediction events generated by ML.

    This is a read-only tool.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    limit_error = _validate_limit(limit)

    if limit_error:
        return limit_error

    try:
        data = get_prediction_events(
            event_type=event_type,
            severity=severity,
            limit=limit,
        )

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve ML prediction events: " f"{exc}")


# =========================================================
# TOOL 8: ML PEAK EVENTS
# =========================================================


def get_ml_peak_events(
    severity: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get peak-demand risk events.

    Read-only.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    limit_error = _validate_limit(limit)

    if limit_error:
        return limit_error

    try:
        data = get_peak_events(
            severity=severity,
            limit=limit,
        )

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve peak-demand events: " f"{exc}")


# =========================================================
# TOOL 9: ML ENERGY ANOMALIES
# =========================================================


def get_ml_energy_anomalies(
    severity: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get energy anomaly events detected by ML.

    Read-only.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    limit_error = _validate_limit(limit)

    if limit_error:
        return limit_error

    try:
        data = get_energy_anomalies(
            severity=severity,
            limit=limit,
        )

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve energy anomalies: " f"{exc}")


# =========================================================
# TOOL 10: ML EVENT CONTEXT
# =========================================================


def get_ml_event_context(
    timestamp: str,
) -> Dict[str, Any]:
    """
    Get complete PRE-APPROVAL context for an event.

    Returns:
        events
        candidate_actions
        recommendation

    Verification is intentionally excluded.

    Read-only.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    validation_error = _validate_timestamp(timestamp)

    if validation_error:
        return validation_error

    try:
        data = get_event_context(timestamp)

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve event context: " f"{exc}")


# =========================================================
# TOOL 11: EVENTS AT TIMESTAMP
# =========================================================


def get_ml_events_at_timestamp(
    timestamp: str,
) -> Dict[str, Any]:
    """
    Get ML events associated with a timestamp.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    validation_error = _validate_timestamp(timestamp)

    if validation_error:
        return validation_error

    try:
        data = get_events_at_timestamp(timestamp)

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve events at timestamp: " f"{exc}")


# =========================================================
# TOOL 12: ML SIMULATION
# =========================================================


def get_ml_simulation(
    timestamp: str,
) -> Dict[str, Any]:
    """
    Get Digital Twin simulation results
    for a specific event.

    Read-only.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    validation_error = _validate_timestamp(timestamp)

    if validation_error:
        return validation_error

    try:
        data = get_simulation_for_event(timestamp)

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve simulation results: " f"{exc}")


# =========================================================
# TOOL 13: ML RECOMMENDATION
# =========================================================


def get_ml_recommendation(
    timestamp: str,
) -> Dict[str, Any]:
    """
    Get optimized action recommendation.

    IMPORTANT:
    This function recommends an action only.

    It does NOT:
        - approve
        - execute
        - control equipment
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    validation_error = _validate_timestamp(timestamp)

    if validation_error:
        return validation_error

    try:
        data = get_recommended_action(timestamp)

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve recommended action: " f"{exc}")


# =========================================================
# TOOL 14: ML VERIFICATION
# =========================================================


def get_ml_verification(
    timestamp: str,
) -> Dict[str, Any]:
    """
    Get verification result for an event.

    IMPORTANT:
    This tool is intended to be called AFTER:
        1. Recommendation
        2. Human approval
        3. Simulated execution

    It does not execute anything.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    validation_error = _validate_timestamp(timestamp)

    if validation_error:
        return validation_error

    try:
        data = get_verification_result(timestamp)

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve verification result: " f"{exc}")


# =========================================================
# TOOL 14b: ML VERIFICATION FOR A SPECIFIC ACTION
# =========================================================


def get_ml_verification_for_action(
    timestamp: str,
    action: str,
) -> Dict[str, Any]:
    """
    Get the verification result of one specific action at an event.

    Used after replanning, so an approved alternative is verified
    against its own record instead of the original recommendation's.
    Read-only; call only after approval and simulated execution.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    validation_error = _validate_timestamp(timestamp)

    if validation_error:
        return validation_error

    if not isinstance(action, str) or not action.strip():
        return _error("Invalid action: must be a non-empty string.")

    try:
        data = get_verification_for_action(timestamp, action.strip())

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve action verification result: " f"{exc}")


# =========================================================
# TOOL 15: ML REPLANNING EVENTS
# =========================================================


def get_ml_replanning_events(
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get events that require replanning
    after an underperformed action.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    limit_error = _validate_limit(limit)

    if limit_error:
        return limit_error

    try:
        data = get_replanning_events(limit=limit)

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve replanning events: " f"{exc}")


# =========================================================
# TOOL 16: ML SYSTEM SUMMARY
# =========================================================


def get_ml_system_summary() -> Dict[str, Any]:
    """
    Get high-level ML pipeline statistics.
    """

    if not ML_SERVICE_AVAILABLE:
        return _ml_unavailable_error()

    try:
        data = get_ml_summary()

        return _success(data)

    except Exception as exc:
        return _error("Failed to retrieve ML system summary: " f"{exc}")


# =========================================================
# TOOL: LIME ML EXPLANATION
# =========================================================


def explain_ml_prediction(
    timestamp: str,
    building_id: str,
    num_features: int = 8,
) -> Dict[str, Any]:
    """
    Explain an ML forecast using LIME.

    LIME is imported lazily so tools.py remains importable when
    the optional lime package is not installed.
    """

    validation_error = _validate_timestamp(timestamp)

    if validation_error:
        return validation_error

    building = str(building_id or "").strip().upper()

    if building != "CAMPUS":
        validation_error = _validate_building_id(building)

        if validation_error:
            return validation_error

    if building not in {"B001", "B002", "B003", "CAMPUS"}:
        return _error("Unknown building. Use B001, B002, B003 or CAMPUS.")

    try:
        import ml_explainer

        data = ml_explainer.explain_prediction(
            timestamp=timestamp,
            building_id=building,
            num_features=num_features,
        )

        return _success(data)

    except LookupError as exc:
        return _error(str(exc))

    except ImportError:
        return _error("LIME is not installed. Run: pip install lime")

    except Exception as exc:
        return _error(f"Failed to explain prediction: {exc}")


# =========================================================
# TOOL REGISTRY
# =========================================================

TOOLS = {
    # ---------------------------------------------
    # Database / Operational Tools
    # ---------------------------------------------
    "get_current_consumption": get_current_consumption,
    "get_historical_consumption": get_historical_consumption,
    "get_hvac_load": get_hvac_load,
    "get_occupancy": get_occupancy,
    "get_solar_generation": get_solar_generation,
    "get_grid_status": get_grid_status,
    # ---------------------------------------------
    # ML Tools
    # ---------------------------------------------
    "get_ml_prediction_events": get_ml_prediction_events,
    "get_ml_peak_events": get_ml_peak_events,
    "get_ml_energy_anomalies": get_ml_energy_anomalies,
    "get_ml_event_context": get_ml_event_context,
    "get_ml_events_at_timestamp": get_ml_events_at_timestamp,
    "get_ml_simulation": get_ml_simulation,
    "get_ml_recommendation": get_ml_recommendation,
    "get_ml_verification": get_ml_verification,
    "get_ml_verification_for_action": get_ml_verification_for_action,
    "get_ml_replanning_events": get_ml_replanning_events,
    "get_ml_system_summary": get_ml_system_summary,
    "explain_ml_prediction": explain_ml_prediction,
}


def get_event_context_tool(timestamp: str) -> Dict[str, Any]:
    """Helper tool wrapper to get pre-approval context for an event."""
    return get_ml_event_context(timestamp)


def validate_candidate_action(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check one simulated candidate against the optimizer's constraints.

    Returns data = {"valid": bool, "checks": [...]}.
    The logic lives in optimizer.py; this tool only exposes it to the Agent.
    """
    try:
        import optimizer
    except Exception as exc:  # noqa: BLE001
        return _error(f"Optimizer is not available: {exc}")
    try:
        checks = optimizer.constraint_checks(candidate)
        return _success({"valid": all(c["passed"] for c in checks), "checks": checks})
    except Exception as exc:  # noqa: BLE001
        return _error(f"Failed to validate candidate action: {exc}")


def get_verification_result_tool(timestamp: str) -> Dict[str, Any]:
    """Helper tool wrapper to get verification result for an event."""
    return get_ml_verification(timestamp)


def get_verification_for_action_tool(timestamp: str, action: str) -> Dict[str, Any]:
    """Helper tool wrapper to get the verification result of one action."""
    return get_ml_verification_for_action(timestamp, action)


# =========================================================
# TOOL METADATA
# =========================================================

TOOL_METADATA = {
    "get_current_consumption": {
        "category": "data",
        "description": ("Get the latest energy consumption " "for a building."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_historical_consumption": {
        "category": "data",
        "description": ("Get historical energy consumption " "for a building."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_hvac_load": {
        "category": "analysis",
        "description": ("Get current HVAC load and percentage."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_occupancy": {
        "category": "data",
        "description": ("Get current building occupancy."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_solar_generation": {
        "category": "data",
        "description": ("Get current solar generation."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_grid_status": {
        "category": "data",
        "description": ("Get current grid status and signals."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_prediction_events": {
        "category": "ml",
        "description": ("Get ML-generated energy prediction events."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_peak_events": {
        "category": "ml",
        "description": ("Get ML-generated peak-demand risk events."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_energy_anomalies": {
        "category": "ml",
        "description": ("Get ML-detected energy anomalies."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_event_context": {
        "category": "ml",
        "description": ("Get pre-approval context for an event."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_events_at_timestamp": {
        "category": "ml",
        "description": ("Get ML events for a timestamp."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_simulation": {
        "category": "simulation",
        "description": ("Get Digital Twin candidate action simulations."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_recommendation": {
        "category": "optimization",
        "description": ("Get the ML-optimized recommended action."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_verification": {
        "category": "verification",
        "description": ("Get the result of an action after execution."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_verification_for_action": {
        "category": "verification",
        "description": ("Get the verification result of one specific action."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_replanning_events": {
        "category": "replanning",
        "description": ("Get events that require replanning."),
        "requires_approval": False,
        "read_only": True,
    },
    "get_ml_system_summary": {
        "category": "ml",
        "description": ("Get ML pipeline summary statistics."),
        "requires_approval": False,
        "read_only": True,
    },
    "explain_ml_prediction": {
        "category": "ml",
        "description": "Explain an ML energy forecast using LIME.",
        "requires_approval": False,
        "read_only": True,
    },
}


# =========================================================
# HELPER: GET TOOL
# =========================================================


def get_tool(
    tool_name: str,
):
    """
    Retrieve a tool function by name.

    Returns:
        Callable tool or None.
    """

    return TOOLS.get(tool_name)


# =========================================================
# HELPER: LIST TOOLS
# =========================================================


def list_tools():
    """
    Return available tool names.
    """

    return list(TOOLS.keys())


# =========================================================
# MODULE TEST
# =========================================================

if __name__ == "__main__":

    print("=" * 60)
    print("SMART ENERGY AI - TOOL REGISTRY")
    print("=" * 60)

    print(f"Database available: " f"{DATABASE_AVAILABLE}")

    print(f"ML service available: " f"{ML_SERVICE_AVAILABLE}")

    print(f"Mock data enabled: " f"{ALLOW_MOCK_DATA}")

    print("\nAvailable tools:")

    for index, tool_name in enumerate(
        TOOLS,
        start=1,
    ):
        print(f"{index:02d}. {tool_name}")

    print("=" * 60)
