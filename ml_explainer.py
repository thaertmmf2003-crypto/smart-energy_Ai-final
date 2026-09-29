"""
Smart Energy AI - LIME ML Explainer

Explains why the Random Forest forecasting model produced
a particular prediction.

Important:
    This explains the MODEL prediction.
    It does not establish the physical cause of the energy behavior.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = BASE_DIR / "models" / "energy_forecast_model.pkl"
DATA_PATH = BASE_DIR / "data" / "processed" / "ml_energy_dataset.csv"


# =========================================================
# LAZY SINGLETON STATE
# =========================================================

_LOAD_LOCK = threading.Lock()
_LIME_LOCK = threading.Lock()

_MODEL_PACKAGE: Optional[Dict[str, Any]] = None
_DATA: Optional[pd.DataFrame] = None
_EXPLAINER = None

_CACHE: Dict[Tuple[str, str, int], Dict[str, Any]] = {}


# =========================================================
# HUMAN-READABLE FEATURE NAMES
# The model's feature names are engineering shorthand. These map each one to
# plain words for the explanation panel, so a non-technical reader (or a judge)
# sees "Last hour's usage" instead of "energy_lag_1". Purely presentational —
# the model and its math are untouched.
# =========================================================

FRIENDLY_NAMES: Dict[str, str] = {
    "temperature_c": "Temperature",
    "relative_humidity_percent": "Humidity",
    "cloud_cover_percent": "Cloud cover",
    "shortwave_radiation_w_m2": "Sunlight intensity",
    "wind_speed_kmh": "Wind speed",
    "precipitation_mm": "Rainfall",
    "occupancy_percent": "Occupancy",
    "hour": "Hour of day",
    "day_of_week": "Day of week",
    "month": "Month",
    "day_of_year": "Day of year",
    "is_weekend": "Weekend",
    "hour_sin": "Time of day (cyclic)",
    "hour_cos": "Time of day (cyclic)",
    "day_sin": "Season (yearly cycle)",
    "day_cos": "Season (yearly cycle)",
    "energy_lag_1": "Last hour's usage",
    "energy_lag_24": "Usage same hour yesterday",
    "energy_lag_168": "Usage same hour last week",
    "energy_rolling_24_mean": "24-hour average usage",
    "energy_rolling_168_mean": "7-day average usage",
}

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _readable_condition(condition: str, matched_feature: Optional[str]) -> str:
    """
    Turn a LIME rule string into plain words.

    Numeric rules keep their thresholds, only the feature token is swapped:
      "78.70 < energy_lag_1 <= 215.00" -> "78.70 < Last hour's usage <= 215.00"
    Categorical rules are decoded to the value's meaning:
      "day_of_week=0" -> "Day of week: Monday"   "month=12" -> "Month: December"
    Falls back to the original string when nothing matches, so it never hides
    information it could not translate.
    """
    if matched_feature is None:
        return condition

    friendly = FRIENDLY_NAMES.get(matched_feature, matched_feature)

    # Categorical equality rule: "feature=<int>"
    marker = f"{matched_feature}="
    if marker in condition:
        raw = condition.split("=", 1)[1].strip()
        try:
            idx = int(float(raw))
        except (TypeError, ValueError):
            idx = None
        if matched_feature == "day_of_week" and idx is not None and 0 <= idx < 7:
            return f"Day of week: {_DAY_NAMES[idx]}"
        if matched_feature == "month" and idx is not None and 1 <= idx <= 12:
            return f"Month: {_MONTH_NAMES[idx - 1]}"
        if matched_feature == "is_weekend" and idx is not None:
            return "Weekend day" if idx == 1 else "Weekday"
        return f"{friendly} = {raw}"

    # Numeric threshold rule: replace only the feature token, keep the numbers.
    return condition.replace(matched_feature, friendly)


# =========================================================
# HELPERS
# =========================================================


def _load_resources():
    """
    Load model package and dataset once.

    Thread-safe and lazy.
    """

    global _MODEL_PACKAGE
    global _DATA
    global _EXPLAINER

    if _MODEL_PACKAGE is not None and _DATA is not None:
        return

    with _LOAD_LOCK:
        if _MODEL_PACKAGE is None:
            if not MODEL_PATH.exists():
                raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")

            # Import only when resources are actually needed.
            from ml_models import load_model

            _MODEL_PACKAGE = load_model()

        if _DATA is None:
            if not DATA_PATH.exists():
                raise FileNotFoundError(f"ML dataset file not found: {DATA_PATH}")

            _DATA = pd.read_csv(DATA_PATH)


def _get_features() -> list[str]:
    """
    Get feature order from the saved model package.

    Fall back to ml_models.FEATURES only if the package does not
    contain the feature list.
    """

    _load_resources()

    assert _MODEL_PACKAGE is not None

    features = _MODEL_PACKAGE.get("features")

    if features:
        return list(features)

    from ml_models import FEATURES

    return list(FEATURES)


def _get_model():
    _load_resources()

    assert _MODEL_PACKAGE is not None

    model = _MODEL_PACKAGE.get("model")

    if model is None:
        raise ValueError("Saved model package does not contain a model.")

    return model


def _numeric(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not np.isfinite(number):
        return None

    return number


def _scalar(value: Any) -> Optional[float]:
    """
    Flatten a LIME per-label result (dict, array, list or scalar) to one float.

    In regression mode LIME keys its outputs by a dummy label, so attributes such
    as `intercept` come back as {0: 0.42} rather than 0.42.
    """

    if value is None:
        return None

    if isinstance(value, dict):
        if not value:
            return None
        value = next(iter(value.values()))

    if isinstance(value, (list, tuple, np.ndarray)):
        flat = np.asarray(value).reshape(-1)
        if flat.size == 0:
            return None
        value = flat[0]

    return _numeric(value)


def _import_lime():
    """
    Import LIME lazily.

    This function is intentionally called only when an explanation
    is requested.
    """

    try:
        from lime.lime_tabular import LimeTabularExplainer
    except ImportError as exc:
        raise ImportError("LIME is not installed. Run: pip install lime") from exc

    return LimeTabularExplainer


# =========================================================
# AVAILABILITY
# =========================================================


def is_available() -> tuple[bool, Optional[str]]:
    """
    Check whether LIME and the required model/data files are available.
    """

    try:
        _import_lime()
    except ImportError:
        return False, "LIME is not installed. Run: pip install lime"

    if not MODEL_PATH.exists():
        return False, f"Model file not found: {MODEL_PATH.name}"

    if not DATA_PATH.exists():
        return False, f"Dataset file not found: {DATA_PATH.name}"

    return True, None


# =========================================================
# LIME EXPLAINER
# =========================================================


def _get_explainer(features: list[str]):
    global _EXPLAINER

    if _EXPLAINER is not None:
        return _EXPLAINER

    with _LIME_LOCK:
        if _EXPLAINER is not None:
            return _EXPLAINER

        LimeTabularExplainer = _import_lime()

        assert _DATA is not None

        train_data, _, _ = __import__("ml_models").chronological_split(_DATA)

        missing = [f for f in features if f not in train_data.columns]

        if missing:
            raise ValueError(
                "ML dataset is missing model features: " + ", ".join(missing)
            )

        X_train = train_data[features].copy()

        categorical_features = [
            features.index(name)
            for name in (
                "is_weekend",
                "day_of_week",
                "month",
            )
            if name in features
        ]

        _EXPLAINER = LimeTabularExplainer(
            training_data=X_train.values,
            feature_names=features,
            mode="regression",
            discretize_continuous=True,
            random_state=42,
            categorical_features=categorical_features,
        )

        return _EXPLAINER


# =========================================================
# ROW LOOKUP
# =========================================================


def _find_row(
    timestamp: str,
    building_id: str,
) -> pd.Series:

    _load_resources()

    assert _DATA is not None

    rows = _DATA[
        (_DATA["timestamp"].astype(str) == str(timestamp))
        & (_DATA["building_id"].astype(str) == str(building_id))
    ]

    if rows.empty:
        raise LookupError(f"No model input row for {building_id} at {timestamp}")

    return rows.iloc[0]


# =========================================================
# SINGLE BUILDING EXPLANATION
# =========================================================


def _explain_building(
    timestamp: str,
    building_id: str,
    num_features: int,
    num_samples: int,
) -> Dict[str, Any]:

    _load_resources()

    features = _get_features()
    model = _get_model()
    explainer = _get_explainer(features)

    row = _find_row(timestamp, building_id)

    row_values = row[features].astype(float).values

    prediction = model.predict(row[features].to_frame().T)[0]

    predicted_kw = float(prediction)

    actual_value = _numeric(row.get("energy"))

    if actual_value is not None and predicted_kw != 0:
        residual_percent = (actual_value - predicted_kw) / predicted_kw * 100.0
    else:
        residual_percent = None

    exp = explainer.explain_instance(
        row_values,
        model.predict,
        num_features=num_features,
        num_samples=num_samples,
    )

    contributions = []

    # num_features belongs to explain_instance() above, which already limited the
    # surrogate to that many features. Forwarding it to as_list() sends it into
    # TableDomainMapper.map_exp_ids(self, exp), which takes no keyword arguments,
    # and raises: unexpected keyword argument 'num_features'.
    for condition, weight in exp.as_list():
        weight_kw = float(weight)

        feature_name = str(condition)

        direction = "up" if weight_kw >= 0 else "down"

        # LIME condition is a rule string. We try to map it to the
        # underlying feature name so the UI can still expose a value.
        matched_feature = None

        # Longest name first: "energy_lag_1" is a substring of "energy_lag_168",
        # and "hour" of "hour_cos", so a plain first-match loop attributes the
        # contribution to the wrong feature.
        for feature in sorted(features, key=len, reverse=True):
            if feature in condition:
                matched_feature = feature
                break

        if matched_feature is None:
            # For discretized conditions, the feature name normally
            # appears in the LIME rule. If not, keep the condition
            # and use null for its exact source value.
            value = None
        else:
            value = _numeric(row[matched_feature])

        contributions.append(
            {
                "feature": (
                    matched_feature if matched_feature is not None else feature_name
                ),
                "friendly_name": FRIENDLY_NAMES.get(matched_feature, matched_feature)
                if matched_feature
                else feature_name,
                "condition": feature_name,
                "readable": _readable_condition(feature_name, matched_feature),
                "weight_kw": weight_kw,
                "direction": direction,
                "value": value,
            }
        )

    contributions.sort(
        key=lambda item: abs(item["weight_kw"]),
        reverse=True,
    )

    top_features = {}

    for item in contributions:
        feature = item["feature"]

        if feature in row.index:
            value = _numeric(row[feature])

            if value is not None:
                top_features[feature] = value

    # LIME returns these per-label. In regression mode the label is a dummy key,
    # so intercept is {0: value} and local_pred is a one-element array. score is
    # a plain float here but a dict in classification mode. _scalar flattens all
    # three shapes so this keeps working if the mode ever changes.
    lime_intercept = _scalar(exp.intercept)

    lime_local_prediction = _scalar(exp.local_pred)

    lime_score = _scalar(exp.score)

    return {
        "building_id": building_id,
        "timestamp": timestamp,
        "predicted_kw": predicted_kw,
        "actual_kw": actual_value,
        "residual_percent": residual_percent,
        "lime_intercept": lime_intercept,
        "lime_local_prediction": lime_local_prediction,
        "lime_score": lime_score,
        "contributions": contributions,
        "feature_values": top_features,
        "method": ("LIME (local surrogate of the Random Forest forecast)"),
        "note": (
            "Explains why the MODEL predicted this value, " "not the physical cause."
        ),
    }


# =========================================================
# PUBLIC API
# =========================================================


def explain_prediction(
    timestamp: str,
    building_id: str,
    num_features: int = 8,
    num_samples: int = 3000,
) -> dict:

    num_features = max(
        3,
        min(int(num_features), 15),
    )

    num_samples = max(
        500,
        min(int(num_samples), 5000),
    )

    building_id = str(building_id).upper().strip()

    cache_key = (
        str(timestamp),
        building_id,
        num_features,
    )

    if cache_key in _CACHE:
        return _CACHE[cache_key]

    if building_id == "CAMPUS":
        buildings = ["B001", "B002", "B003"]

        results = [
            _explain_building(
                timestamp,
                building,
                num_features,
                num_samples,
            )
            for building in buildings
        ]

        predicted_values = [item["predicted_kw"] for item in results]

        actual_values = [item["actual_kw"] for item in results]

        predicted_total = float(sum(predicted_values))

        if all(value is not None for value in actual_values):
            actual_total = float(sum(actual_values))
        else:
            actual_total = None

        result = {
            "building_id": "CAMPUS",
            "timestamp": timestamp,
            "predicted_kw": predicted_total,
            "actual_kw": actual_total,
            "buildings": results,
        }

    else:
        if building_id not in {
            "B001",
            "B002",
            "B003",
        }:
            raise ValueError("Unknown building. Use B001, B002, B003 or CAMPUS.")

        result = _explain_building(
            timestamp,
            building_id,
            num_features,
            num_samples,
        )

    _CACHE[cache_key] = result

    return result


def get_cached_explanation(
    timestamp: str,
    building_id: str,
    num_features: int = 8,
) -> Optional[dict]:
    """
    Return an already generated explanation without computing a new one.
    """

    key = (
        str(timestamp),
        str(building_id).upper().strip(),
        max(3, min(int(num_features), 15)),
    )

    return _CACHE.get(key)


def clear_cache() -> None:
    """
    Clear explanation cache.

    Used by tests or when a fresh application-level explanation cache
    is required.
    """

    _CACHE.clear()
    _SUMMARY_CACHE.clear()


# =========================================================
# PLAIN-LANGUAGE SUMMARY (OPTIONAL LLM LAYER)
# =========================================================
#
# The LIME output above is precise but hard to read: conditions such as
# "78.70 < energy_lag_1 <= 215.00" mean nothing to an operator. This layer turns
# one explanation into a short paragraph.
#
# It is strictly optional. Without an API key the API and the dashboard keep
# working exactly as before and simply show no paragraph. The numbers are never
# produced by the language model: it only rewords contributions that LIME
# already computed.
#
# Configuration (shared with rag_service.py, with an explainer-specific
# override so the two can use different models if you want):
#     ANTHROPIC_API_KEY / OPENAI_API_KEY   enable a provider
#     EXPLAIN_LLM_PROVIDER                 anthropic | openai | none
#     EXPLAIN_LLM_MODEL                    model name override


LLM_TIMEOUT_SECONDS = 30

LLM_DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
}

SUMMARY_SYSTEM_PROMPT = """You explain a machine learning forecast to a building operator.

