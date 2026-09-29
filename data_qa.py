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
                                                and not re.search(r"(?<!\w)(اي|ايش|شو|اكثر|اعلى|اقل)\s*يوم", t))

    # Rank questions: "which day...", "أي يوم ..."
    rank_unit = None
    m = re.search(r"\b(?:which|what)\s+(day|date|month|hour|time of day|time|building|year|week)", t) or \
        re.search(r"\btop\s+\d*\s*(days?|months?|hours?|buildings?)", t) or \
        re.search(r"\b(?:highest|lowest|busiest|quietest|peak|most|least)\s+(day|month|hour|building|year)", t) or \
        re.search(r"(?<!\w)(?:اي|ايش|شو|ما هو|ما هي|انهي|وين)\s*(?:هو\s*|هي\s*)?(ال)?(يوم|تاريخ|شهر|ساعه|مبنى|المبنى|سنه)", t) or \
        re.search(r"(?<!\w)(?:اكثر|اعلى|اقل|ادنى)\s*(ال)?(يوم|شهر|ساعه|مبنى|سنه)", t)
    if m:
        word = m.group(m.lastindex or 1) or ""
        word = word.rstrip("s")
        rank_unit = {"date": "day", "time": "hour", "time of day": "hour", "week": "day",
                     "يوم": "day", "تاريخ": "day", "شهر": "month", "ساعه": "hour", "مبنى": "building",
                     "المبنى": "building", "سنه": "year"}.get(word, word)
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
        or (is_action and quant)
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

    top = re.search(r"\btop\s+(\d{1,2})\b|(?<!\w)(?:اعلى|اكثر|اقل|ادنى)\s+(\d{1,2})(?!\d)", t)
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
        return {"intent": "out_of_range", "answer": msg, "facts": [msg], "source": _source(plan, data, [msg]),
                "plan": _plan_dict(plan)}

    if plan.intent == "relative":
        last_day = _day_period(data.last.normalize())
        plan.periods = [last_day]
        plan.intent = "summary"
        result = _summary(plan, data)
        note = (f"ملاحظة: البيانات تاريخية ({rng})، فلا يوجد \"اليوم\" أو \"أمس\" فيها. هذه أرقام آخر يوم متوفر." if ar else
                f"Note: the dataset is historical ({rng}), so there is no \"today\" or \"yesterday\" in it. "
                f"These are the figures for the last available day.")
        result["headline"].insert(0, note)
    else:
        result = {"summary": _summary, "rank": _rank, "events": _events, "actions": _actions,
                  "forecast": _forecast, "overview": _overview}[plan.intent](plan, data)

    if plan.notes:
        result["facts"].append((f"خارج نطاق البيانات ({rng}): {', '.join(plan.notes)}") if ar else
                               (f"Outside the dataset ({rng}): {', '.join(plan.notes)}"))
    headline = result["headline"]
    text = ("\n".join(headline) if headline else
            ("لم أجد بيانات مطابقة." if ar else "No matching data found."))
    return {
        "intent": plan.intent,
        "answer": text,
        "facts": result["facts"],
        "source": _source(plan, data, headline or result["facts"][:2]),
        "plan": _plan_dict(plan),
    }


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
