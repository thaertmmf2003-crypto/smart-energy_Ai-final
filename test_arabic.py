"""
test_arabic.py - the AI Knowledge assistant understands Arabic (formal and
Levantine dialect) and answers in Arabic, with no language model configured.

Run:
    python test_arabic.py
"""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("RAG_LLM_PROVIDER", "none")      # test the offline path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag_service import rag_service  # noqa: E402

AR = re.compile(r"[؀-ۿ]")
results = []


def check(q, mode, must=(), doc=None):
    r = rag_service.query(q)
    ans = r["answer"]
    ok = r["mode"] == mode and bool(AR.search(ans)) and all(m in ans for m in must)
    if doc:
        ok = ok and any(doc in (s.get("document") or "") for s in r["sources"])
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}]  {q}")
    if not ok:
        print(f"        mode={r['mode']} answer={ans[:160]}")


print("--- project data (numbers computed from energy.db) ---")
check("كم كان استهلاك الطاقة يوم 5/7/2016؟", "data", ["10,117.0"])
check("قديش صرف مبنى الادارة يوم 3/3/2017", "data", ["1,648.5", "الإدارة"])
check("شو كان استهلاك المختبرات بشهر 7 سنة 2016", "data", ["183,183.6"])
check("ايش أعلى يوم استهلاك بسنة 2017", "data", ["2017-01-18"])
check("أي مبنى استهلك أكثر في 2017؟", "data", ["B002"])
check("أقل شهر توليد شمسي في 2016", "data", ["2016-12"])
check("كم كانت الطاقة الشمسية يوم 15 حزيران 2017 الساعة 12 الظهر", "data", ["263.2"])
check("كم عدد الاحداث في آب 2017", "data", ["23"])
check("شو نسبة نجاح الاجراءات", "data", ["81.9%"])

print("\n--- concepts (answered from the Arabic documents) ---")
check("كيف يعمل التحقق وإعادة التخطيط؟", "extractive", ["إعادة التخطيط"], "smart_energy_ai_operating_policy.md")
check("ما هو سير عمل الوكيل في هذا المشروع؟", "extractive", ["إحدى عشرة مرحلة"])
check("ما هي الإجراءات التي يحاكيها التوأم الرقمي؟", "extractive", ["تعديل ضبط التكييف", "الإجراء المركّب"])
check("ليش بنستخدم البطارية وقت الذروة؟", "extractive", ["الذروة"], "battery_and_ev_flexibility.md")
check("شو الفرق بين الطاقة والطلب؟", "extractive", ["معدل الاستخدام اللحظي"])
check("شو اسباب ضعف أداء الألواح الشمسية؟", "extractive", ["الغبار"])
check("لماذا يؤدي تخفيض التكييف إلى تخفيض الاستهلاك؟", "extractive", ["الضواغط"])
check("ايمتى بيوقف الوكيل وبيستنى موافقة؟", "extractive", ["بانتظار الموافقة"])

print("\n--- boundaries ---")
check("كم كان استهلاك الطاقة يوم 2020-01-01؟", "data", ["لا توجد بيانات"])

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