A model forecast an electricity load. LIME identified which inputs moved that
forecast. Write ONE short paragraph explaining why the model forecast what it did.

Rules:
- Use simple everyday English.
- Plain text only: no Markdown, no **, no #, no bullets, no lists, no tables.
- Do not quote the raw feature conditions or the numeric contributions.
- Do not mention LIME, the surrogate, or that you were given reasons.
- Use only the factors provided. Never invent a factor.
- Say what the model responded to, not what physically caused the event.
- Maximum 4 sentences.
"""

# Human wording for the model's input columns. Anything not listed falls back to
# the raw column name with underscores removed, so a new feature degrades to
# something readable rather than breaking.
FEATURE_PHRASES = {
    "energy_lag_1": "the load in the previous hour",
    "energy_lag_24": "the load at the same hour yesterday",
    "energy_lag_168": "the load at the same hour last week",
    "energy_rolling_24_mean": "the average load over the last day",
    "energy_rolling_168_mean": "the average load over the last week",
    "occupancy_percent": "how busy the building was",
    "hvac_power_kw": "HVAC power draw",
    "ev_charging_power_kw": "EV charging",
    "solar_generation_kw": "solar generation",
    "temperature_c": "outdoor temperature",
    "relative_humidity_percent": "humidity",
    "shortwave_radiation_w_m2": "how much sunlight there was",
    "cloud_cover_percent": "cloud cover",
    "wind_speed_kmh": "wind speed",
    "precipitation_mm": "rainfall",
    "hour": "the hour of day",
    "hour_sin": "the hour of day",
    "hour_cos": "the hour of day",
    "day_of_week": "the day of the week",
    "day_sin": "the time of year",
    "day_cos": "the time of year",
    "day_of_year": "the time of year",
    "is_weekend": "whether it was a weekend",
    "battery_state_of_charge_percent": "battery charge level",
    "battery_power_kw": "battery power",
}

_SUMMARY_CACHE: Dict[Tuple[str, str, int], str] = {}


def _llm_provider() -> str:
    """Pick a provider from the environment, or "none" if none is configured."""

    import os

    configured = os.getenv("EXPLAIN_LLM_PROVIDER", "auto").strip().lower()

    if configured in {"none", "off", "disabled"}:
        return "none"

    if configured == "anthropic":
        return "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "none"

    if configured == "openai":
        return "openai" if os.getenv("OPENAI_API_KEY") else "none"

    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"

    if os.getenv("OPENAI_API_KEY"):
        return "openai"

    return "none"


def _llm_model(provider: str) -> Optional[str]:
    import os

    if provider == "none":
        return None

    return os.getenv("EXPLAIN_LLM_MODEL") or LLM_DEFAULT_MODELS[provider]


def _call_llm(provider: str, model: str, system: str, user: str) -> str:
    """
    Send one prompt and return the text.

    Mirrors rag_service._call_llm rather than adding an SDK dependency, so the
    project keeps a single HTTP client.
    """

    import os

    import requests

    if provider == "anthropic":
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 400,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=LLM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        blocks = response.json().get("content", [])
        return "".join(
            block.get("text", "") for block in blocks if block.get("type") == "text"
        ).strip()

    if provider == "openai":
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        response = requests.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 400,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=LLM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    raise ValueError(f"Unknown LLM provider: {provider}")


def _readable_feature(contribution: Dict[str, Any]) -> str:
    """Turn one LIME contribution into a phrase a person can read."""

    feature = contribution.get("feature")

    if feature and feature in FEATURE_PHRASES:
        return FEATURE_PHRASES[feature]

    if feature:
        return str(feature).replace("_", " ")

    # No feature was matched to the rule, so fall back to the condition text.
    return str(contribution.get("condition") or "an input the model uses")


def _summary_prompt(result: Dict[str, Any]) -> str:
    """
    Build the user prompt from one single-building explanation.

    Contributions are ranked by absolute weight and handed over as directions
    only. The model is given the ordering, not the numbers, so it cannot quote a
    contribution value back at the reader.
    """

    # Several columns share one phrase: hour, hour_sin and hour_cos are all "the
    # hour of day". Listing them separately produces contradictory lines such as
    # "the hour of day pushed higher" next to "the hour of day pulled lower".
    # Merge by phrase and keep the net direction.
    merged: Dict[str, float] = {}

    for contribution in result.get("contributions") or []:
        phrase = _readable_feature(contribution)
        weight = _numeric(contribution.get("weight_kw")) or 0.0
        merged[phrase] = merged.get(phrase, 0.0) + weight

    ranked = sorted(merged.items(), key=lambda item: abs(item[1]), reverse=True)

    lines = []

    for phrase, weight in ranked[:5]:
        direction = (
            "pushed the forecast higher" if weight >= 0 else "pulled the forecast lower"
        )
        lines.append(f"- {phrase} {direction}")

    predicted = _numeric(result.get("predicted_kw"))
    actual = _numeric(result.get("actual_kw"))

    prompt = [
        f"Building: {result.get('building_id')}",
        f"Hour: {result.get('timestamp')}",
        f"Forecast load: {predicted:.1f} kW" if predicted is not None else "",
        f"Measured load: {actual:.1f} kW" if actual is not None else "",
        "",
        "Factors, strongest first:",
        *lines,
    ]

    # A weak local fit means the factor list is unreliable. Tell the model, so
    # the paragraph is hedged instead of sounding certain about a poor fit.
    score = _numeric(result.get("lime_score"))
    if score is not None and score < 0.3:
        prompt += [
            "",
            "Note: these factors are only a rough approximation of the model's "
            "behaviour here. Word the explanation tentatively.",
        ]

    return "\n".join(line for line in prompt if line != "" or True).strip()


def summarize_explanation(
    result: Dict[str, Any],
    use_cache: bool = True,
) -> Optional[str]:
    """
    Write a plain-language paragraph for one explanation.

    Accepts either a single-building result or a CAMPUS result, in which case
    the building with the largest forecast is summarised.

    Returns None when no provider is configured, when the explanation has no
    contributions, or when the call fails. Callers treat the paragraph as a
    bonus and must not depend on it: the LIME table is the real output.
    """

    if not result:
        return None

    # A campus result nests one entry per building.
    parts = result.get("buildings") or [result]
    parts = [part for part in parts if part.get("contributions")]

    if not parts:
        return None

    target = max(parts, key=lambda part: _numeric(part.get("predicted_kw")) or 0.0)

    cache_key = (
        str(target.get("timestamp")),
        str(target.get("building_id")),
        len(target.get("contributions") or []),
    )

    if use_cache and cache_key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[cache_key]

    provider = _llm_provider()

    if provider == "none":
        return None

    model = _llm_model(provider)

    try:
        text = _call_llm(
            provider,
            model,
            SUMMARY_SYSTEM_PROMPT,
            _summary_prompt(target),
        )
    except Exception:  # noqa: BLE001
        # A summary is decoration. Never let it break the explanation itself.
        return None

    if not text:
        return None

    # Strip any Markdown that slipped through despite the instructions.
    text = text.replace("**", "").replace("##", "").replace("#", "").strip()

    if use_cache:
        _SUMMARY_CACHE[cache_key] = text

    return text


def summary_available() -> Tuple[bool, Optional[str]]:
    """Whether a plain-language summary can be produced, and why not if it cannot."""

    provider = _llm_provider()

    if provider == "none":
        return False, (
            "No language model is configured. Set ANTHROPIC_API_KEY or "
            "OPENAI_API_KEY to enable plain-language summaries."
        )

    return True, None
