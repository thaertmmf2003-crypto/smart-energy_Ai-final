"""
Smart Energy AI - data_qa.py

Answers factual questions about the project's own data, in English or Arabic:

    "What was the energy consumption on 2016-07-01?"
    "How much did the Labs consume in July 2017?"
    "Which day had the highest consumption in 2016?"
    "What was the solar generation of B001 on 15/3/2017 at 2 pm?"
    "Were there any anomalies on 1 July 2016?"
    "كم كان استهلاك الطاقة يوم 5/7/2016؟"
    "أي يوم كان فيه أعلى استهلاك في 2017؟"

Why it exists
-------------
rag_service.py retrieves from the documents in knowledge/energy/. Those
documents explain *how* the system works; they contain no readings, so a
question about a specific day could never be answered from them. This module
reads energy.db and data/processed/*.csv, computes the figures with pandas, and
returns them as verified facts. rag_service then gives those facts to the
language model (or shows them directly when no model is configured).

All numbers are computed here, never by the language model.

Units
-----
Readings are hourly. Each energy value is the energy used in that hour, so
summing a day gives kWh for the day and the hourly value doubles as the average
demand in kW for that hour.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "energy.db"
PROCESSED = BASE_DIR / "data" / "processed"

BUILDINGS = {
    "B001": {"en": "Administration", "ar": "مبنى الإدارة"},
    "B002": {"en": "Labs", "ar": "مبنى المختبرات"},
    "B003": {"en": "Classrooms", "ar": "مبنى القاعات الدراسية"},
}

# kind:
#   energy  hourly energy; summed over time and across buildings
#   level   per-building level (%, SOC); averaged
#   site    one value per timestamp for the whole site (weather, grid)
METRICS: Dict[str, Dict[str, Any]] = {
    "energy": {"src": "readings", "col": "energy", "kind": "energy", "unit": "kWh",
               "en": "energy consumption", "ar": "استهلاك الطاقة"},
    "hvac": {"src": "readings", "col": "hvac", "kind": "energy", "unit": "kWh",
             "en": "HVAC consumption", "ar": "استهلاك التكييف (HVAC)"},
    "solar": {"src": "readings", "col": "solar", "kind": "energy", "unit": "kWh",
              "en": "solar generation", "ar": "توليد الطاقة الشمسية"},
    "ev": {"src": "readings", "col": "ev", "kind": "energy", "unit": "kWh",
           "en": "EV charging", "ar": "شحن السيارات الكهربائية"},
    "occupancy": {"src": "readings", "col": "occupancy", "kind": "level", "unit": "%",
                  "en": "occupancy", "ar": "نسبة الإشغال"},
    "battery": {"src": "battery", "col": "soc", "kind": "level", "unit": "%",
                "en": "battery state of charge", "ar": "شحن البطارية"},
    "temperature": {"src": "weather", "col": "temperature_c", "kind": "site", "unit": "°C",
                    "en": "outdoor temperature", "ar": "درجة الحرارة الخارجية"},
    "humidity": {"src": "weather", "col": "relative_humidity_percent", "kind": "site", "unit": "%",
                 "en": "relative humidity", "ar": "الرطوبة النسبية"},
    "radiation": {"src": "weather", "col": "shortwave_radiation_w_m2", "kind": "site", "unit": "W/m²",
                  "en": "solar radiation", "ar": "الإشعاع الشمسي"},
    "grid": {"src": "grid", "col": "grid_stress_level", "kind": "site", "unit": "",
             "en": "grid stress level", "ar": "مستوى إجهاد الشبكة"},
}

# =========================================================
# TEXT NORMALISATION
# =========================================================

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DIACRITICS = re.compile(r"[ؗ-ًؚ-ْـ]")
_ARABIC = re.compile(r"[؀-ۿ]")


def normalize(text: str) -> str:
    t = (text or "").translate(_DIGITS)
    t = _DIACRITICS.sub("", t)
    t = re.sub("[إأآٱ]", "ا", t)
    t = t.replace("ة", "ه").replace("ى", "ي").replace("،", ",").replace("؟", "?")
    return t.lower()


def is_arabic(text: str) -> bool:
    return bool(_ARABIC.search(text or ""))


_AR_PREFIX = r"(?:وبال|وال|بال|لل|كال|فال|ال|و|ب|ل|ف)?"


def _pattern(words: List[str]) -> re.Pattern:
    """Word-boundary alternation. Arabic words accept common prefixes/suffixes."""
    parts = []
    for w in words:
        w = normalize(w)
        if _ARABIC.search(w):
            parts.append(rf"(?<!\w){_AR_PREFIX}{re.escape(w)}\w{{0,3}}(?!\w)")
        else:
            parts.append(rf"\b{w}\b")
    return re.compile("|".join(parts))


# =========================================================
# VOCABULARY
# =========================================================

METRIC_WORDS = {
    "energy": ["consumption", "consume[sd]?", "consuming", "load", "demand", "usage", "used", "use",
               "kwh", "استهلاك", "مستهلك", "استهلك", "حمل"],
    "hvac": ["hvac", "cooling", "heating", "air[- ]?condition\\w*", "a/?c", "تكييف", "تبريد", "تدفئه", "مكيف"],
    "solar": ["solar", "pv", "photovoltaic\\w*", "panels?", "شمسي", "شمسيه", "الواح", "توليد"],
    "ev": ["ev", "evs", "charging", "electric vehicles?", "chargers?", "شحن السيارات", "سيارات", "شواحن"],
    "occupancy": ["occupancy", "occupied", "occupants", "people", "اشغال", "اشغال", "اشخاص", "حضور"],
    "battery": ["battery", "batteries", "soc", "state of charge", "بطاريه", "البطاريه", "بطاريات"],
    "temperature": ["temperature", "temp", "weather", "hot", "cold", "degrees?", "حراره", "طقس", "جو"],
    "humidity": ["humidity", "humid", "رطوبه"],
    "radiation": ["radiation", "irradiance", "sunshine", "اشعاع"],
    "grid": ["grid", "stress", "import limit", "شبكه"],
}
# Generic words that suggest energy only when nothing more specific is present.
WEAK_ENERGY = _pattern(["energy", "electricity", "power", "طاقه", "كهرباء", "كهربا"])

BUILDING_WORDS = {
    "B001": ["b001", "b-001", "b1", "administration", "admin", "office", "اداره", "اداري", "اداريه", "مكاتب"],
    "B002": ["b002", "b-002", "b2", "labs?", "laborator(?:y|ies)", "مختبر", "مختبرات", "معامل"],
    "B003": ["b003", "b-003", "b3", "classrooms?", "classes", "lecture", "teaching",
             "قاعات", "صفوف", "تدريس", "دراسيه", "محاضرات"],
}
CAMPUS_WORDS = _pattern(["campus", "all buildings", "whole site", "total site", "كل المباني", "جميع المباني",
                         "الحرم", "الموقع", "المباني"])

MONTHS_LONG = {
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
    "كانون الثاني": 1, "كانون ثاني": 1, "يناير": 1, "شباط": 2, "فبراير": 2, "اذار": 3, "مارس": 3,
    "نيسان": 4, "ابريل": 4, "افريل": 4, "ايار": 5, "مايو": 5, "حزيران": 6, "يونيو": 6, "يونيه": 6,
    "تموز": 7, "يوليو": 7, "يوليه": 7, "اغسطس": 8, "ايلول": 9, "سبتمبر": 9,
    "تشرين الاول": 10, "تشرين اول": 10, "اكتوبر": 10, "تشرين الثاني": 11, "تشرين ثاني": 11,
    "نوفمبر": 11, "كانون الاول": 12, "كانون اول": 12, "ديسمبر": 12,
}
# Ambiguous month names: accepted only next to a number ("may" the verb, "اب" the word).
MONTHS_NEEDS_NUMBER = {"may": 5, "اب": 8}
ALL_MONTHS = {**MONTHS_LONG, **MONTHS_NEEDS_NUMBER}
_MONTH_ALT = "|".join(sorted((re.escape(m) for m in ALL_MONTHS), key=len, reverse=True))
_MONTH_ALONE_ALT = "|".join(sorted((re.escape(m) for m in MONTHS_LONG), key=len, reverse=True))
_MP = rf"(?:[وبلف])?({_MONTH_ALT})"          # month with optional Arabic prefix
_ORD = r"(?:st|nd|rd|th)?"

QUANT_CUES = _pattern([
    "how much", "how many", "what was", "what were", "what's the", "what is the (?:total|average|peak|maximum|minimum)",
    "show me", "tell me", "give me", "total", "sum", "average", "mean", "highest", "lowest", "maximum", "minimum",
    "max", "min", "most", "least", "peak", "record", "which", "compare", "comparison", "value", "reading", "readings",
    "كم", "قديش", "اديش", "قد ايش", "اعلى", "اقل", "ادنى", "اكثر", "متوسط", "معدل", "مجموع", "اجمالي",
    "قيمه", "قراءه", "قراءات", "ذروه", "قارن", "مقارنه", "اي", "ايش", "شو", "ما هو", "ما هي", "ماذا",
])
MAX_WORDS = _pattern(["highest", "maximum", "max", "most", "peak", "busiest", "largest", "biggest", "top",
                      "اعلى", "اكثر", "اكبر", "ذروه", "اقصى"])
MIN_WORDS = _pattern(["lowest", "minimum", "min", "least", "smallest", "quietest", "bottom",
                      "اقل", "ادنى", "اصغر"])
RELATIVE_DAY = _pattern(["today", "yesterday", "tonight", "this week", "last week", "this month", "now",
                         "currently", "امبارح", "مبارح", "امس", "هاليوم", "هلا", "الان", "حاليا", "هذا الاسبوع"])

EVENT_WORDS = _pattern(["anomaly", "anomalies", "anomalous", "events?", "incidents?", "alerts?", "alarms?",
                        "peak demand risk", "abnormal", "unusual", "problems?", "issues?",
                        "شذوذ", "شاذ", "شاذه", "احداث", "حدث", "حوادث", "تنبيه", "تنبيهات", "انذار", "مشكله",
                        "مشاكل", "غير طبيعي"])
ACTION_WORDS = _pattern(["actions?", "recommendations?", "recommended", "verification", "verified", "verify",
                         "success rate", "succeeded", "underperform\\w*", "replan\\w*", "executed",
                         "اجراء", "اجراءات", "توصيه", "توصيات", "تحقق", "نجاح", "نجح", "تنفيذ"])
FORECAST_WORDS = _pattern(["forecast\\w*", "predict\\w*", "accuracy", "accurate", "mae", "mape", "error",
                           "model performance", "تنبؤ", "توقع", "توقعات", "دقه", "خطا", "النموذج", "الموديل"])
OVERVIEW_WORDS = _pattern(["dataset", "data set", "date range", "time range", "period covered", "what period",
                           "which period", "what dates", "how many buildings", "which buildings",
                           "what buildings", "data cover", "data available", "summary of the data",
                           "overview", "how many records", "how many readings", "how many rows",
                           "البيانات", "الداتا", "الفتره", "كم مبنى", "ما هي المباني", "شو المباني", "نظره عامه",
                           "ملخص", "كم سجل", "كم قراءه"])


_SOLAR_ENERGY = re.compile(r"solar (?:energy|power)|(?:ال)?طاقه (?:ال)?شمسيه")


def _metrics_in(t: str) -> List[str]:
    found = [m for m, words in METRIC_WORDS.items() if _pattern(words).search(t)]
    # "HVAC consumption" means HVAC, not total energy. Keep total energy next to
    # another metric only when the question names energy/electricity explicitly
    # ("energy consumption and solar generation").
    if "energy" in found and len(found) > 1:
        generic = WEAK_ENERGY.search(_SOLAR_ENERGY.sub(" ", t))
        if not generic:
            found.remove("energy")
    return found


def _buildings_in(t: str) -> List[str]:
    return [b for b, words in BUILDING_WORDS.items() if _pattern(words).search(t)]


# =========================================================
# DATE / TIME PARSING
# =========================================================


@dataclass
class Period:
    start: pd.Timestamp
    end: pd.Timestamp          # exclusive
    kind: str                  # hour | day | month | year | range | all
    label: str

    def contains_data(self, lo: pd.Timestamp, hi: pd.Timestamp) -> bool:
        return self.start <= hi and self.end > lo


def _safe_ts(y: int, m: int, d: int = 1, h: int = 0) -> Optional[pd.Timestamp]:
    try:
        return pd.Timestamp(year=y, month=m, day=d, hour=h)
    except (ValueError, OverflowError):
        return None


def _day_period(ts: pd.Timestamp) -> Period:
    return Period(ts, ts + pd.Timedelta(days=1), "day", ts.strftime("%Y-%m-%d"))


def _month_period(y: int, m: int) -> Period:
    s = pd.Timestamp(year=y, month=m, day=1)
    return Period(s, s + pd.offsets.MonthBegin(1), "month", s.strftime("%Y-%m"))


def _year_period(y: int) -> Period:
    s = pd.Timestamp(year=y, month=1, day=1)
    return Period(s, pd.Timestamp(year=y + 1, month=1, day=1), "year", str(y))


def _parse_hour(t: str) -> Optional[int]:
    pats = [
        r"(?:\bat|@|الساعه|ساعه|بالساعه)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|صباحا|الصبح|صباح|ص|مساء|المسا|مسا|م|العصر|الظهر|ليلا|بالليل)?",
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)",
        r"(?<![\d/.-])(\d{1,2}):(\d{2})(?![\d/.-])()",
    ]
    for p in pats:
        m = re.search(p, t)
        if not m:
            continue
        h = int(m.group(1))
        suffix = (m.group(3) or "").replace(".", "")
        if suffix in {"pm", "مساء", "المسا", "مسا", "م", "العصر", "ليلا", "بالليل"} and h < 12:
            h += 12
        elif suffix == "الظهر" and h < 6:
            h += 12
        elif suffix in {"am", "صباحا", "الصبح", "صباح", "ص"} and h == 12:
            h = 0
        if 0 <= h <= 23:
            return h
    return None


def parse_periods(t: str, years: List[int]) -> Tuple[List[Period], Optional[int], bool]:
    """
    Returns (periods, hour, is_range). `t` must already be normalised.
    Days given without a year expand to every dataset year.
    """
    found: List[Tuple[int, List[Period], Optional[int]]] = []  # (position, periods, hour)
    taken: List[Tuple[int, int]] = []

    def free(s: int, e: int) -> bool:
        return all(e <= a or s >= b for a, b in taken)

    def add(m: re.Match, periods: List[Period], hour: Optional[int] = None) -> None:
        if periods and free(m.start(), m.end()):
            taken.append((m.start(), m.end()))
            found.append((m.start(), periods, hour))

    # 1. ISO: 2016-07-01 [18:00]
    for m in re.finditer(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ t]+(\d{1,2}):(\d{2}))?\b", t):
        ts = _safe_ts(int(m[1]), int(m[2]), int(m[3]))
        if ts is not None:
            add(m, [_day_period(ts)], int(m[4]) if m[4] else None)

    # 2. Day-first numeric: 1/7/2016 (month-first only when day-first is impossible)
    for m in re.finditer(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", t):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        ts = _safe_ts(y, b, a) if b <= 12 else _safe_ts(y, a, b)
        if ts is not None:
            add(m, [_day_period(ts)])

    # 3. Day + month name [+ year]: "1 July 2016", "1st of july", "5 تموز 2016"
    for m in re.finditer(rf"\b(\d{{1,2}}){_ORD}\s*(?:of\s+|من\s+(?:شهر\s+)?|شهر\s+)?{_MP}(?!\w)[,\s]*(?:سنه\s*|عام\s*)?(\d{{4}})?", t):
        d, mon = int(m[1]), ALL_MONTHS[m[2]]
        ys = [int(m[3])] if m[3] else years
        add(m, [_day_period(p) for p in (_safe_ts(y, mon, d) for y in ys) if p is not None])

    # 4. Month name + day [+ year]: "July 1, 2016"
    for m in re.finditer(rf"(?<!\w){_MP}\s+(\d{{1,2}}){_ORD}(?!\d)(?:,?\s*(\d{{4}}))?", t):
        mon, d = ALL_MONTHS[m[1]], int(m[2])
        if d > 31:
            continue
        ys = [int(m[3])] if m[3] else years
        add(m, [_day_period(p) for p in (_safe_ts(y, mon, d) for y in ys) if p is not None])

    # 5. Month name + year: "July 2016", "تموز 2017", "شهر 7 2016"
    for m in re.finditer(rf"(?<!\w){_MP}(?!\w)[,\s]*(?:سنه\s*|عام\s*|of\s+)?(\d{{4}})", t):
        add(m, [_month_period(int(m[2]), ALL_MONTHS[m[1]])])
    for m in re.finditer(r"شهر\s*(\d{1,2})\s*(?:سنه|عام|/|-)?\s*(\d{4})", t):
        if 1 <= int(m[1]) <= 12:
            add(m, [_month_period(int(m[2]), int(m[1]))])

    # 6. Numeric month: 2016-07 / 07/2016
    for m in re.finditer(r"\b(\d{4})[-/](\d{1,2})\b(?![-/]\d)", t):
        if 1 <= int(m[2]) <= 12:
            add(m, [_month_period(int(m[1]), int(m[2]))])
    for m in re.finditer(r"(?<![\d/.-])(\d{1,2})[-/](\d{4})\b", t):
        if 1 <= int(m[1]) <= 12:
            add(m, [_month_period(int(m[2]), int(m[1]))])

    # 7. Month name alone: "in July" → that month in every year
    for m in re.finditer(rf"(?<!\w)(?:[وبلف])?({_MONTH_ALONE_ALT})(?!\w)", t):
        mon = MONTHS_LONG[m[1]]
        add(m, [_month_period(y, mon) for y in years])
    for m in re.finditer(r"شهر\s*(\d{1,2})(?!\d)", t):
        if 1 <= int(m[1]) <= 12:
            add(m, [_month_period(y, int(m[1])) for y in years])

    # 8. Year alone
    for m in re.finditer(r"(?<![\d/.:-])((?:19|20)\d{2})(?![\d/.:-])", t):
        add(m, [_year_period(int(m[1]))])

    found.sort(key=lambda f: f[0])
    periods = [p for _, ps, _ in found for p in ps]
    hour = next((h for _, _, h in found if h is not None), None)
    if hour is None:
        # strip date spans so "2016-07-01" is not read as an hour
        stripped = t
        for s, e in sorted(taken, reverse=True):
            stripped = stripped[:s] + " " + stripped[e:]
        hour = _parse_hour(stripped)

    is_range = bool(
        len(found) == 2
        and re.search(r"\b(from|between|to|until|till|through|and)\b|من|بين|الى|لغايه|حتى|ل\s*\d|و\s*\d|-", t)
        and not re.search(r"compare|versus|vs\.?|قارن|مقارنه", t)
    )
    if is_range:
        s = found[0][1][0].start
        e = found[1][1][-1].end
        if e > s:
            periods = [Period(s, e, "range", f"{s:%Y-%m-%d} → {(e - pd.Timedelta(hours=1)):%Y-%m-%d}")]
        else:
            is_range = False
    return periods, hour, is_range


# =========================================================
# DATA LOADING
# =========================================================


class ProjectData:
    """Loads the project datasets once and keeps them in memory (~10 MB)."""

    def __init__(self, db_path: Path = DB_PATH, processed: Path = PROCESSED):
        self.db_path = Path(db_path)
        self.processed = Path(processed)
        self._lock = threading.Lock()
        self._loaded = False
        self.error: Optional[str] = None

    def ensure(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._load()
            self._loaded = True

    def reload(self) -> None:
        with self._lock:
            self._loaded = False
            self._load()
            self._loaded = True

    def _csv(self, name: str) -> pd.DataFrame:
        path = self.processed / name
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_csv(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"])
        return df

    def _load(self) -> None:
        self.error = None
        readings = pd.DataFrame()
        if self.db_path.exists():
            try:
                with sqlite3.connect(self.db_path) as con:
                    readings = pd.read_sql_query(
                        "SELECT timestamp, building_id, energy_kw AS energy, hvac_kw AS hvac, "
                        "occupancy_pct AS occupancy, solar_kw AS solar, ev_kw AS ev, "
                        "temperature_c AS temperature FROM energy_readings",
                        con,
                    )
            except Exception as exc:  # noqa: BLE001
                self.error = f"energy.db: {exc}"
        if readings.empty:
            # Fallback: rebuild the same table from the processed CSVs.
            e = self._csv("energy_readings.csv").rename(columns={"energy": "energy"})
            if not e.empty:
                readings = e[["timestamp", "building_id", "energy"]]
                for name, col, new in [("hvac_readings.csv", "hvac_power_kw", "hvac"),
                                       ("occupancy.csv", "occupancy_percent", "occupancy"),
                                       ("solar_readings.csv", "solar_generation_kw", "solar"),
                                       ("ev_charging.csv", "ev_charging_power_kw", "ev")]:
                    other = self._csv(name)
                    if not other.empty:
                        readings = readings.merge(other[["timestamp", "building_id", col]].rename(columns={col: new}),
                                                  on=["timestamp", "building_id"], how="left")
        if not readings.empty:
            readings["timestamp"] = pd.to_datetime(readings["timestamp"])
            readings = readings.sort_values(["timestamp", "building_id"]).reset_index(drop=True)
        self.readings = readings

        bat = self._csv("battery_readings.csv")
        if not bat.empty:
            bat = bat.rename(columns={"battery_state_of_charge_percent": "soc", "battery_power_kw": "battery_kw"})
        self.battery = bat
        self.weather = self._csv("weather_data.csv")
        if self.weather.empty and not readings.empty:
            self.weather = (readings.groupby("timestamp", as_index=False)["temperature"].first()
                            .rename(columns={"temperature": "temperature_c"}))
        self.grid = self._csv("grid_signals.csv")
        self.anomalies = self._csv("anomaly_labels.csv")
        self.events = self._csv("prediction_events.csv")
        self.actions = self._csv("optimized_actions.csv")
        self.verification = self._csv("verification_results.csv")
        self.forecast = self._csv("energy_forecast_results.csv")

        if readings.empty:
            self.error = self.error or "No energy readings found (energy.db and CSVs missing)."
            self.first = self.last = None
            self.years = []
        else:
            self.first = readings["timestamp"].min()
            self.last = readings["timestamp"].max()
            self.years = list(range(self.first.year, self.last.year + 1))

    # ------------------------------------------------------
    def frame(self, metric: str) -> pd.DataFrame:
        src = METRICS[metric]["src"]
        return {"readings": self.readings, "battery": self.battery,
                "weather": self.weather, "grid": self.grid}[src]


project_data = ProjectData()


# =========================================================
# QUERY PLAN
# =========================================================


@dataclass
class Plan:
    question: str
    arabic: bool
    intent: str                      # summary | rank | events | actions | forecast | overview | relative
    metrics: List[str]
    buildings: List[str]             # empty → campus
    periods: List[Period]
    hour: Optional[int] = None
    rank_unit: Optional[str] = None  # day | month | hour | building | year
    rank_dir: str = "max"
    top_n: int = 5
    notes: List[str] = field(default_factory=list)


def plan_question(question: str, data: ProjectData = project_data) -> Optional[Plan]:
    """Decide whether the question asks about project data. None → not a data question."""
    data.ensure()
    t = normalize(question)
    arabic = is_arabic(question)
    years = data.years or [2016, 2017]

    periods, hour, _ = parse_periods(t, years)
    metrics = _metrics_in(t)
    weak_energy = bool(WEAK_ENERGY.search(t))
    buildings = _buildings_in(t)
    quant = bool(QUANT_CUES.search(t))
    is_event = bool(EVENT_WORDS.search(t))
    is_action = bool(ACTION_WORDS.search(t))
    is_forecast = bool(FORECAST_WORDS.search(t))
    is_overview = bool(OVERVIEW_WORDS.search(t))
    relative = bool(RELATIVE_DAY.search(t)) or (not periods and re.search(r"(?<!\w)اليوم(?!\w)", t) is not None
                                                and not re.search(r"(?<!\w)(اي|ايش|شو|اكثر|اعلي|اقل)\s*يوم", t))

    # Rank questions: "which day...", "أي يوم ..."
    rank_unit = None
    m = re.search(r"\b(?:which|what)\s+(day|date|month|hour|time of day|time|building|year|week)", t) or \
        re.search(r"\btop\s+\d*\s*(days?|months?|hours?|buildings?)", t) or \
        re.search(r"\b(?:highest|lowest|busiest|quietest|peak|most|least)\s+(day|month|hour|building|year)", t) or \
        re.search(r"(?<!\w)(?:اي|ايش|شو|ما هو|ما هي|انهي|وين)\s*(?:هو\s*|هي\s*)?(ال)?(يوم|تاريخ|شهر|ساعه|مبني|المبني|سنه)", t) or \
        re.search(r"(?<!\w)(?:اكثر|اعلي|اقل|ادني)\s*(?:\d{1,2}\s*)?(ال)?(يوم|ايام|شهر|اشهر|شهور|ساعه|ساعات|مبني|مباني|سنه)", t)
    if m:
        word = m.group(m.lastindex or 1) or ""
        word = word.rstrip("s")
        rank_unit = {"date": "day", "time": "hour", "time of day": "hour", "week": "day",
                     "يوم": "day", "تاريخ": "day", "شهر": "month", "ساعه": "hour", "مبني": "building",
                     "المبني": "building", "سنه": "year",
                     "ايام": "day", "اشهر": "month", "شهور": "month", "ساعات": "hour", "مباني": "building"}.get(word, word)
        if rank_unit not in {"day", "month", "hour", "building", "year"}:
            rank_unit = None

    has_metric = bool(metrics) or weak_energy
    # "Why does…", "How can…", "لماذا…", "كيف…" ask for an explanation. They go to
    # the documents unless they also name a date, a building or a ranking.
    conceptual = bool(
        re.match(r"\s*(why|how(?! (much|many|accurate|often|high|low|big))|explain|describe|what (is|are) (a|an|the)? ?"
                 r"(role|purpose|difference|meaning|concept|definition)|what does|define)\b", t)
        or re.match(r"\s*(لماذا|ليش|ليه|كيف|اشرح|وضح|ما (هو|هي) (دور|الفرق|معنى|مفهوم))", t)
    )
    conceptual = conceptual or bool(
        re.search(r"(?<!\w)(?:[وبلف])?(اسباب|سبب|ليش|لماذا|ليه|كيف|يعني|معني|تعريف|اشرح|وضح|الفرق|فرق|فكره|مبدا)(?!\w)", t)
        or re.search(r"\b(causes?|reasons?|why|explain|meaning|difference between)\b", t)
    )
    if conceptual and not (periods or rank_unit or buildings or relative):
        return None
    data_cue = bool(has_metric or buildings or is_event or is_action or is_forecast or rank_unit
                    or re.search(r"happen|data|summary|report|reading|حدث|صار|بيانات|ملخص|تقرير|قراء", t))
    day_level = any(p.kind == "day" for p in periods)
    is_data = bool(
        (periods and (day_level or data_cue)) or rank_unit or (relative and data_cue)
        or (quant and (has_metric or buildings))
        or (buildings and has_metric)
        or (is_event and (quant or periods))
        or (is_action and re.search(r"rate|success|succeed|how many|count|percent|underperform|نسبه|نجاح|نجح|عدد|كم|قديش|فشل", t))
        or (is_forecast and (quant or re.search(r"accura|mae|mape|دقه|خطا", t))
            and (weak_energy or "energy" in metrics or re.search(r"model|forecast|نموذج|موديل|تنبؤ", t)))
        or is_overview
    )
    if not is_data:
        return None

    if not metrics:
        metrics = ["energy"]

    if relative and not periods:
        intent = "relative"
    elif is_overview and not periods and not rank_unit and not (quant and has_metric and not is_overview):
        intent = "overview"
    elif is_event and not rank_unit:
        intent = "events"
    elif is_action and not rank_unit:
        intent = "actions"
    elif is_forecast and not rank_unit:
        intent = "forecast"
    elif rank_unit:
        intent = "rank"
    else:
        intent = "summary"

    top = re.search(r"\btop\s+(\d{1,2})\b|(?<!\w)(?:اعلي|اكثر|اقل|ادني)\s+(\d{1,2})(?!\d)", t)
    top_n = int(top.group(1) or top.group(2)) if top else 5
    rank_dir = "min" if MIN_WORDS.search(t) and not (MAX_WORDS.search(t) and
                                                     MAX_WORDS.search(t).start() < MIN_WORDS.search(t).start()) else "max"

    plan = Plan(question, arabic, intent, metrics, buildings, periods, hour,
                rank_unit, rank_dir, max(1, min(top_n, 20)))

    # Clip periods to the dataset and note anything outside it.
    if data.first is not None and plan.periods:
        kept = []
        for p in plan.periods:
            if p.contains_data(data.first, data.last):
                kept.append(p)
            else:
                plan.notes.append(p.label)
        plan.periods = kept
    return plan


# =========================================================
# FORMATTING
# =========================================================


def _n(x: float, digits: int = 1) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{digits}f}"


def _bname(b: str, ar: bool) -> str:
    return f"{b} {BUILDINGS[b]['ar' if ar else 'en']}" if b in BUILDINGS else b


def _scope_label(buildings: List[str], ar: bool) -> str:
    if not buildings or len(buildings) == len(BUILDINGS):
        return "الحرم كامل (3 مباني)" if ar else "the whole campus (3 buildings)"
    return " + ".join(_bname(b, ar) for b in buildings)


def _period_label(p: Period, ar: bool) -> str:
    if p.kind == "day":
        return (f"يوم {p.label} ({_weekday(p.start, ar)})" if ar else f"{p.label} ({_weekday(p.start, ar)})")
    if p.kind == "month":
        return f"شهر {p.label}" if ar else f"{p.start:%B %Y}"
    if p.kind == "year":
        return f"سنة {p.label}" if ar else p.label
    if p.kind == "hour":
        return p.label
    return (f"الفترة {p.label}" if ar else p.label)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _prep(p: "Period") -> str:
    return "on" if p.kind == "day" else ("for" if p.kind in {"range", "all"} else "in")


def _weekday(ts: pd.Timestamp, ar: bool) -> str:
    en = ts.strftime("%A")
    arw = {"Monday": "الاثنين", "Tuesday": "الثلاثاء", "Wednesday": "الأربعاء", "Thursday": "الخميس",
           "Friday": "الجمعة", "Saturday": "السبت", "Sunday": "الأحد"}
    return arw[en] if ar else en


# =========================================================
# HUMAN LANGUAGE
# ---------------------------------------------------------
# The "facts" list keeps every figure at full precision. The answer the reader
# sees first is written as plain sentences: friendly dates ("Tuesday 5 July
# 2016"), clock times ("3 pm"), rounded numbers and a short explanation of what
# the figure means. **x** marks the key figure; the UI renders it in bold.
# =========================================================

AR_MONTHS = ["كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب", "أيلول",
             "تشرين الأول", "تشرين الثاني", "كانون الأول"]

ACTION_NAMES = {
    "COMBINED_ACTION": ("الإجراء المركّب (بطارية + تكييف + شحن السيارات)", "the combined action (battery + HVAC + EV)"),
    "BATTERY_DISCHARGE": ("تفريغ البطارية وقت الذروة", "discharging the battery at the peak"),
    "HVAC_SETPOINT_ADJUSTMENT": ("تعديل ضبط حرارة التكييف", "adjusting the HVAC set-point"),
    "EV_LOAD_SHIFT": ("تأجيل شحن السيارات الكهربائية", "shifting EV charging"),
}
EVENT_NAMES = {
    "PEAK_DEMAND_RISK": ("تنبيه خطر ذروة الطلب (الطلب المتوقع يقترب من حد الاستيراد من الشبكة)",
                         "peak-demand risk alerts (predicted demand approaching the grid import limit)"),
    "ENERGY_ANOMALY": ("استهلاك أعلى من المتوقع بشكل غير طبيعي", "unusually high consumption compared with the expected baseline"),
    "SOLAR_UNDERPERFORMANCE": ("ضعف غير طبيعي في توليد الطاقة الشمسية", "solar generation well below what was expected"),
}
SEVERITY_NAMES = {"CRITICAL": ("حرجة", "critical"), "HIGH": ("عالية", "high"), "ELEVATED": ("مرتفعة", "elevated")}


def _hn(x: float, unit: str = "", ar: bool = False) -> str:
    """Round for reading: 10,117 · 48.3 · 6.8 million."""
    if x is None or pd.isna(x):
        return "—"
    ax = abs(x)
    if ax >= 1_000_000:
        s = f"{x / 1_000_000:,.2f}".rstrip("0").rstrip(".") + (" مليون" if ar else " million")
    elif ax >= 100:
        s = f"{x:,.0f}"
    elif ax >= 10:
        s = f"{x:,.1f}".rstrip("0").rstrip(".")
    else:
        s = f"{x:,.2f}".rstrip("0").rstrip(".")
    return f"{s} {unit}".strip() if unit and unit != "%" else f"{s}{unit}"


def _hpct(x: float) -> str:
    ax = abs(x)
    if ax >= 10:
        return f"{x:.0f}%"
    if ax >= 1:
        t = f"{x:.1f}"
    elif ax >= 0.01:
        t = f"{x:.2f}"
    else:
        return "0%"
    return t.rstrip("0").rstrip(".") + "%"


def _li(word: str) -> str:
    """Arabic preposition لـ: لمبنى، للإجراء."""
    return "لل" + word[2:] if word.startswith("ال") else "ل" + word


def _bval(b: str, v: str, ar: bool, pct: str = "") -> str:
    """'مبنى الإدارة (B001) بـ1,447 kWh (14%)' / 'the Administration building (B001) with 1,447 kWh (14%)'."""
    tail = f" ({pct})" if pct else ""
    return f"{_hbuilding(b, ar)} بـ{v}{tail}" if ar else f"{_hbuilding(b, ar)} with {v}{tail}"


def _hdate(ts: pd.Timestamp, ar: bool, weekday: bool = True, year: bool = True) -> str:
    wd = (_weekday(ts, ar) + " ") if weekday else ""
    if ar:
        return f"{wd}{ts.day} {AR_MONTHS[ts.month - 1]}" + (f" {ts.year}" if year else "")
    return f"{wd}{ts.day} {ts:%B}" + (f" {ts.year}" if year else "")


def _hmonth(ts: pd.Timestamp, ar: bool) -> str:
    return f"{AR_MONTHS[ts.month - 1]} {ts.year}" if ar else f"{ts:%B %Y}"


def _hhour(h: int, ar: bool) -> str:
    h = int(h) % 24
    if ar:
        if h == 0:
            return "منتصف الليل"
        if h == 12:
            return "الساعة 12 ظهراً"
        h12 = h if h <= 12 else h - 12
        part = ("ليلاً" if h <= 3 else "فجراً" if h <= 5 else "صباحاً" if h <= 11 else
                "ظهراً" if h <= 14 else "عصراً" if h <= 17 else "مساءً" if h <= 20 else "ليلاً")
        return f"الساعة {h12} {part}"
    if h == 0:
        return "midnight"
    if h == 12:
        return "noon"
    return f"{h if h < 12 else h - 12} {'am' if h < 12 else 'pm'}"


def _hwhen(ts: pd.Timestamp, ar: bool, same_day: bool) -> str:
    """'at 3 pm' within one day, otherwise 'on Wednesday 6 July at 4 pm' (Arabic without prepositions)."""
    if same_day:
        return _hhour(ts.hour, ar) if ar else f"at {_hhour(ts.hour, ar)}"
    d = _hdate(ts, ar, weekday=True, year=False)
    return f"يوم {d} {_hhour(ts.hour, ar)}" if ar else f"on {d} at {_hhour(ts.hour, ar)}"


def _hscope(buildings: List[str], ar: bool) -> str:
    if not buildings or len(buildings) == len(BUILDINGS):
        return "الحرم كاملاً (المباني الثلاثة)" if ar else "the whole campus (all three buildings)"
    names = [f"{BUILDINGS[b]['ar']} ({b})" if ar else f"the {BUILDINGS[b]['en']} building ({b})"
             for b in buildings if b in BUILDINGS]
    return (" و".join(names)) if ar else " and ".join(names)


def _hbuilding(b: str, ar: bool) -> str:
    if b not in BUILDINGS:
        return b
    return f"{BUILDINGS[b]['ar']} ({b})" if ar else f"the {BUILDINGS[b]['en']} building ({b})"


def _hperiod(p: Optional[Period], ar: bool, data: Optional["ProjectData"] = None) -> str:
    """Phrase that can start a sentence: 'On Tuesday 5 July 2016', 'في تموز 2016'."""
    if p is None or p.kind == "all":
        if data is not None and data.first is not None:
            return (f"خلال كامل فترة البيانات ({data.first.year}–{data.last.year})" if ar else
                    f"Over the whole dataset ({data.first.year}–{data.last.year})")
        return "خلال كامل فترة البيانات" if ar else "Over the whole dataset"
    if p.kind == "day":
        return f"يوم {_hdate(p.start, ar)}" if ar else f"On {_hdate(p.start, ar)}"
    if p.kind == "month":
        return f"في شهر {_hmonth(p.start, ar)}" if ar else f"In {_hmonth(p.start, ar)}"
    if p.kind == "year":
        return f"في سنة {p.start.year}" if ar else f"In {p.start.year}"
    if p.kind == "hour":
        return (f"يوم {_hdate(p.start, ar)} {_hhour(p.start.hour, ar)}" if ar else
                f"On {_hdate(p.start, ar)} at {_hhour(p.start.hour, ar)}")
    last = p.end - pd.Timedelta(hours=1)
    return (f"بين {_hdate(p.start, ar, weekday=False)} و{_hdate(last, ar, weekday=False)}" if ar else
            f"Between {_hdate(p.start, ar, weekday=False)} and {_hdate(last, ar, weekday=False)}")


def _mid(phrase: str) -> str:
    """English period phrase used mid-sentence: 'On …' → 'on …'."""
    return phrase[:1].lower() + phrase[1:]


def _ar_count(n: int, one: str, two: str, few: str, many: str) -> str:
    """Arabic number agreement: 1 حدث، 2 حدثان، 3-10 أحداث، 11+ حدثاً."""
    if n == 1:
        return f"{one} واحد" if not one.endswith("ة") else f"{one} واحدة"
    if n == 2:
        return two
    if 3 <= n % 100 <= 10:
        return f"{n:,} {few}"
    return f"{n:,} {many}"


def _change_word(diff_pct: float, ar: bool) -> str:
    a = abs(diff_pct)
    up = diff_pct >= 0
    if a < 3:
        return "تقريباً بنفس المستوى" if ar else "about the same"
    size_ar = "بقليل" if a < 10 else ("بشكل واضح" if a < 25 else "بشكل كبير")
    size_en = "slightly" if a < 10 else ("noticeably" if a < 25 else "much")
    if ar:
        return f"{'أعلى' if up else 'أقل'} {size_ar} (بنسبة {_hpct(a)})"
    return f"{size_en} {'higher' if up else 'lower'} ({_hpct(a)})"


def _weather_word(mean_c: float, ar: bool) -> str:
    if mean_c < 10:
        return "بارداً" if ar else "cold"
    if mean_c < 22:
        return "معتدلاً" if ar else "mild"
    if mean_c < 28:
        return "دافئاً" if ar else "warm"
    return "حاراً" if ar else "hot"


# Verbs per metric: (Arabic, English) with {scope} and {value}.
METRIC_SENTENCE = {
    "energy": ("استهلك {scope} حوالي **{value}** من الكهرباء", "{scope} used about **{value}** of electricity"),
    "hvac": ("استهلك التكييف (HVAC) في {scope} حوالي **{value}**", "air-conditioning (HVAC) in {scope} used about **{value}**"),
    "solar": ("ولّدت الألواح الشمسية في {scope} حوالي **{value}**", "the solar panels at {scope} generated about **{value}**"),
    "ev": ("استهلك شحن السيارات الكهربائية في {scope} حوالي **{value}**", "EV charging at {scope} used about **{value}**"),
}


# =========================================================
# COMPUTATION
# =========================================================


def _slice(df: pd.DataFrame, p: Optional[Period]) -> pd.DataFrame:
    if df.empty or p is None:
        return df
    return df[(df["timestamp"] >= p.start) & (df["timestamp"] < p.end)]


def _series(data: ProjectData, metric: str, buildings: List[str], p: Optional[Period]) -> pd.DataFrame:
    """Timestamp-indexed frame: one column per building (+ 'campus') or one 'site' column."""
    meta = METRICS[metric]
    df = _slice(data.frame(metric), p)
    if df.empty:
        return pd.DataFrame()
    if meta["kind"] == "site":
        return df.set_index("timestamp")[[meta["col"]]].rename(columns={meta["col"]: "site"})
    if not buildings and metric == "battery":
        buildings = ["B002"]           # the only building with storage (config.py)
    if buildings:
        df = df[df["building_id"].isin(buildings)]
    wide = df.pivot_table(index="timestamp", columns="building_id", values=meta["col"], aggfunc="first")
    if meta["kind"] == "energy":
        wide["campus"] = wide.sum(axis=1, min_count=1)
    else:
        wide["campus"] = wide.mean(axis=1)
    return wide


def _stats_line(s: pd.Series, metric: str, ar: bool, name: str) -> Tuple[str, Dict[str, Any]]:
    meta = METRICS[metric]
    unit = meta["unit"]
    s = s.dropna()
    if s.empty:
        return (f"{name}: لا توجد قراءات" if ar else f"{name}: no readings"), {}
    pk, lo = s.idxmax(), s.idxmin()
    single_day = (s.index.max() - s.index.min()) < pd.Timedelta(days=1)
    fmt = "%H:%M" if single_day else "%Y-%m-%d %H:%M"
    st = {"hours": int(s.size), "mean": float(s.mean()), "max": float(s.max()), "max_at": pk.strftime(fmt),
          "min": float(s.min()), "min_at": lo.strftime(fmt)}
    if meta["kind"] == "energy":
        st["total"] = float(s.sum())
        if ar:
            line = (f"{name}: المجموع {_n(st['total'])} kWh، متوسط الساعة {_n(st['mean'])} kW، "
                    f"الذروة {_n(st['max'])} kW عند {st['max_at']}، الأدنى {_n(st['min'])} kW عند {st['min_at']}")
        else:
            line = (f"{name}: total {_n(st['total'])} kWh, hourly average {_n(st['mean'])} kW, "
                    f"peak {_n(st['max'])} kW at {st['max_at']}, lowest {_n(st['min'])} kW at {st['min_at']}")
    else:
        d = 3 if metric == "grid" else 1
        u = f" {unit}" if unit and unit != "%" else unit
        if ar:
            line = (f"{name}: المتوسط {_n(st['mean'], d)}{u}، الأعلى {_n(st['max'], d)}{u} عند {st['max_at']}، "
                    f"الأدنى {_n(st['min'], d)}{u} عند {st['min_at']}")
        else:
            line = (f"{name}: average {_n(st['mean'], d)}{u}, highest {_n(st['max'], d)}{u} at {st['max_at']}, "
                    f"lowest {_n(st['min'], d)}{u} at {st['min_at']}")
    return line, st


def _summary(plan: Plan, data: ProjectData) -> Dict[str, Any]:
    ar = plan.arabic
    facts: List[str] = []
    headline: List[str] = []
    periods = plan.periods or [Period(data.first, data.last + pd.Timedelta(hours=1), "all",
                                      "كامل البيانات" if ar else "the full dataset")]
    for p in periods:
        plabel = _period_label(p, ar) if p.kind != "all" else p.label
        for metric in plan.metrics:
            meta = METRICS[metric]
            wide = _series(data, metric, plan.buildings, p)
            mname = meta["ar" if ar else "en"]
            if wide.empty:
                facts.append(f"{plabel} — {mname}: " + ("لا توجد بيانات" if ar else "no data"))
                continue

            if plan.hour is not None and p.kind == "day":
                ts = p.start + pd.Timedelta(hours=plan.hour)
                row = wide.loc[wide.index == ts]
                hlabel = f"{ts:%Y-%m-%d %H:00}"
                if row.empty:
                    facts.append(f"{hlabel} — {mname}: " + ("لا توجد قراءة" if ar else "no reading"))
                    continue
                row = row.iloc[0]
                u = meta["unit"] if meta["kind"] != "energy" else "kW"
                if meta["kind"] == "site":
                    facts.append(f"{hlabel} — {mname}: {_n(row['site'], 3 if metric == 'grid' else 1)} {u}".strip())
                    headline.append(f"{mname} {'الساعة' if ar else 'at'} {hlabel}: {_n(row['site'], 1)} {u}")
                    continue
                parts = [f"{_bname(b, ar)} {_n(row[b])} {u}" for b in wide.columns if b != "campus"]
                camp = row["campus"]
                if len(parts) > 1:
                    tag = ("مجموع الحرم" if meta["kind"] == "energy" else "متوسط الحرم") if ar else \
                          ("campus total" if meta["kind"] == "energy" else "campus average")
                    facts.append(f"{hlabel} — {mname}: {tag} {_n(camp)} {u} ({'; '.join(parts)})")
                else:
                    facts.append(f"{hlabel} — {mname}: {parts[0]}")
                headline.append(f"{mname} {'الساعة' if ar else 'at'} {hlabel}: {_n(camp)} {u}")
                continue

            if meta["kind"] == "site":
                line, st = _stats_line(wide["site"], metric, ar, f"{plabel} — {mname}")
                facts.append(line)
                if st:
                    headline.append(f"{mname} ({plabel}): " + (f"المتوسط {_n(st['mean'])} {meta['unit']}" if ar
                                                            else f"average {_n(st['mean'])} {meta['unit']}"))
                continue

            scope = _scope_label(plan.buildings, ar)
            line, st = _stats_line(wide["campus"], metric, ar, f"{plabel} — {mname} — {scope}")
            facts.append(line)
            bcols = [b for b in wide.columns if b != "campus"]
            if len(bcols) > 1:
                for b in bcols:
                    bl, _ = _stats_line(wide[b], metric, ar, f"   • {_bname(b, ar)}")
                    facts.append(bl)
            if st:
                if meta["kind"] == "energy":
                    headline.append(
                        (f"{mname} في {plabel} لـ{scope}: {_n(st['total'])} kWh (ذروة {_n(st['max'])} kW عند {st['max_at']})")
                        if ar else
                        (f"{_cap(mname)} for {scope} {_prep(p)} {plabel}: {_n(st['total'])} kWh "
                         f"(peak {_n(st['max'])} kW at {st['max_at']})"))
                else:
                    headline.append((f"{mname} في {plabel}: المتوسط {_n(st['mean'])}{meta['unit']}") if ar else
                                    (f"{_cap(mname)} {_prep(p)} {plabel}: average {_n(st['mean'])}{meta['unit']}"))

            # Context that helps explain a single day
            if p.kind == "day" and metric == "energy":
                facts.extend(_day_context(plan, data, p))
    return {"headline": headline, "facts": facts}


def _day_context(plan: Plan, data: ProjectData, p: Period) -> List[str]:
    ar = plan.arabic
    out: List[str] = []
    w = _slice(data.weather, p)
    if not w.empty and "temperature_c" in w:
        out.append((f"الطقس في {p.label}: الحرارة بين {_n(w['temperature_c'].min())} و{_n(w['temperature_c'].max())} °C "
                    f"(متوسط {_n(w['temperature_c'].mean())} °C)") if ar else
                   (f"Weather on {p.label}: {_n(w['temperature_c'].min())}–{_n(w['temperature_c'].max())} °C "
                    f"(mean {_n(w['temperature_c'].mean())} °C)"))
    # Compare with the same weekday average of that month
    wide = _series(data, "energy", plan.buildings, _month_period(p.start.year, p.start.month))
    if not wide.empty:
        daily = wide["campus"].resample("D").sum(min_count=1).dropna()
        same = daily[daily.index.dayofweek == p.start.dayofweek]
        today = daily.get(p.start.normalize())
        if today is not None and len(same) > 1:
            avg = same.mean()
            diff = (today - avg) / avg * 100 if avg else 0
            out.append((f"مقارنة: متوسط أيام {_weekday(p.start, True)} في نفس الشهر {_n(avg)} kWh، "
                        f"أي أن هذا اليوم {'أعلى' if diff >= 0 else 'أقل'} بنسبة {_n(abs(diff))}%") if ar else
                       (f"Comparison: the average {p.start:%A} in the same month used {_n(avg)} kWh, "
                        f"so this day was {_n(abs(diff))}% {'higher' if diff >= 0 else 'lower'}"))
    fc = _slice(data.forecast, p)
    if not fc.empty:
        if plan.buildings:
            fc = fc[fc["building_id"].isin(plan.buildings)]
        if not fc.empty:
            out.append((f"نموذج التنبؤ: الفعلي {_n(fc['energy'].sum())} kWh مقابل المتوقع {_n(fc['predicted_energy'].sum())} kWh "
                        f"(متوسط الخطأ المطلق {_n(fc['absolute_error'].mean(), 2)} kW)") if ar else
                       (f"ML forecast: actual {_n(fc['energy'].sum())} kWh vs predicted {_n(fc['predicted_energy'].sum())} kWh "
                        f"(mean absolute error {_n(fc['absolute_error'].mean(), 2)} kW)"))
    ev = _events_in(data, p, plan.buildings)
    if ev:
        out.append((f"أحداث مسجلة في هذا اليوم: {len(ev)}" if ar else f"Events recorded on this day: {len(ev)}"))
        out.extend(f"   • {e}" for e in ev[:5])
    return out


def _events_in(data: ProjectData, p: Optional[Period], buildings: List[str]) -> List[str]:
    rows: List[Tuple[pd.Timestamp, str]] = []
    a = _slice(data.anomalies, p)
    for _, r in a.iterrows():
        if buildings and r["building_id"] not in buildings:
            continue
        rows.append((r["timestamp"], f"{r['timestamp']:%Y-%m-%d %H:%M} {r['building_id']} {r['anomaly_type']} — "
                                     f"{r['anomaly_description']} (labelled anomaly)"))
    e = _slice(data.events, p)
    for _, r in e.iterrows():
        if buildings and r["building_id"] not in buildings and r["building_id"] != "CAMPUS":
            continue
        rows.append((r["timestamp"], f"{r['timestamp']:%Y-%m-%d %H:%M} {r['building_id']} {r['event_type']} "
                                     f"[{r['severity']}] value {r['value']} — {r['description']}"))
    rows.sort(key=lambda x: x[0])
    return [text for _, text in rows]


def _rank(plan: Plan, data: ProjectData) -> Dict[str, Any]:
    ar = plan.arabic
    metric = plan.metrics[0]
    meta = METRICS[metric]
    periods = plan.periods or [None]
    facts: List[str] = []
    headline: List[str] = []
    mname = meta["ar" if ar else "en"]
    agg = "sum" if meta["kind"] == "energy" else "mean"
    unit = "kWh" if meta["kind"] == "energy" else meta["unit"]
    word = {"max": ("الأعلى" if ar else "highest"), "min": ("الأقل" if ar else "lowest")}[plan.rank_dir]

    for p in periods:
        plabel = (_period_label(p, ar) if p else ("كامل البيانات" if ar else "the full dataset"))
        if plan.rank_unit == "building":
            if meta["kind"] == "site":
                facts.append("هذا المقياس على مستوى الموقع وليس لكل مبنى" if ar else "This metric is site-wide, not per building")
                continue
            wide = _series(data, metric, [], p)
            if wide.empty:
                continue
            vals = getattr(wide.drop(columns="campus"), agg)()
            vals = vals.sort_values(ascending=plan.rank_dir == "min")
            facts.append(f"{mname} {'حسب المبنى' if ar else 'by building'} — {plabel}:")
            for i, (b, v) in enumerate(vals.items(), 1):
                facts.append(f"   {i}. {_bname(b, ar)}: {_n(v)} {unit}{'' if agg == 'sum' else (' (متوسط)' if ar else ' (average)')}")
            b0 = vals.index[0]
            headline.append((f"المبنى صاحب {mname} {word} في {plabel}: {_bname(b0, ar)} ({_n(vals.iloc[0])} {unit})") if ar
                            else (f"The building with the {word} {mname} in {plabel} is {_bname(b0, ar)} "
                                  f"({_n(vals.iloc[0])} {unit})"))
            continue

        wide = _series(data, metric, plan.buildings, p)
        if wide.empty:
            continue
        s = wide["site"] if meta["kind"] == "site" else wide["campus"]
        if plan.rank_unit == "hour":
            if p is not None and p.kind == "day":
                ranked = s
                fmt = "%H:00"
            else:
                ranked = s.groupby(s.index.hour).mean()
                fmt = None
        elif plan.rank_unit == "month":
            ranked = s.resample("MS").mean() if agg == "mean" else s.resample("MS").sum(min_count=1)
            fmt = "%Y-%m"
        elif plan.rank_unit == "year":
            ranked = s.resample("YS").sum(min_count=1) if agg == "sum" else s.resample("YS").mean()
            fmt = "%Y"
        else:  # day
            ranked = s.resample("D").sum(min_count=1) if agg == "sum" else s.resample("D").mean()
            fmt = "%Y-%m-%d"
        ranked = ranked.dropna().sort_values(ascending=plan.rank_dir == "min")
        if ranked.empty:
            continue
        top = ranked.head(plan.top_n)
        scope = _scope_label(plan.buildings, ar) if meta["kind"] != "site" else ""
        unit_r = unit if not (plan.rank_unit == "hour" and fmt is None and meta["kind"] == "energy") else "kW"
        header = f"{mname} — {word} — {plabel}" + (f" — {scope}" if scope else "")
        facts.append(header + ":")
        for i, (k, v) in enumerate(top.items(), 1):
            if fmt is None:
                key = f"{int(k):02d}:00" + (" (متوسط كل الأيام)" if ar else " (average over all days)")
            else:
                key = k.strftime(fmt)
                if plan.rank_unit == "day":
                    key += f" ({_weekday(k, ar)})"
            facts.append(f"   {i}. {key}: {_n(v)} {unit_r}")
        k0, v0 = top.index[0], top.iloc[0]
        key0 = (f"{int(k0):02d}:00" if fmt is None else k0.strftime(fmt))
        unit_name = {"day": ("اليوم", "day"), "month": ("الشهر", "month"), "hour": ("الساعة", "hour"),
                     "year": ("السنة", "year")}[plan.rank_unit or "day"]
        headline.append((f"{unit_name[0]} صاحب {mname} {word} في {plabel}: {key0} بقيمة {_n(v0)} {unit_r}") if ar
                        else (f"The {unit_name[1]} with the {word} {mname} in {plabel} was {key0} "
                              f"with {_n(v0)} {unit_r}"))
    return {"headline": headline, "facts": facts}


def _events(plan: Plan, data: ProjectData) -> Dict[str, Any]:
    ar = plan.arabic
    facts: List[str] = []
    headline: List[str] = []
    for p in (plan.periods or [None]):
        plabel = _period_label(p, ar) if p else ("كامل البيانات" if ar else "the full dataset")
        rows = _events_in(data, p, plan.buildings)
        ev = _slice(data.events, p)
        an = _slice(data.anomalies, p)
        if plan.buildings:
            ev = ev[ev["building_id"].isin(plan.buildings + ["CAMPUS"])] if not ev.empty else ev
            an = an[an["building_id"].isin(plan.buildings)] if not an.empty else an
        headline.append((f"عدد الأحداث في {plabel}: {len(rows)}") if ar else f"Events in {plabel}: {len(rows)}")
        if not ev.empty:
            by_type = ev.groupby(["event_type", "severity"]).size()
            facts.append(("توزيع أحداث التنبؤ حسب النوع والخطورة:" if ar else "Prediction events by type and severity:"))
            facts.extend(f"   • {t} [{s}]: {c}" for (t, s), c in by_type.items())
        if not an.empty:
            facts.append((f"حالات شذوذ موسومة (anomaly labels): {len(an)}" if ar else f"Labelled anomalies: {len(an)}"))
        if rows:
            facts.append("أمثلة:" if ar else "Examples (chronological):")
            facts.extend(f"   • {r}" for r in rows[:12])
            if len(rows) > 12:
                facts.append(f"   … +{len(rows) - 12}")
        else:
            facts.append("لا توجد أحداث مسجلة في هذه الفترة" if ar else "No events recorded in this period")
    return {"headline": headline, "facts": facts}


def _actions(plan: Plan, data: ProjectData) -> Dict[str, Any]:
    ar = plan.arabic
    facts: List[str] = []
    headline: List[str] = []
    for p in (plan.periods or [None]):
        plabel = _period_label(p, ar) if p else ("كامل البيانات" if ar else "the full dataset")
        act = _slice(data.actions, p)
        ver = _slice(data.verification, p)
        if act.empty and ver.empty:
            facts.append(f"{plabel}: " + ("لا توجد إجراءات" if ar else "no actions"))
            continue
        if not act.empty:
            facts.append((f"{plabel}: {len(act)} توصية، مجموع التخفيض المتوقع {_n(act['estimated_reduction_kw'].sum())} kW") if ar
                         else (f"{plabel}: {len(act)} recommended actions, total estimated reduction "
                               f"{_n(act['estimated_reduction_kw'].sum())} kW"))
            facts.extend(f"   • {k}: {v}" for k, v in act["recommended_action"].value_counts().items())
        if not ver.empty:
            succ = (ver["verification_status"] == "SUCCESS").sum()
            rate = succ / len(ver) * 100
            facts.append((f"التحقق: {succ} من {len(ver)} ناجحة ({_n(rate)}%)، متوسط الأداء {_n(ver['performance_ratio_percent'].mean())}%، "
                          f"مجموع التخفيض المحقق {_n(ver['achieved_reduction_kw'].sum())} kW") if ar else
                         (f"Verification: {succ} of {len(ver)} SUCCESS ({_n(rate)}%), mean performance "
                          f"{_n(ver['performance_ratio_percent'].mean())}%, total achieved reduction "
                          f"{_n(ver['achieved_reduction_kw'].sum())} kW"))
            under = ver[ver["verification_status"] != "SUCCESS"]
            for _, r in under.head(5).iterrows():
                facts.append(f"   • {r['timestamp']:%Y-%m-%d %H:%M} {r['executed_action']} "
                             f"{r['verification_status']} ({_n(r['performance_ratio_percent'])}%)")
            headline.append((f"نسبة نجاح الإجراءات في {plabel}: {_n(rate)}% ({succ}/{len(ver)})") if ar else
                            (f"Action success rate in {plabel}: {_n(rate)}% ({succ}/{len(ver)})"))
    return {"headline": headline, "facts": facts}


def _forecast(plan: Plan, data: ProjectData) -> Dict[str, Any]:
    ar = plan.arabic
    facts: List[str] = []
    headline: List[str] = []
    fc_all = data.forecast
    if fc_all.empty:
        return {"headline": [], "facts": ["No forecast results file" if not ar else "لا يوجد ملف نتائج التنبؤ"]}
    for p in (plan.periods or [None]):
        fc = _slice(fc_all, p)
        if plan.buildings:
            fc = fc[fc["building_id"].isin(plan.buildings)]
        plabel = _period_label(p, ar) if p else (
            f"فترة الاختبار {fc_all['timestamp'].min():%Y-%m-%d} → {fc_all['timestamp'].max():%Y-%m-%d}" if ar else
            f"test period {fc_all['timestamp'].min():%Y-%m-%d} → {fc_all['timestamp'].max():%Y-%m-%d}")
        if fc.empty:
            facts.append((f"{plabel}: لا توجد نتائج تنبؤ (نتائج الاختبار تغطي "
                          f"{fc_all['timestamp'].min():%Y-%m-%d} → {fc_all['timestamp'].max():%Y-%m-%d})") if ar else
                         (f"{plabel}: no forecast results (the test set covers "
                          f"{fc_all['timestamp'].min():%Y-%m-%d} → {fc_all['timestamp'].max():%Y-%m-%d})"))
            continue
        mae = fc["absolute_error"].mean()
        mape = (fc["absolute_error"] / fc["energy"].where(fc["energy"] > 0)).mean() * 100
        facts.append((f"{plabel}: MAE {_n(mae, 2)} kW، MAPE {_n(mape, 2)}% على {len(fc):,} قراءة") if ar else
                     (f"{plabel}: MAE {_n(mae, 2)} kW, MAPE {_n(mape, 2)}% over {len(fc):,} hourly readings"))
        for b, g in fc.groupby("building_id"):
            facts.append(f"   • {_bname(b, ar)}: MAE {_n(g['absolute_error'].mean(), 2)} kW")
        headline.append((f"دقة نموذج التنبؤ في {plabel}: متوسط الخطأ المطلق {_n(mae, 2)} kW") if ar else
                        (f"Forecast accuracy for {plabel}: mean absolute error {_n(mae, 2)} kW (MAPE {_n(mape, 2)}%)"))
    return {"headline": headline, "facts": facts}


def _overview(plan: Plan, data: ProjectData) -> Dict[str, Any]:
    ar = plan.arabic
    r = data.readings
    days = (data.last.normalize() - data.first.normalize()).days + 1
    total = r["energy"].sum()
    facts = [
        (f"الفترة: {data.first:%Y-%m-%d} → {data.last:%Y-%m-%d} ({days} يوم، قراءات كل ساعة)") if ar else
        (f"Period: {data.first:%Y-%m-%d} → {data.last:%Y-%m-%d} ({days} days, hourly readings)"),
        (f"عدد القراءات: {len(r):,} (3 مباني)") if ar else f"Readings: {len(r):,} across 3 buildings",
    ]
    for b, g in r.groupby("building_id"):
        facts.append(f"   • {_bname(b, ar)}: " + (f"مجموع {_n(g['energy'].sum())} kWh، متوسط {_n(g['energy'].mean())} kW" if ar else
                                                  f"total {_n(g['energy'].sum())} kWh, average {_n(g['energy'].mean())} kW"))
    for y, g in r.groupby(r["timestamp"].dt.year):
        facts.append((f"سنة {y}: مجموع استهلاك الحرم {_n(g['energy'].sum())} kWh") if ar else
                     (f"{y}: campus consumption {_n(g['energy'].sum())} kWh"))
    facts.append((f"الأحداث: {len(data.events)} حدث تنبؤ، {len(data.anomalies)} شذوذ موسوم، {len(data.actions)} توصية، "
                  f"{len(data.verification)} نتيجة تحقق") if ar else
                 (f"Events: {len(data.events)} prediction events, {len(data.anomalies)} labelled anomalies, "
                  f"{len(data.actions)} recommended actions, {len(data.verification)} verification results"))
    facts.append("المصدر: Building Data Genome 2 (موقع Robin)" if ar else "Source: Building Data Genome 2 (Robin site)")
    headline = [(f"البيانات تغطي {data.first:%Y-%m-%d} إلى {data.last:%Y-%m-%d} لثلاثة مباني، مجموع الاستهلاك {_n(total)} kWh") if ar
                else (f"The dataset covers {data.first:%Y-%m-%d} to {data.last:%Y-%m-%d} for 3 buildings, "
                      f"total consumption {_n(total)} kWh")]
    return {"headline": headline, "facts": facts}


# =========================================================
# STORIES (the plain-language answer shown first)
# =========================================================

HOUR_SENTENCE = {
    "energy": ("كان {scope} يستهلك حوالي **{value}**", "{scope} was drawing about **{value}**"),
    "hvac": ("كان التكييف في {scope} يستهلك حوالي **{value}**", "air-conditioning in {scope} was drawing about **{value}**"),
    "solar": ("كانت الألواح الشمسية في {scope} تولّد حوالي **{value}**", "the solar panels at {scope} were producing about **{value}**"),
    "ev": ("كان شحن السيارات الكهربائية في {scope} يستهلك حوالي **{value}**", "EV charging at {scope} was drawing about **{value}**"),
}


def _sent(s: str) -> str:
    s = s.strip()
    return s[:1].upper() + s[1:] if s and s[0].isascii() else s


def _join_ar(items: List[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return "، ".join(items[:-1]) + " و" + items[-1]


def _join_en(items: List[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _grid_note(mean: float, ar: bool) -> str:
    level = (("منخفض", "low") if mean < 0.35 else ("متوسط", "moderate") if mean < 0.6 else ("مرتفع", "high"))
    return (f"هذا المقياس من 0 (الشبكة مرتاحة) إلى 1 (الشبكة مجهدة جداً)، أي أن الإجهاد كان {level[0]}." if ar else
            f"The scale runs from 0 (grid relaxed) to 1 (grid heavily stressed), so the stress was {level[1]}.")


def _event_records(data: ProjectData, p: Optional[Period], buildings: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    a = _slice(data.anomalies, p)
    for _, r in a.iterrows():
        if buildings and r["building_id"] not in buildings:
            continue
        rows.append({"ts": r["timestamp"], "b": r["building_id"], "type": r["anomaly_type"], "sev": None,
                     "labelled": True})
    e = _slice(data.events, p)
    for _, r in e.iterrows():
        if buildings and r["building_id"] not in buildings and r["building_id"] != "CAMPUS":
            continue
        rows.append({"ts": r["timestamp"], "b": r["building_id"], "type": r["event_type"], "sev": r["severity"],
                     "labelled": False})
    rows.sort(key=lambda x: x["ts"])
    return rows


def _event_phrase(ev: Dict[str, Any], ar: bool, same_day: bool) -> str:
    name = EVENT_NAMES.get(ev["type"], (ev["type"], ev["type"]))[0 if ar else 1]
    where = ("الحرم كاملاً" if ar else "the whole campus") if ev["b"] == "CAMPUS" else _hbuilding(ev["b"], ar)
    when = _hwhen(ev["ts"], ar, same_day)
    return f"{name} في {where} {when}" if ar else f"{name} in {where} {when}"


def _story_hour(plan: Plan, data: ProjectData, metric: str, ts: pd.Timestamp, row: pd.Series,
                wide: pd.DataFrame) -> List[str]:
    ar = plan.arabic
    meta = METRICS[metric]
    mname = meta["ar" if ar else "en"]
    when = _hperiod(Period(ts, ts + pd.Timedelta(hours=1), "hour", ""), ar)
    if meta["kind"] == "site":
        v = row["site"]
        out = [(f"{when} كانت {mname} حوالي **{_hn(v, meta['unit'], ar)}**." if ar else
                f"{when}, the {mname} was about **{_hn(v, meta['unit'], ar)}**.")]
        if metric == "grid":
            out.append(_grid_note(v, ar))
        return out
    u = "kW" if meta["kind"] == "energy" else meta["unit"]
    scope = _hscope(plan.buildings or ([] if metric != "battery" else ["B002"]), ar)
    camp = row["campus"]
    if meta["kind"] == "energy":
        tpl = HOUR_SENTENCE[metric][0 if ar else 1]
        first = tpl.format(scope=scope, value=_hn(camp, u, ar))
    else:
        first = (f"كانت {mname} في {scope} حوالي **{_hn(camp, u, ar)}**" if ar else
                 f"the {mname} in {scope} was about **{_hn(camp, u, ar)}**")
    out = [(f"{when}، {first}." if ar else f"{when}, {first}.")]
    bcols = [b for b in wide.columns if b != "campus" and not pd.isna(row.get(b))]
    if len(bcols) > 1:
        parts = sorted(((b, row[b]) for b in bcols), key=lambda x: -x[1])
        items = [f"{BUILDINGS[b]['ar' if ar else 'en']} {_hn(v, u, ar)}" for b, v in parts]
        out.append((f"حسب المبنى: {_join_ar(items)}." if ar else f"By building: {_join_en(items)}."))
    if metric == "solar" and camp < 1 and (ts.hour < 6 or ts.hour >= 20):
        out.append("هذا طبيعي لأن الوقت ليل ولا يوجد ضوء شمس." if ar else "That is expected: it was dark, so there was no sunlight.")
    return out


def _story_energy_period(plan: Plan, data: ProjectData, metric: str, p: Period, wide: pd.DataFrame) -> Tuple[List[str], float]:
    ar = plan.arabic
    meta = METRICS[metric]
    s = wide["campus"].dropna()
    total = float(s.sum())
    scope = _hscope(plan.buildings, ar)
    tpl = METRIC_SENTENCE[metric][0 if ar else 1]
    lead = tpl.format(scope=scope, value=_hn(total, "kWh", ar))
    when = _hperiod(p, ar, data)
    days = max(1, round((s.index.max() - s.index.min()) / pd.Timedelta(days=1)))
    extra = ""
    if p.kind != "day" and days > 1:
        extra = (f"، أي بمعدل {_hn(total / days, 'kWh', ar)} في اليوم" if ar else
                 f", or about {_hn(total / days, 'kWh', ar)} a day")
    out = [(f"{when}، {lead}{extra}." if ar else f"{when}, {lead}{extra}.")]

    same_day = p.kind == "day"
    pk, lo = s.idxmax(), s.idxmin()
    if metric == "solar":
        out.append((f"بلغ الإنتاج ذروته {_hwhen(pk, ar, same_day)} (حوالي {_hn(s.max(), 'kW', ar)})." if ar else
                    f"Generation peaked {_hwhen(pk, ar, same_day)} (about {_hn(s.max(), 'kW', ar)})."))
    else:
        noun = ("طلب" if metric == "energy" else "استهلاك") if ar else ("Demand" if metric == "energy" else "Use")
        line = (f"كان أعلى {noun} {_hwhen(pk, ar, same_day)} (حوالي {_hn(s.max(), 'kW', ar)})، "
                f"وأقل {noun} {_hwhen(lo, ar, same_day)} (حوالي {_hn(s.min(), 'kW', ar)})." if ar else
                f"{noun} peaked {_hwhen(pk, ar, same_day)} (about {_hn(s.max(), 'kW', ar)}) and was lowest "
                f"{_hwhen(lo, ar, same_day)} (about {_hn(s.min(), 'kW', ar)}).")
        if same_day and metric == "energy" and 9 <= pk.hour <= 18 and (lo.hour < 7 or lo.hour >= 20):
            line += (" وهذا نمط طبيعي: يرتفع الاستهلاك خلال ساعات الدوام وينخفض في الليل." if ar else
                     " That is the normal pattern: use rises during working hours and falls at night.")
        out.append(line)

    bcols = [b for b in wide.columns if b != "campus"]
    if len(bcols) > 1 and total > 0:
        tot = sorted(((b, float(wide[b].sum())) for b in bcols), key=lambda x: -x[1])
        pct = lambda v: _hpct(v / total * 100)  # noqa: E731
        b0, v0 = tot[0]
        rest = [_bval(b, _hn(v, 'kWh', ar), ar, pct(v)) for b, v in tot[1:]]
        out.append((f"صاحب الحصة الأكبر هو {_hbuilding(b0, ar)} بحوالي {_hn(v0, 'kWh', ar)} ({pct(v0)} من المجموع)، "
                     f"يليه {' ثم '.join(rest)}." if ar else
                     _sent(f"{_hbuilding(b0, ar)} had the largest share, about {_hn(v0, 'kWh', ar)} ({pct(v0)} of the total), "
                           f"followed by {_join_en(rest)}.")))

    if same_day and metric == "energy":
        out.extend(_story_day_context(plan, data, p))
    elif p.kind in {"month", "year"} and len(plan.periods) == 1:
        other = None
        for y in (p.start.year - 1, p.start.year + 1):
            q = _month_period(y, p.start.month) if p.kind == "month" else _year_period(y)
            if q.start >= data.first and q.end <= data.last + pd.Timedelta(hours=1):
                other = q
                break
        if other is not None:
            w2 = _series(data, metric, plan.buildings, other)
            if not w2.empty:
                t2 = float(w2["campus"].sum())
                if t2:
                    diff = (total - t2) / t2 * 100
                    olabel = _hmonth(other.start, ar) if p.kind == "month" else str(other.start.year)
                    out.append((f"للمقارنة: في {olabel} كان المجموع حوالي {_hn(t2, 'kWh', ar)}، "
                                f"فكانت هذه الفترة {_change_word(diff, ar)}." if ar else
                                f"For comparison, {olabel} came to about {_hn(t2, 'kWh', ar)}, "
                                f"so this period was {_change_word(diff, ar)}."))
    return out, total


def _story_day_context(plan: Plan, data: ProjectData, p: Period) -> List[str]:
    ar = plan.arabic
    out: List[str] = []
    wide = _series(data, "energy", plan.buildings, _month_period(p.start.year, p.start.month))
    if not wide.empty:
        daily = wide["campus"].resample("D").sum(min_count=1).dropna()
        same = daily[daily.index.dayofweek == p.start.dayofweek]
        today = daily.get(p.start.normalize())
        if today is not None and len(same) > 1 and same.mean():
            avg = same.mean()
            diff = (today - avg) / avg * 100
            out.append((f"للمقارنة: متوسط أيام {_weekday(p.start, True)} في نفس الشهر كان حوالي {_hn(avg, 'kWh', ar)}، "
                        f"فكان هذا اليوم {_change_word(diff, ar)}." if ar else
                        f"For comparison, an average {p.start:%A} that month used about {_hn(avg, 'kWh', ar)}, "
                        f"so this day was {_change_word(diff, ar)}."))
    w = _slice(data.weather, p)
    if not w.empty and "temperature_c" in w:
        t = w["temperature_c"]
        out.append((f"كان الطقس {_weather_word(t.mean(), ar)}، والحرارة بين {_hn(t.min(), '°C', ar)} و{_hn(t.max(), '°C', ar)}." if ar else
                    f"The weather was {_weather_word(t.mean(), ar)}, between {_hn(t.min(), '°C', ar)} and {_hn(t.max(), '°C', ar)}."))
    fc = _slice(data.forecast, p)
    if not fc.empty and plan.buildings:
        fc = fc[fc["building_id"].isin(plan.buildings)]
    if not fc.empty:
        act, pred = fc["energy"].sum(), fc["predicted_energy"].sum()
        gap = abs(act - pred) / act * 100 if act else 0
        if gap < 0.1:
            out.append((f"وكان نموذج التنبؤ قد توقّع حوالي {_hn(pred, 'kWh', ar)} لهذا اليوم، أي تقريباً نفس الاستهلاك الفعلي (الفرق أقل من 0.1%)." if ar else
                        f"The forecasting model had predicted about {_hn(pred, 'kWh', ar)} for this day — almost exactly what was used (less than 0.1% off)."))
        else:
            out.append((f"وكان نموذج التنبؤ قد توقّع حوالي {_hn(pred, 'kWh', ar)} لهذا اليوم، أي بفرق {_hpct(gap)} فقط عن الاستهلاك الفعلي." if ar else
                        f"The forecasting model had predicted about {_hn(pred, 'kWh', ar)} for this day, only {_hpct(gap)} away from what was actually used."))
    ev = _event_records(data, p, plan.buildings)
    if ev:
        items = [_event_phrase(e, ar, True) for e in ev[:3]]
        more = len(ev) - len(items)
        if ar:
            head = "سُجّل في هذا اليوم " + _ar_count(len(ev), "حدث", "حدثان", "أحداث", "حدثاً")
            out.append(f"{head}: {'؛ '.join(items)}" + (f" (و{more} غيرها في التفاصيل)" if more > 0 else "") + ".")
        else:
            out.append(f"{len(ev)} event{'s were' if len(ev) > 1 else ' was'} recorded that day: {'; '.join(items)}"
                       + (f" (and {more} more in the details)" if more > 0 else "") + ".")
    else:
        out.append("لم يُسجَّل أي حدث غير طبيعي في هذا اليوم." if ar else "No unusual events were recorded that day.")
    return out


def _story_level_period(plan: Plan, data: ProjectData, metric: str, p: Period, wide: pd.DataFrame) -> List[str]:
    ar = plan.arabic
    meta = METRICS[metric]
    mname = meta["ar" if ar else "en"]
    u = meta["unit"]
    s = (wide["site"] if meta["kind"] == "site" else wide["campus"]).dropna()
    if s.empty:
        return []
    same_day = p.kind == "day"
    when = _hperiod(p, ar, data)
    where = ""
    if meta["kind"] != "site":
        blds = plan.buildings or (["B002"] if metric == "battery" else [])
        where = (f" في {_hscope(blds, ar)}" if ar else f" in {_hscope(blds, ar)}")
    lo_t, hi_t = s.idxmin(), s.idxmax()
    out = [(f"{when}، كان متوسط {mname}{where} حوالي **{_hn(s.mean(), u, ar)}**، "
            f"وتراوح بين {_hn(s.min(), u, ar)} ({_hwhen(lo_t, ar, same_day)}) و{_hn(s.max(), u, ar)} ({_hwhen(hi_t, ar, same_day)})." if ar else
            f"{when}, the average {mname}{where} was about **{_hn(s.mean(), u, ar)}**, ranging from "
            f"{_hn(s.min(), u, ar)} ({_hwhen(lo_t, ar, same_day)}) to {_hn(s.max(), u, ar)} ({_hwhen(hi_t, ar, same_day)}).")]
    if metric == "grid":
        out.append(_grid_note(s.mean(), ar))
    if metric == "battery" and not plan.buildings:
        out.append("البطارية موجودة في مبنى المختبرات (B002) فقط." if ar else "Only the Labs building (B002) has a battery.")
    return out


def _story_summary(plan: Plan, data: ProjectData) -> List[str]:
    ar = plan.arabic
    out: List[str] = []
    periods = plan.periods or [Period(data.first, data.last + pd.Timedelta(hours=1), "all", "")]
    totals: Dict[str, List[Tuple[Period, float]]] = {}
    for p in periods:
        for metric in plan.metrics:
            meta = METRICS[metric]
            wide = _series(data, metric, plan.buildings, p)
            mname = meta["ar" if ar else "en"]
            if wide.empty:
                out.append((f"{_hperiod(p, ar, data)}، لا توجد بيانات عن {mname}." if ar else
                            f"{_hperiod(p, ar, data)}, there is no {mname} data."))
                continue
            if plan.hour is not None and p.kind == "day":
                ts = p.start + pd.Timedelta(hours=plan.hour)
                row = wide.loc[wide.index == ts]
                if row.empty:
                    out.append(("لا توجد قراءة لهذه الساعة." if ar else "There is no reading for that hour."))
                    continue
                out.extend(_story_hour(plan, data, metric, ts, row.iloc[0], wide))
                continue
            if meta["kind"] == "energy":
                paras, total = _story_energy_period(plan, data, metric, p, wide)
                out.extend(paras)
                totals.setdefault(metric, []).append((p, total))
            else:
                out.extend(_story_level_period(plan, data, metric, p, wide))
    for metric, vals in totals.items():
        if len(vals) == 2 and vals[0][1]:
            (p1, t1), (p2, t2) = vals
            diff = (t2 - t1) / t1 * 100
            mname = METRICS[metric]["ar" if ar else "en"]
            a, b = _hperiod(p1, ar, data), _hperiod(p2, ar, data)
            out.insert(0, (f"باختصار: {mname} {b} كان {_change_word(diff, ar)} منه {a}." if ar else
                           f"In short, {mname} {_mid(b)} was {_change_word(diff, ar)} than {_mid(a)}."))
    return out


def _rank_key(k: Any, unit: Optional[str], by_hour_avg: bool, ar: bool) -> str:
    if by_hour_avg:
        return _hhour(int(k), ar)
    if unit == "hour":
        return _hhour(k.hour, ar)
    if unit == "month":
        return _hmonth(k, ar)
    if unit == "year":
        return str(k.year)
    return _hdate(k, ar)


def _story_rank(plan: Plan, data: ProjectData) -> List[str]:
    ar = plan.arabic
    metric = plan.metrics[0]
    meta = METRICS[metric]
    mname = meta["ar" if ar else "en"]
    agg = "sum" if meta["kind"] == "energy" else "mean"
    unit = "kWh" if meta["kind"] == "energy" else meta["unit"]
    word = {"max": ("الأعلى", "highest"), "min": ("الأقل", "lowest")}[plan.rank_dir][0 if ar else 1]
    out: List[str] = []
    for p in (plan.periods or [None]):
        when = _hperiod(p, ar, data)
        if plan.rank_unit == "building":
            if meta["kind"] == "site":
                out.append("هذا المقياس واحد للموقع كله، وليس لكل مبنى على حدة." if ar else
                           "This measure is the same for the whole site, not per building.")
                continue
            wide = _series(data, metric, [], p)
            if wide.empty:
                continue
            vals = getattr(wide.drop(columns="campus"), agg)().sort_values(ascending=plan.rank_dir == "min")
            b0, v0 = vals.index[0], float(vals.iloc[0])
            share = ""
            if agg == "sum" and vals.sum():
                share = (f" ({_hpct(v0 / vals.sum() * 100)} من مجموع الحرم)" if ar else
                         f" ({_hpct(v0 / vals.sum() * 100)} of the campus total)")
            avg_note = "" if agg == "sum" else (" في المتوسط" if ar else " on average")
            rest = [_bval(b, _hn(v, unit, ar), ar) for b, v in list(vals.items())[1:]]
            if ar:
                out.append(f"{when}، كان {_hbuilding(b0, ar)} صاحب {mname} {word}: حوالي **{_hn(v0, unit, ar)}**{avg_note}{share}."
                           + (f" يليه {' ثم '.join(rest)}." if rest else ""))
            else:
                out.append(f"{when}, {_hbuilding(b0, ar)} had the {word} {mname}: about **{_hn(v0, unit, ar)}**{avg_note}{share}."
                           + (f" It is followed by {_join_en(rest)}." if rest else ""))
            continue

        wide = _series(data, metric, plan.buildings, p)
        if wide.empty:
            continue
        s = wide["site"] if meta["kind"] == "site" else wide["campus"]
        by_hour_avg = False
        if plan.rank_unit == "hour":
            if p is not None and p.kind == "day":
                ranked = s
            else:
                ranked = s.groupby(s.index.hour).mean()
                by_hour_avg = True
        elif plan.rank_unit == "month":
            ranked = s.resample("MS").mean() if agg == "mean" else s.resample("MS").sum(min_count=1)
        elif plan.rank_unit == "year":
            ranked = s.resample("YS").sum(min_count=1) if agg == "sum" else s.resample("YS").mean()
        else:
            ranked = s.resample("D").sum(min_count=1) if agg == "sum" else s.resample("D").mean()
        ranked = ranked.dropna().sort_values(ascending=plan.rank_dir == "min")
        if ranked.empty:
            continue
        top = ranked.head(max(plan.top_n, 3))
        u = unit if not (plan.rank_unit == "hour" and meta["kind"] == "energy") else "kW"
        keys = [_rank_key(k, plan.rank_unit, by_hour_avg, ar) for k in top.index]
        vals = [_hn(float(v), u, ar) for v in top.values]
        scope = "" if meta["kind"] == "site" else (f" في {_hscope(plan.buildings, ar)}" if ar else f" for {_hscope(plan.buildings, ar)}")
        unit_word = {"day": ("اليوم", "day"), "month": ("الشهر", "month"), "hour": ("الساعة", "hour"),
                     "year": ("السنة", "year")}[plan.rank_unit or "day"]
        owner = "صاحبة" if plan.rank_unit in {"hour", "year"} else "صاحب"
        pre = ("في المتوسط، " if ar else "On average, ") if by_hour_avg else ""
        fem = plan.rank_unit in {"hour", "year"}
        if ar:
            line = (f"{pre}{unit_word[0]} {owner} {mname} {word} {when} {'كانت' if fem else 'كان'} **{keys[0]}**، "
                    f"بحوالي **{vals[0]}**{scope}.")
        else:
            the = "the" if pre else "The"
            line = (f"{pre}{the} {unit_word[1]} with the {word} {mname} {_mid(when)} was **{keys[0]}**, "
                    f"with about **{vals[0]}**{scope}.")
        nxt = [f"{k} ({v})" for k, v in zip(keys[1:3], vals[1:3])]
        if nxt:
            line += (f" {'تليها' if fem else 'يليه'} {' ثم '.join(nxt)}." if ar else
                     f" Next {'come' if len(nxt) > 1 else 'comes'} {_join_en(nxt)}.")
        out.append(line)
        if by_hour_avg and metric == "energy":
            h0 = int(top.index[0])
            if plan.rank_dir == "max" and 11 <= h0 <= 17:
                out.append("أي أن ذروة الطلب تكون عادةً بعد الظهر، خلال ساعات الدوام." if ar else
                           "In other words, demand usually peaks in the afternoon, during working hours.")
            elif plan.rank_dir == "min" and (h0 <= 6 or h0 >= 22):
                out.append("أي أن أهدأ وقت يكون عادةً في ساعات الليل المتأخرة." if ar else
                           "In other words, the quietest time is usually late at night.")
        if len(ranked) > 3 and plan.top_n > 3:
            out.append("القائمة الكاملة في التفاصيل أدناه." if ar else "The full list is in the details below.")
    return out


def _story_events(plan: Plan, data: ProjectData) -> List[str]:
    ar = plan.arabic
    out: List[str] = []
    for p in (plan.periods or [None]):
        when = _hperiod(p, ar, data)
        rows = _event_records(data, p, plan.buildings)
        if not rows:
            out.append((f"{when}، لا توجد أحداث مسجلة. لم يرصد النظام أي خطر ذروة أو استهلاك غير طبيعي." if ar else
                        f"{when}, no events were recorded: the system saw no peak risk and no unusual consumption."))
            continue
        n = len(rows)
        out.append((f"{when}، سُجّل **{_ar_count(n, 'حدث', 'حدثان', 'أحداث', 'حدثاً')}**." if ar else
                    f"{when}, **{n} event{'s' if n != 1 else ''}** {'were' if n != 1 else 'was'} recorded."))
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            by_type.setdefault(r["type"], []).append(r)
        items = []
        for t, rs in sorted(by_type.items(), key=lambda x: -len(x[1])):
            name = EVENT_NAMES.get(t, (t, t))[0 if ar else 1]
            sev: Dict[str, int] = {}
            for r in rs:
                if r["sev"]:
                    sev[r["sev"]] = sev.get(r["sev"], 0) + 1
            sev_txt = ""
            if sev:
                parts = [f"{c} {SEVERITY_NAMES.get(k, (k, k))[0 if ar else 1]}"
                         for k, c in sorted(sev.items(), key=lambda x: -x[1])]
                sev_txt = f" ({_join_ar(parts) if ar else _join_en(parts)})"
            items.append(f"{name}: {len(rs)}{sev_txt}")
        out.append(("وتوزّعت كالتالي — " + "؛ ".join(items) + "." if ar else "By type — " + "; ".join(items) + "."))
        if n > 3:
            per_day = pd.Series([r["ts"].normalize() for r in rows]).value_counts()
            d0, c0 = per_day.index[0], int(per_day.iloc[0])
            if c0 > 1:
                out.append((f"أكثر يوم فيه أحداث كان {_hdate(d0, ar)} ({c0} أحداث)." if ar else
                            f"The busiest day was {_hdate(d0, ar)}, with {c0} events."))
        else:
            ex = [_event_phrase(r, ar, False) for r in rows]
            out.append(("وهي: " + "؛ ".join(ex) + "." if ar else "They were: " + "; ".join(ex) + "."))
    return out


def _story_actions(plan: Plan, data: ProjectData) -> List[str]:
    ar = plan.arabic
    out: List[str] = []
    for p in (plan.periods or [None]):
        when = _hperiod(p, ar, data)
        ver = _slice(data.verification, p)
        act = _slice(data.actions, p)
        if ver.empty and act.empty:
            out.append((f"{when}، لم ينفّذ الوكيل أي إجراء." if ar else f"{when}, the agent carried out no actions."))
            continue
        if not ver.empty:
            n = len(ver)
            succ = int((ver["verification_status"] == "SUCCESS").sum())
            rate = succ / n * 100
            k = round(rate / 10)
            out.append((f"{when}، نفّذ الوكيل {_ar_count(n, 'إجراء', 'إجراءان', 'إجراءات', 'إجراءً')} وتم التحقق من نتائجها، "
                        f"نجح منها **{succ}** — أي حوالي **{_hpct(rate)}** (تقريباً {k} من كل 10)." if ar else
                        f"{when}, the agent carried out {n} verified actions and **{succ}** of them succeeded — "
                        f"about **{_hpct(rate)}** (roughly {k} out of every 10)."))
            under = n - succ
            if under:
                out.append((f"أما الـ{under} الباقية فحققت تخفيضاً أقل من المتوقع (UNDERPERFORMED)، ولهذا اقترح الوكيل لها إعادة التخطيط." if ar else
                            f"The other {under} saved less than expected (UNDERPERFORMED), so the agent proposed replanning for them."))
            out.append((f"في المتوسط حققت الإجراءات {_hpct(ver['performance_ratio_percent'].mean())} من التخفيض المتوقع، "
                        f"وبلغ مجموع التخفيض الفعلي حوالي {_hn(ver['achieved_reduction_kw'].sum(), 'kW', ar)}." if ar else
                        f"On average the actions delivered {_hpct(ver['performance_ratio_percent'].mean())} of the expected reduction, "
                        f"and together they cut about {_hn(ver['achieved_reduction_kw'].sum(), 'kW', ar)} of load."))
            g = ver.groupby("executed_action")["verification_status"].apply(lambda x: (x == "SUCCESS").mean() * 100)
            if len(g) > 1:
                best = g.idxmax()
                nm = ACTION_NAMES.get(best, (best, best))[0 if ar else 1]
                out.append((f"أعلى نسبة نجاح كانت {_li(nm)} ({_hpct(g.max())})." if ar else
                            f"The most reliable was {nm} ({_hpct(g.max())} success)."))
        if not act.empty:
            vc = act["recommended_action"].value_counts()
            nm = ACTION_NAMES.get(vc.index[0], (vc.index[0], vc.index[0]))[0 if ar else 1]
            out.append((f"الإجراء الأكثر استخداماً كان {nm} ({vc.iloc[0]} مرة)." if ar else
                        f"The action used most often was {nm} ({vc.iloc[0]} times)."))
    return out


def _story_forecast(plan: Plan, data: ProjectData) -> List[str]:
    ar = plan.arabic
    fc_all = data.forecast
    out: List[str] = []
    if fc_all.empty:
        return ["لا يوجد ملف نتائج التنبؤ." if ar else "There is no forecast results file."]
    lo, hi = fc_all["timestamp"].min(), fc_all["timestamp"].max()
    for p in (plan.periods or [None]):
        fc = _slice(fc_all, p)
        if plan.buildings:
            fc = fc[fc["building_id"].isin(plan.buildings)]
        when = (_hperiod(p, ar, data) if p else
                (f"خلال فترة اختبار النموذج ({_hdate(lo, ar, False)} – {_hdate(hi, ar, False)})" if ar else
                 f"Over the model's test period ({_hdate(lo, ar, False)} – {_hdate(hi, ar, False)})"))
        if fc.empty:
            out.append((f"{when}، لا توجد نتائج تنبؤ؛ نتائج الاختبار تغطي من {_hdate(lo, ar, False)} إلى {_hdate(hi, ar, False)} فقط." if ar else
                        f"{when}, there are no forecast results; the test set only covers {_hdate(lo, ar, False)} to {_hdate(hi, ar, False)}."))
            continue
        mae = fc["absolute_error"].mean()
        mape = (fc["absolute_error"] / fc["energy"].where(fc["energy"] > 0)).mean() * 100
        q = (("دقيقاً جداً", "very accurate") if mape < 5 else ("دقيقاً", "accurate") if mape < 10 else
             ("مقبول الدقة", "reasonably accurate") if mape < 20 else ("ضعيف الدقة", "not very accurate"))
        only = (" فقط" if ar else "") if mape < 10 else ""
        only_en = " only" if (mape < 10 and not ar) else ""
        out.append((f"{when}، كان نموذج التنبؤ {q[0]}: متوسط خطئه حوالي **{_hn(mae, 'kW', ar)}** في الساعة، "
                    f"أي أن توقعاته ابتعدت عن الاستهلاك الفعلي بحوالي **{_hpct(mape)}**{only} في المتوسط." if ar else
                    f"{when}, the forecasting model was {q[1]}: its average error was about **{_hn(mae, 'kW', ar)}** per hour, "
                    f"meaning its predictions were off by{only_en} about **{_hpct(mape)}** on average."))
        g = fc.groupby("building_id")["absolute_error"].mean()
        if len(g) > 1:
            b_best, b_worst = g.idxmin(), g.idxmax()
            line = (f"كانت التوقعات الأدق {_li(_hbuilding(b_best, ar))} (خطأ {_hn(g.min(), 'kW', ar)})، "
                    f"والأقل دقة {_li(_hbuilding(b_worst, ar))} (خطأ {_hn(g.max(), 'kW', ar)})." if ar else
                    _sent(f"predictions were closest for {_hbuilding(b_best, ar)} (error {_hn(g.min(), 'kW', ar)}) "
                          f"and furthest for {_hbuilding(b_worst, ar)} (error {_hn(g.max(), 'kW', ar)})."))
            if b_worst == "B002":
                line += (" وهذا متوقع لأنه المبنى الأكبر استهلاكاً، فأي نسبة خطأ صغيرة تعني كيلوواطات أكثر." if ar else
                         " That is expected: it is the largest consumer, so a small percentage error means more kilowatts.")
            out.append(line)
    return out


def _story_overview(plan: Plan, data: ProjectData) -> List[str]:
    ar = plan.arabic
    r = data.readings
    days = (data.last.normalize() - data.first.normalize()).days + 1
    total = r["energy"].sum()
    out = [(f"تغطي البيانات الفترة من {_hdate(data.first, ar, False)} إلى {_hdate(data.last, ar, False)} ({days:,} يوماً)، "
            f"بقراءة كل ساعة لثلاثة مباني: الإدارة (B001) والمختبرات (B002) والقاعات الدراسية (B003) — "
            f"أي {len(r):,} قراءة." if ar else
            f"The data covers {_hdate(data.first, ar, False)} to {_hdate(data.last, ar, False)} ({days:,} days), "
            f"with a reading every hour for three buildings: Administration (B001), Labs (B002) and Classrooms (B003) — "
            f"{len(r):,} readings in all.")]
    years = r.groupby(r["timestamp"].dt.year)["energy"].sum()
    ys = [f"{_hn(v, 'kWh', ar)} {'في' if ar else 'in'} {y}" for y, v in years.items()]
    line = (f"خلال هذه الفترة استهلك الحرم حوالي **{_hn(total, 'kWh', ar)}**: {_join_ar(ys)}" if ar else
            f"Over that time the campus used about **{_hn(total, 'kWh', ar)}**: {_join_en(ys)}")
    if len(years) == 2 and years.iloc[0]:
        diff = (years.iloc[1] - years.iloc[0]) / years.iloc[0] * 100
        line += (f"، أي أن السنة الثانية كانت {_change_word(diff, ar)}" if ar else
                 f", so the second year was {_change_word(diff, ar)}")
    out.append(line + ".")
    bt = r.groupby("building_id")["energy"].sum().sort_values(ascending=False)
    out.append((f"{_hbuilding(bt.index[0], ar)} وحده مسؤول عن حوالي {_hpct(bt.iloc[0] / total * 100)} من الاستهلاك." if ar else
                _sent(f"{_hbuilding(bt.index[0], ar)} alone accounts for about {_hpct(bt.iloc[0] / total * 100)} of it.")))
    out.append((f"كما تحتوي على {len(data.events):,} حدث تنبؤ و{len(data.anomalies)} حالات شذوذ موسومة "
                f"و{len(data.verification):,} إجراء تم التحقق من نتائجه. المصدر: Building Data Genome 2 (موقع Robin)." if ar else
                f"It also holds {len(data.events):,} prediction events, {len(data.anomalies)} labelled anomalies and "
                f"{len(data.verification):,} verified actions. Source: Building Data Genome 2 (Robin site)."))
    return out


STORIES = {"summary": _story_summary, "rank": _story_rank, "events": _story_events, "actions": _story_actions,
           "forecast": _story_forecast, "overview": _story_overview}


# =========================================================
# PUBLIC API
# =========================================================


def answer(question: str, data: ProjectData = project_data) -> Optional[Dict[str, Any]]:
    """
    Returns None when the question is not about project data. Otherwise:
        {
          "intent": str,
          "answer": str,          # deterministic, same language as the question
          "facts": [str, ...],    # every computed figure, one per line
          "source": {...}         # for the UI source list
        }
    """
    try:
        plan = plan_question(question, data)
    except Exception:  # noqa: BLE001 - a parsing bug must never break the knowledge page
        return None
    if plan is None:
        return None
    if data.readings is None or data.readings.empty:
        return {"intent": "error", "answer": data.error or "No data", "facts": [], "source": None,
                "plan": {}}
    ar = plan.arabic
    rng = f"{data.first:%Y-%m-%d} → {data.last:%Y-%m-%d}"

    if plan.notes and not plan.periods:
        msg = (f"لا توجد بيانات للفترة المطلوبة ({', '.join(plan.notes)}). البيانات المتوفرة تغطي {rng} فقط." if ar else
               f"There is no data for {', '.join(plan.notes)}. The dataset covers {rng} only.")
        human = (f"لا توجد بيانات لهذه الفترة ({', '.join(plan.notes)}).\n"
                 f"البيانات المتوفرة تبدأ في {_hdate(data.first, ar, False)} وتنتهي في {_hdate(data.last, ar, False)}، "
                 f"فجرّب السؤال عن تاريخ ضمن هذه الفترة، مثلاً: «كم كان استهلاك الطاقة يوم 5/7/2016؟»" if ar else
                 f"There is no data for {', '.join(plan.notes)}.\n"
                 f"The dataset starts on {_hdate(data.first, ar, False)} and ends on {_hdate(data.last, ar, False)}, "
                 f"so try a date inside that range — for example, \"What was the energy consumption on 5 July 2016?\"")
        return {"intent": "out_of_range", "answer": human, "headline": msg, "facts": [msg],
                "source": _source(plan, data, [msg]), "plan": _plan_dict(plan)}

    if plan.intent == "relative":
        last_day = _day_period(data.last.normalize())
        plan.periods = [last_day]
        plan.intent = "summary"
        result = _summary(plan, data)
        note = (f"ملاحظة: البيانات تاريخية ({rng})، فلا يوجد \"اليوم\" أو \"أمس\" فيها. هذه أرقام آخر يوم متوفر." if ar else
                f"Note: the dataset is historical ({rng}), so there is no \"today\" or \"yesterday\" in it. "
                f"These are the figures for the last available day.")
        result["headline"].insert(0, note)
        story = [("ملاحظة: البيانات تاريخية (من 2016 إلى 2017)، لذلك لا يوجد فيها «اليوم» أو «أمس». "
                  "هذه أرقام آخر يوم متوفر:" if ar else
                  "Note: the data is historical (2016 to 2017), so there is no \"today\" or \"yesterday\" in it. "
                  "Here are the figures for the last day available:")]
        story += _safe_story(plan, data)
    else:
        result = {"summary": _summary, "rank": _rank, "events": _events, "actions": _actions,
                  "forecast": _forecast, "overview": _overview}[plan.intent](plan, data)
        story = _safe_story(plan, data)

    if plan.notes:
        result["facts"].append((f"خارج نطاق البيانات ({rng}): {', '.join(plan.notes)}") if ar else
                               (f"Outside the dataset ({rng}): {', '.join(plan.notes)}"))
    headline = result["headline"]
    short = "\n".join(headline)
    text = ("\n".join(story) if story else short) or ("لم أجد بيانات مطابقة." if ar else "No matching data found.")
    return {
        "intent": plan.intent,
        "answer": text,             # plain-language answer, shown first
        "headline": short,          # the exact one-line result(s)
        "facts": result["facts"],
        "source": _source(plan, data, headline or result["facts"][:2]),
        "plan": _plan_dict(plan),
    }


def _safe_story(plan: Plan, data: ProjectData) -> List[str]:
    """Plain-language paragraphs; falls back to the one-line headline if anything goes wrong."""
    try:
        return [x for x in STORIES[plan.intent](plan, data) if x]
    except Exception:  # noqa: BLE001 - the exact facts are still returned
        return []


def _plan_dict(plan: Plan) -> Dict[str, Any]:
    return {
        "intent": plan.intent,
        "metrics": plan.metrics,
        "buildings": plan.buildings or ["CAMPUS"],
        "periods": [{"start": f"{p.start:%Y-%m-%d %H:%M}", "end": f"{p.end:%Y-%m-%d %H:%M}", "kind": p.kind}
                    for p in plan.periods],
        "hour": plan.hour,
        "rank_unit": plan.rank_unit,
        "rank_dir": plan.rank_dir,
    }


def _source(plan: Plan, data: ProjectData, lines: List[str]) -> Dict[str, Any]:
    tables = sorted({{"readings": "energy.db · energy_readings", "battery": "battery_readings.csv",
                      "weather": "weather_data.csv", "grid": "grid_signals.csv"}[METRICS[m]["src"]]
                     for m in plan.metrics})
    extra = {"events": ["prediction_events.csv", "anomaly_labels.csv"],
             "actions": ["optimized_actions.csv", "verification_results.csv"],
             "forecast": ["energy_forecast_results.csv"]}.get(plan.intent, [])
    excerpt = " ".join(lines)
    return {
        "ref": "D",
        "document": ", ".join(tables + extra),
        "title": "Project data (computed from the dataset)",
        "section": ", ".join(METRICS[m]["en"] for m in plan.metrics),
        "score": None,
        "excerpt": excerpt[:400],
        "kind": "data",
    }


def status(data: ProjectData = project_data) -> Dict[str, Any]:
    data.ensure()
    if data.readings is None or data.readings.empty:
        return {"available": False, "error": data.error}
    return {"available": True, "rows": int(len(data.readings)),
            "from": f"{data.first:%Y-%m-%d}", "to": f"{data.last:%Y-%m-%d}"}


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "What was the energy consumption on 2016-07-01?"
    print(json.dumps(answer(q), indent=2, ensure_ascii=False, default=str))
