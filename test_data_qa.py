"""
test_data_qa.py - checks that the AI Knowledge page answers data questions
with the right numbers.

Every expected value is recomputed here straight from data/processed/*.csv,
independently of data_qa.py, so a wrong figure fails the test.

Run:
    python test_data_qa.py
"""

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import data_qa  # noqa: E402
from rag_service import rag_service  # noqa: E402

P = Path(__file__).resolve().parent / "data" / "processed"
results = []


def check(label, cond, detail=""):
    cond = bool(cond)
    results.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}]  {label}" + (f"\n        {detail}" if detail and not cond else ""))


def num(text, value, digits=1):
    """True when `value`, formatted like the answers, appears in `text`."""
    return f"{value:,.{digits}f}" in text


energy = pd.read_csv(P / "energy_readings.csv", parse_dates=["timestamp"])
solar = pd.read_csv(P / "solar_readings.csv", parse_dates=["timestamp"])
events = pd.read_csv(P / "prediction_events.csv", parse_dates=["timestamp"])
ver = pd.read_csv(P / "verification_results.csv")


def day(df, d, col="energy", b=None):
    x = df[df["timestamp"].dt.strftime("%Y-%m-%d") == d]
    if b:
        x = x[x["building_id"] == b]
    return x[col].sum()


print("\n--- dataset consistency ---")
r = data_qa.project_data
r.ensure()
check("energy.db matches energy_readings.csv",
      abs(r.readings["energy"].sum() - energy["energy"].sum()) < 1e-6 * energy["energy"].sum())

print("\n--- daily totals (English and Arabic, several date formats) ---")
for q, d, b in [
    ("What was the energy consumption on 2016-07-01?", "2016-07-01", None),
    ("كم كان استهلاك الطاقة يوم 5/7/2016؟", "2016-07-05", None),
    ("كم كان استهلاك الطاقة في اليوم 1 تموز 2016", "2016-07-01", None),
    ("How much energy did the Labs use on March 3, 2017?", "2017-03-03", "B002"),
    ("كم استهلك مبنى الإدارة بتاريخ 2017/1/18", "2017-01-18", "B001"),
    ("energy used by classrooms on 12th of August 2017", "2017-08-12", "B003"),
]:
    a = data_qa.answer(q)
    exp = day(energy, d, b=b)
    check(f"{q}  →  {exp:,.1f} kWh", a is not None and num(a["answer"], exp), a and a["answer"])

print("\n--- single hour ---")
a = data_qa.answer("What was the load at 16:00 on 2016-06-10")
exp = energy[energy["timestamp"] == "2016-06-10 16:00:00"]["energy"].sum()
check(f"campus load 2016-06-10 16:00 = {exp:,.1f}", a and num(a["answer"], exp), a and a["answer"])
a = data_qa.answer("What was the solar generation of B001 on 15/3/2017 at 2 pm?")
exp = solar[(solar["timestamp"] == "2017-03-15 14:00:00") & (solar["building_id"] == "B001")]["solar_generation_kw"].sum()
check(f"B001 solar 2017-03-15 14:00 = {exp:,.1f}", a and num(a["answer"], exp), a and a["answer"])

print("\n--- month, year, range ---")
a = data_qa.answer("How much did the Labs consume in July 2017?")
x = energy[(energy["timestamp"].dt.strftime("%Y-%m") == "2017-07") & (energy["building_id"] == "B002")]["energy"].sum()
check(f"Labs July 2017 = {x:,.1f}", a and num(a["answer"], x), a and a["answer"])
a = data_qa.answer("consumption between 2016-07-01 and 2016-07-07")
x = energy[(energy["timestamp"] >= "2016-07-01") & (energy["timestamp"] < "2016-07-08")]["energy"].sum()
check(f"range 1-7 July 2016 = {x:,.1f}", a and num(a["answer"], x), a and a["answer"])

print("\n--- rankings ---")
daily = energy.groupby(energy["timestamp"].dt.date)["energy"].sum()
d2017 = daily[[d.year == 2017 for d in daily.index]]
top = d2017.idxmax()
for q in ["Which day had the highest consumption in 2017?", "أي يوم كان فيه أعلى استهلاك في 2017؟"]:
    a = data_qa.answer(q)
    check(f"{q}  →  {top}", a and str(top) in a["answer"] and num(a["answer"], d2017.max()), a and a["answer"])
low = d2017.idxmin()
a = data_qa.answer("Which day had the lowest consumption in 2017?")
check(f"lowest day 2017 → {low}", a and str(low) in a["answer"], a and a["answer"])
b = energy[energy["timestamp"].dt.year == 2017].groupby("building_id")["energy"].sum().idxmax()
a = data_qa.answer("Which building consumed the most energy in 2017?")
check(f"top building 2017 → {b}", a and b in a["answer"], a and a["answer"])

print("\n--- events and actions ---")
a = data_qa.answer("Were there any anomalies on 1 July 2016?")
check("anomaly on 2016-07-01 found", a and "ENERGY_ANOMALY" in " ".join(a["facts"]))
n = int((events["timestamp"].dt.strftime("%Y-%m") == "2017-08").sum())
a = data_qa.answer("How many events were there in August 2017?")
check(f"events in August 2017 = {n}", a and re.search(rf"\b{n}\b", a["answer"]) is not None, a and a["answer"])
rate = (ver["verification_status"] == "SUCCESS").mean() * 100
a = data_qa.answer("What was the action success rate?")
check(f"success rate = {rate:.1f}%", a and f"{rate:.1f}%" in a["answer"], a and a["answer"])

print("\n--- boundaries ---")
a = data_qa.answer("What was the energy consumption on 2020-01-01?")
check("date outside the dataset is reported, not invented", a and a["intent"] == "out_of_range")
for q in ["Why does reducing HVAC load lower total building energy demand?",
          "How can batteries reduce peak demand?", "What is the agentic workflow in this project?",
          "How does verification trigger replanning?"]:
    check(f"conceptual question goes to documents: {q}", data_qa.answer(q) is None)

print("\n--- through the RAG service ---")
res = rag_service.query("What was the energy consumption on 2016-07-01?")
check("RAG returns data answer with [D] source",
      res["mode"] in {"data", "llm"} and res["sources"] and res["sources"][0]["ref"] == "D" and res["data"])
res = rag_service.query("كيف يعمل التحقق وإعادة التخطيط؟")
check("Arabic conceptual question retrieves documents", res["mode"] != "no_match" and res["sources"])

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
