/*
 * Smart Energy AI — Arabic translation layer for the whole interface.
 *
 * The data-i18n system in i18n_theme.js only covers elements that carry a
 * data-i18n key, and most pages (and everything rendered by app.js) had none.
 * This layer translates every text node, placeholder, title and aria-label on
 * the page, including text that app.js writes later (a MutationObserver keeps
 * watching). Switching back to English restores the original text.
 *
 *   AR       exact strings (matched case-insensitively, whitespace-normalised)
 *   PATTERNS dynamic sentences with numbers / names
 *   Composite text joined with " · " is translated part by part.
 *
 * Numbers, units (kW, kWh, JOD), building codes and timestamps stay as they are.
 * Elements inside [data-no-i18n] or with their own data-i18n key are skipped.
 */
(function () {
  "use strict";

  const AR = {
    // ---------- shell / navigation ----------
    "online": "متصل", "offline": "غير متصل", "degraded": "أداء منخفض",
    "overview": "نظرة عامة", "energy monitor": "مراقبة الطاقة", "ai operations": "عمليات الذكاء الاصطناعي",
    "digital twin": "التوأم الرقمي", "verification": "التحقق", "ai knowledge": "المعرفة الذكية",
    "activity log": "سجل النشاط", "admin control center": "مركز التحكم الإداري", "admin panel": "لوحة الإدارة",
    "my profile": "ملفي الشخصي", "sign out": "تسجيل الخروج", "user profile": "الملف الشخصي",
    "open menu": "فتح القائمة", "toggle theme": "تبديل النمط", "toggle language": "تبديل اللغة",
    "color theme": "ثيم الألوان", "switch to light mode": "التبديل إلى النمط الفاتح", "switch to dark mode": "التبديل إلى النمط الداكن",
    "switch to english": "التبديل إلى الإنجليزية", "show/hide password": "إظهار/إخفاء كلمة المرور",
    "smart energy ai": "Smart Energy AI", "operational loop": "دورة التشغيل",
    "mock data": "بيانات تجريبية", "live": "مباشر", "dark": "داكن", "light": "فاتح",
    "luxury gold": "ذهبي فاخر", "midnight navy": "كحلي ليلي", "emerald energy": "زمردي طاقة", "ocean teal": "فيروزي",
    "royal indigo": "نيلي ملكي", "arctic blue": "أزرق قطبي", "solar amber": "كهرماني شمسي", "graphite mono": "جرافيت أحادي",
    "crimson rose": "قرمزي وردي",

    // ---------- common words ----------
    "yes": "نعم", "no": "لا", "ok": "سليم", "available": "متاح", "unavailable": "غير متاح", "hide": "إخفاء",
    "loading…": "جارٍ التحميل…", "loading...": "جارٍ التحميل…", "source:": "المصدر:", "status": "الحالة",
    "state": "الحالة", "event": "الحدث", "action": "الإجراء", "expected": "المتوقع", "achieved": "المحقّق",
    "reached": "النسبة المحققة", "target": "الهدف", "reduction": "التخفيض", "score": "النتيجة", "this": "هذا",
    "selected": "المختار", "mode": "الوضع", "approval": "الموافقة", "ml": "التعلم الآلي", "rag": "RAG",
    "consumption": "الاستهلاك", "solar": "الطاقة الشمسية", "hvac": "التكييف", "energy": "الطاقة", "occupancy": "الإشغال",
    "temperature": "درجة الحرارة", "humidity": "الرطوبة", "solar irradiance": "الإشعاع الشمسي", "wind speed": "سرعة الرياح",
    "relative humidity": "الرطوبة النسبية", "data source": "مصدر البيانات", "retrieved": "وقت الجلب",
    "when": "الوقت", "building": "المبنى", "kind": "النوع", "severity": "الخطورة", "measure": "القياس",
    "administration": "الإدارة", "labs": "المختبرات", "classrooms": "القاعات الدراسية", "campus-wide": "الحرم كامل",
    "campus": "الحرم", "b001 administration": "B001 الإدارة", "b002 labs": "B002 المختبرات", "b003 classrooms": "B003 القاعات الدراسية",
    "energy anomaly": "شذوذ طاقة", "solar underperformance": "ضعف أداء شمسي", "peak demand risk": "خطر ذروة الطلب", "peak-demand risk": "خطر ذروة الطلب",
    "high": "مرتفع", "elevated": "متوسط", "critical": "حرج", "normal": "طبيعي", "not actionable": "غير قابل للإجراء",
    "pending": "قيد الانتظار", "approved": "موافَق عليه", "rejected": "مرفوض", "success": "نجاح",
    "underperformed": "أداء دون الهدف", "failed": "فشل", "completed": "مكتمل",
    "energy kw": "الطاقة kW", "hvac kw": "التكييف kW", "solar kw": "الشمسية kW", "ev kw": "السيارات kW",

    // ---------- agent states ----------
    "monitoring": "المراقبة", "investigating": "التحقيق", "gathering evidence": "جمع الأدلة", "evidence": "الأدلة",
    "analyzing": "التحليل", "forecasting": "التنبؤ", "forecast": "التنبؤ", "simulating": "المحاكاة",
    "validating": "التحقق من الصلاحية", "waiting for approval": "بانتظار الموافقة", "executing": "التنفيذ",
    "execute": "التنفيذ", "verifying": "التحقق", "verify": "التحقق", "replanning": "إعادة التخطيط",
    "complete": "الاكتمال", "human gate": "الموافقة البشرية", "rejected · waiting": "مرفوض · بانتظار القرار",

    // ---------- actions ----------
    "combined hvac, ev and battery action": "إجراء مركّب: تكييف وسيارات وبطارية",
    "shift ev charging": "إزاحة شحن السيارات", "hvac setpoint adjustment": "تعديل ضبط التكييف",
    "battery discharge": "تفريغ البطارية", "combined action": "إجراء مركّب", "ev charging shift": "إزاحة شحن السيارات",
    "hvac setpoint cut": "خفض ضبط التكييف", "combined_action": "الإجراء المركّب", "battery_discharge": "تفريغ البطارية",
    "ev_charging_shift": "إزاحة شحن السيارات", "hvac_setpoint_adjustment": "تعديل ضبط التكييف",
    "apply a coordinated simulated hvac, ev charging and battery action.": "تطبيق إجراء محاكى منسّق للتكييف وشحن السيارات والبطارية.",

    // ---------- overview ----------
    "autonomous energy intelligence": "ذكاء الطاقة الذاتي", "from anomaly to": "من الشذوذ إلى", "verified action.": "إجراء موثَّق.",
    "the agent continuously connects energy data, ml predictions, digital-twin simulations and human approval into one operational loop.":
      "يربط الوكيل باستمرار بيانات الطاقة وتنبؤات التعلم الآلي ومحاكاة التوأم الرقمي والموافقة البشرية في دورة تشغيل واحدة.",
    "open ai operations": "فتح عمليات الذكاء الاصطناعي", "watch the agent decide": "شاهد الوكيل يتخذ القرار",
    "sense": "الرصد", "decide": "القرار", "approve": "الموافقة", "ml detects the event": "التعلم الآلي يكتشف الحدث",
    "digital twin + optimizer": "التوأم الرقمي + المُحسِّن", "human in the loop": "الإنسان ضمن الحلقة", "measured outcome": "نتيجة مقاسة",
    "live simulation": "محاكاة مباشرة", "● live simulation": "● محاكاة مباشرة", "operational time": "وقت التشغيل", "operational time:": "وقت التشغيل:",
    "updated": "آخر تحديث قبل", "s ago · stream every 5 s": "ث · تحديث كل 5 ث", "s ago": "ث",
    "est. reduction": "التخفيض المقدّر", "run an analysis first": "شغّل التحليل أولاً", "cost avoided": "التكلفة الموفّرة",
    "co₂ avoided": "CO₂ المتجنّب", "digital twin simulation ·": "محاكاة التوأم الرقمي ·", "current load": "الحمل الحالي",
    "kw · live simulated demand": "kW · الطلب المحاكى المباشر", "historical profile + simulation": "ملف تاريخي + محاكاة",
    "solar generation": "توليد الطاقة الشمسية", "kw · renewable supply": "kW · إمداد متجدد", "pv model + nasa power": "نموذج PV + NASA POWER",
    "anomalies detected": "الحالات الشاذة المكتشفة", "what are they?": "ما هي؟", "existing anomaly detection": "كشف الشذوذ الحالي",
    "events in current dataset": "أحداث في البيانات الحالية", "achieved in verification": "محقّق في التحقق",
    "what the detector flagged": "ما رصده الكاشف", "energy anomalies": "حالات شذوذ الطاقة", "peak-demand risks": "مخاطر ذروة الطلب", "both": "الاثنان",
    "an": "", "is an hour where a building's measured load differed from the forecast by 25% or more. the measure column shows that gap: −30% means the building drew 30% less than expected. severity is high from 50% upward, elevated below it. a":
      "هي ساعة اختلف فيها حمل المبنى المقاس عن التنبؤ بنسبة 25% أو أكثر. عمود القياس يعرض هذا الفرق: −30% تعني أن المبنى استهلك أقل بـ 30% من المتوقع. الخطورة «مرتفع» من 50% فأكثر و«متوسط» دون ذلك. أما",
    "is a different thing entirely: the campus total climbing toward the 850 kw grid limit, and its measure is the share of that limit reached.":
      "فشيء مختلف تماماً: اقتراب إجمالي الحرم من حد الشبكة البالغ 850 kW، وقياسه هو النسبة المبلوغة من ذلك الحد.",
    "energy signal": "إشارة الطاقة", "48-hour operating profile": "ملف التشغيل لآخر 48 ساعة", "full monitor →": "المراقبة الكاملة ←",
    "agent status": "حالة الوكيل", "no active event.": "لا يوجد حدث نشط.", "no approval gate active": "لا توجد بوابة موافقة نشطة",
    "human approval required": "مطلوب موافقة بشرية", "human approval required.": "مطلوب موافقة بشرية.",
    "inspect agent lifecycle": "عرض دورة حياة الوكيل", "recent events": "أحدث الأحداث", "operational signals": "إشارات التشغيل",
    "analyze": "تحليل", "no simulation": "لا توجد محاكاة", "show less": "عرض أقل",
    "environmental conditions": "الظروف البيئية", "nasa power weather": "طقس NASA POWER",
    "nasa power (climatological fallback)": "NASA POWER (بديل مناخي)", "nasa observation (utc)": "رصد NASA (UTC)",
    "jordan local (asia/amman)": "توقيت الأردن (عمّان)", "system health": "صحة النظام", "runtime services": "خدمات التشغيل",
    "database": "قاعدة البيانات", "ml service": "خدمة التعلم الآلي", "optimizer": "المُحسِّن",
    "extractive, no language model configured": "استخراجي، بدون نموذج لغوي", "stream unavailable": "البث غير متاح",

    // ---------- operations ----------
    "autonomous reasoning with a human gate.": "استدلال ذاتي مع بوابة موافقة بشرية.",
    "run an event through detection, evidence gathering, forecasting, simulation, approval and verification.":
      "مرّر حدثاً عبر الكشف وجمع الأدلة والتنبؤ والمحاكاة والموافقة والتحقق.",
    "demo path": "مسار العرض", "any available event": "أي حدث متاح", "event that verifies": "حدث ينجح في التحقق",
    "event that needs replanning": "حدث يحتاج إعادة تخطيط", "run ai analysis": "تشغيل تحليل الذكاء الاصطناعي",
    "01 · what happened": "01 · ما الذي حدث", "no active event": "لا يوجد حدث نشط", "02 · what the agent checked": "02 · ما الذي فحصه الوكيل",
    "operational evidence": "الأدلة التشغيلية", "historical readings": "القراءات التاريخية", "grid status": "حالة الشبكة",
    "average across buildings": "متوسط المباني", "03 · what the digital twin simulated": "03 · ما حاكاه التوأم الرقمي",
    "candidate actions": "الإجراءات المرشّحة", "go to digital twin →": "الذهاب إلى التوأم الرقمي ←",
    "no candidate actions available. run an analysis first.": "لا توجد إجراءات مرشّحة. شغّل التحليل أولاً.",
    "estimated reduction of at least 1 kw": "تخفيض مقدّر لا يقل عن 1 kW",
    "battery and combined actions need battery soc above 30%": "إجراءات البطارية والمركّبة تتطلب شحن بطارية فوق 30%",
    "ev and combined actions need active ev charging load": "إجراءات السيارات والمركّبة تتطلب شحناً فعلياً للسيارات",
    "04 · ai recommendation": "04 · توصية الذكاء الاصطناعي", "waiting for simulation results.": "بانتظار نتائج المحاكاة.",
    "explain forecast": "شرح التنبؤ", "download pdf report": "تنزيل تقرير PDF", "ml explanation": "شرح التعلم الآلي",
    "why did the model forecast this?": "لماذا تنبأ النموذج بهذا؟",
    "lime fits a local surrogate around this single prediction. it explains the forecasting model's reasoning, not the real-world cause of the event.":
      "يبني LIME نموذجاً بديلاً محلياً حول هذا التنبؤ فقط. هو يشرح منطق نموذج التنبؤ، لا السبب الواقعي للحدث.",
    "run an analysis, then explain its forecast.": "شغّل التحليل ثم اشرح تنبؤه.",
    "fitting a local surrogate around this prediction…": "جارٍ بناء نموذج بديل محلي حول هذا التنبؤ…",
    "05 · your decision": "05 · قرارك", "reject": "رفض", "view verification": "عرض التحقق",
    "the agent will stop before execution and request human approval.": "سيتوقف الوكيل قبل التنفيذ ويطلب موافقة بشرية.",
    "recommended": "موصى به", "passes constraints": "يجتاز القيود", "fails constraints": "لا يجتاز القيود", "missed target": "لم يحقق الهدف",
    "why was it chosen?": "لماذا اختير؟", "why wasn't it chosen?": "لماذا لم يُختر؟", "why was it rejected?": "لماذا رُفض؟",
    "passed constraints, lower score": "اجتاز القيود، بنتيجة أقل", "rejected after verification": "رُفض بعد التحقق",
    "not selected during replanning": "لم يُختر أثناء إعادة التخطيط", "from optimizer": "من المُحسِّن",
    "alternative after replanning": "بديل بعد إعادة التخطيط", "it passed every optimizer constraint.": "اجتاز جميع قيود المُحسِّن.",
    "not applicable: action does not use the battery": "غير منطبق: الإجراء لا يستخدم البطارية",
    "not applicable: action does not shift ev charging": "غير منطبق: الإجراء لا يزيح شحن السيارات",
    "reduction × weight": "التخفيض × الوزن", "disruption rank × penalty": "درجة الإزعاج × الجزاء",
    "optimizer.py score and constraints": "نتيجة وقيود optimizer.py", "optimizer.py score": "نتيجة optimizer.py",
    "agent.py replanning rule": "قاعدة إعادة التخطيط في agent.py",
    "verification.py threshold and agent.py replanning rule": "عتبة verification.py وقاعدة إعادة التخطيط في agent.py",
    "it is also the candidate with the largest simulated reduction.": "وهو أيضاً المرشّح صاحب أكبر تخفيض محاكى.",
    "you approved it and it ran as a simulated execution.": "وافقتَ عليه ونُفّذ تنفيذاً محاكى.",
    "after the previous action missed its target, the agent picks the untried candidate with the largest estimated reduction that passes the optimizer's constraints.":
      "بعد أن أخفق الإجراء السابق في بلوغ هدفه، يختار الوكيل المرشّح غير المجرَّب صاحب أكبر تخفيض مقدّر والذي يجتاز قيود المُحسِّن.",
    "replanning picks the untried candidate with the largest estimated reduction that passes the optimizer's constraints.":
      "إعادة التخطيط تختار المرشّح غير المجرَّب صاحب أكبر تخفيض مقدّر والذي يجتاز قيود المُحسِّن.",
    "among the untried candidates that pass the optimizer's constraints, this one has the largest estimated reduction (the agent's replanning rule).":
      "من بين المرشّحين غير المجرَّبين الذين يجتازون قيود المُحسِّن، هذا صاحب أكبر تخفيض مقدّر (قاعدة إعادة التخطيط لدى الوكيل).",
    "the target is 80% or more, so verification marked it underperformed and the agent excluded it when replanning.":
      "الهدف 80% أو أكثر، لذا صنّفه التحقق «دون الهدف» واستبعده الوكيل عند إعادة التخطيط.",
    "predicted campus demand is approaching the simulated grid import limit.": "الطلب المتوقع للحرم يقترب من حد الاستيراد المحاكى من الشبكة.",
    "forecast demand vs. grid import limit (%)": "الطلب المتوقع مقابل حد الاستيراد من الشبكة (%)",
    "readings at the event hour (—). history covers the 24 hours up to the event.": "القراءات عند ساعة الحدث (—). السجل يغطي 24 ساعة حتى الحدث.",
    "review the replanning decision": "مراجعة قرار إعادة التخطيط", "the proposal is still waiting in the decision panel.": "المقترح ما زال بانتظار قرارك في لوحة القرار.",
    "analysis complete. human approval required.": "اكتمل التحليل. مطلوب موافقة بشرية.", "analysis completed.": "اكتمل التحليل.",
    "target not met. the agent proposes an alternative.": "لم يتحقق الهدف. الوكيل يقترح بديلاً.",
    "approved. simulated execution verified.": "تمت الموافقة. تم التحقق من التنفيذ المحاكى.", "rejected. nothing was executed.": "مرفوض. لم يُنفَّذ شيء.",
    "simulated execution in progress. no equipment is being controlled.": "التنفيذ المحاكى جارٍ. لا يتم التحكم بأي معدات.",
    "verification is comparing the simulated outcome with the expected target.": "التحقق يقارن النتيجة المحاكاة بالهدف المتوقع.",

    // ---------- replan dialog ----------
    "replanning · round": "إعادة التخطيط · الجولة", "the previous action missed its target": "الإجراء السابق لم يحقق هدفه",
    "the agent now proposes": "الوكيل يقترح الآن", "why did it fall short?": "لماذا لم يبلغ الهدف؟", "hide the reasons": "إخفاء الأسباب",
    "decide later": "القرار لاحقاً", "execution is simulated. nothing runs until you approve.": "التنفيذ محاكى. لا يعمل شيء حتى توافق.",
    "reading the conditions during that hour…": "جارٍ قراءة الظروف خلال تلك الساعة…",
    "battery did not discharge": "البطارية لم تُفرَّغ", "extra load appeared at the charging points": "ظهر حمل إضافي عند نقاط الشحن",
    "solar generation fell away": "انخفض توليد الطاقة الشمسية", "✓ hvac held to plan": "✓ التكييف التزم بالخطة",
    "hvac held to plan": "التكييف التزم بالخطة", "hvac did not follow the plan": "التكييف لم يلتزم بالخطة",

    // ---------- energy page ----------
    "see the operating signal before acting.": "اطّلع على إشارة التشغيل قبل اتخاذ أي إجراء.",
    "consumption, solar and hvac behavior across the selected building.": "سلوك الاستهلاك والطاقة الشمسية والتكييف في المبنى المختار.",
    "load": "الحمل", "historical profile · simulation": "ملف تاريخي · محاكاة", "pv model · nasa power": "نموذج PV · NASA POWER",
    "derived from load profile": "مشتق من ملف الحمل", "operational estimate": "تقدير تشغيلي", "grid import": "الاستيراد من الشبكة",
    "load minus solar": "الحمل ناقص الطاقة الشمسية", "live data window": "نافذة البيانات المباشرة",
    "energy behavior · last 48 hours": "سلوك الطاقة · آخر 48 ساعة", "event feed": "سجل الأحداث", "ml-detected signals": "إشارات رصدها التعلم الآلي",
    "reading guide": "دليل القراءة", "what the agent watches": "ما يراقبه الوكيل", "building electrical demand over time.": "الطلب الكهربائي للمبنى عبر الزمن.",
    "estimated photovoltaic generation.": "التوليد الكهروضوئي المقدّر.", "heating and cooling load contribution.": "مساهمة حمل التدفئة والتبريد.",
    "operational context for demand anomalies.": "سياق تشغيلي لحالات شذوذ الطلب.",
    "historical data explorer · read only": "مستكشف البيانات التاريخية · للقراءة فقط", "inspect past operational truth": "استعرض الحقيقة التشغيلية السابقة",
    "select any historical date and time from the dataset repository to query exact recorded energy profiles, weather parameters, and agent activity. this section queries past sqlite database records and is clearly separated from live operational data.":
      "اختر أي تاريخ ووقت من مستودع البيانات للاستعلام عن ملفات الطاقة المسجلة بدقة ومعطيات الطقس ونشاط الوكيل. هذا القسم يستعلم سجلات قاعدة بيانات SQLite السابقة، وهو منفصل تماماً عن البيانات التشغيلية المباشرة.",
    "historical database repository": "مستودع قاعدة البيانات التاريخية", "historical query selector": "محدد الاستعلام التاريخي",
    "choose date & time (dataset range:": "اختر التاريخ والوقت (نطاق البيانات:", "year": "السنة", "month": "الشهر", "day": "اليوم", "hour": "الساعة", "minute": "الدقيقة",
    "01 - jan": "01 - كانون الثاني", "02 - feb": "02 - شباط", "03 - mar": "03 - آذار", "04 - apr": "04 - نيسان", "05 - may": "05 - أيار",
    "06 - jun": "06 - حزيران", "07 - jul": "07 - تموز", "08 - aug": "08 - آب", "09 - sep": "09 - أيلول", "10 - oct": "10 - تشرين الأول",
    "11 - nov": "11 - تشرين الثاني", "12 - dec": "12 - كانون الأول",
    "view historical state": "عرض الحالة التاريخية", "✦ test event date": "✦ تاريخ حدث تجريبي", "historical observation:": "الرصد التاريخي:",
    "source: building data genome 2 / sqlite database (`energy_readings`)": "المصدر: Building Data Genome 2 / قاعدة بيانات SQLite (`energy_readings`)",
    "historical load": "الحمل التاريخي", "kw · recorded building demand": "kW · طلب المبنى المسجّل", "source: building data genome 2": "المصدر: Building Data Genome 2",
    "kw · pv output at observation": "kW · إنتاج PV وقت الرصد", "source: solar readings archive": "المصدر: أرشيف القراءات الشمسية",
    "hvac load": "حمل التكييف", "kw · cooling/thermal power": "kW · قدرة التبريد/الحرارة", "source: building hvac sensors": "المصدر: حساسات تكييف المبنى",
    "% · estimated building utilization": "% · الاستخدام المقدّر للمبنى", "source: occupancy log": "المصدر: سجل الإشغال",
    "historical time window (24 hours)": "النافذة الزمنية التاريخية (24 ساعة)", "recorded load profile & selected time indicator": "ملف الحمل المسجّل ومؤشر الوقت المختار",
    "▲ selected time": "▲ الوقت المختار", "marker": "علامة", "recorded incidents & anomalies": "الحوادث والشذوذ المسجّلة",
    "database events at selected date": "أحداث قاعدة البيانات في التاريخ المختار", "no recorded incidents at this historical timestamp.": "لا توجد حوادث مسجّلة في هذا الوقت التاريخي.",
    "historical weather record": "سجل الطقس التاريخي", "open-meteo historical archive": "أرشيف Open-Meteo التاريخي",
    "load known date with recorded peak demand incident (2017-08-11 16:00)": "تحميل تاريخ معروف فيه حادثة ذروة طلب مسجّلة (2017-08-11 16:00)",

    // ---------- digital twin ----------
    "test the intervention before touching the system.": "اختبر التدخل قبل المساس بالنظام.",
    "compare candidate actions using the simulation results produced by the agent lifecycle.": "قارن الإجراءات المرشّحة باستخدام نتائج المحاكاة الناتجة عن دورة حياة الوكيل.",
    "open current operation →": "فتح العملية الحالية ←", "simulation environment": "بيئة المحاكاة",
    "operational decisions are evaluated virtually first.": "القرارات التشغيلية تُقيَّم افتراضياً أولاً.",
    "the selected action is not sent to physical equipment. execution remains explicitly simulated for the demo.": "الإجراء المختار لا يُرسل إلى معدات فعلية. التنفيذ يبقى محاكى صراحةً لأغراض العرض.",
    "simulated": "محاكى", "scenario comparison": "مقارنة السيناريوهات", "what-if experiment": "تجربة «ماذا لو»",
    "try your own intervention": "جرّب تدخلك الخاص",
    "move the controls to test a mix of actions against the active event. the meter reacts live and compares your result with the agent's best solution.":
      "حرّك أدوات التحكم لتجربة مزيج من الإجراءات على الحدث النشط. المؤشر يتفاعل مباشرة ويقارن نتيجتك بأفضل حل لدى الوكيل.",
    "experiment only · not applied": "تجربة فقط · غير مطبّقة",
    "run an ai analysis (from ai operations) to load an event, then experiment here.": "شغّل تحليل الذكاء الاصطناعي (من عمليات الذكاء الاصطناعي) لتحميل حدث، ثم جرّب هنا.",
    "load reduction": "تخفيض الحمل", "your experiment": "تجربتك", "agent best (": "أفضل حل للوكيل (", "agent default 15% · from": "الافتراضي لدى الوكيل 15% · من",
    "kw hvac": "kW تكييف", "agent default 80% · from": "الافتراضي لدى الوكيل 80% · من", "kw ev load": "kW حمل السيارات",
    "max 25 kw · battery soc": "الحد الأقصى 25 kW · شحن البطارية", "match agent": "مطابقة الوكيل", "clear all": "مسح الكل",
    "total reduction": "إجمالي التخفيض", "new load": "الحمل الجديد", "bill saving": "توفير الفاتورة", "new predicted load": "الحمل المتوقع الجديد",
    "estimates from the same simulation math the agent uses. this experiment is never executed and never sent to equipment.":
      "تقديرات من نفس معادلات المحاكاة التي يستخدمها الوكيل. هذه التجربة لا تُنفَّذ ولا تُرسل إلى المعدات أبداً.",
    "model self-audit": "تدقيق ذاتي للنموذج", "holiday blind spot": "نقطة عمياء في العطل", "learned confidence": "ثقة مكتسبة",
    "track record by action": "السجل حسب الإجراء",
    "learned from recorded verification history. this is an additive confidence signal shown alongside the optimizer score; it does not change which action the agent selects.":
      "مستفاد من سجل التحقق. هذه إشارة ثقة إضافية تُعرض بجانب نتيجة المُحسِّن؛ ولا تغيّر الإجراء الذي يختاره الوكيل.",
    "add an is_holiday feature to the forecaster, or suppress anomaly flagging on known shutdown days, to stop the model from reporting an empty campus as a fault.":
      "أضف ميزة is_holiday إلى نموذج التنبؤ، أو أوقف الإبلاغ عن الشذوذ في أيام الإغلاق المعروفة، حتى لا يعتبر النموذج الحرم الفارغ عطلاً.",
    "selection logic": "منطق الاختيار", "how the agent chooses": "كيف يختار الوكيل", "safety constraints": "قيود السلامة",
    "reject unsafe or invalid actions.": "رفض الإجراءات غير الآمنة أو غير الصالحة.", "operational feasibility": "الجدوى التشغيلية",
    "check building and system limits.": "فحص حدود المبنى والنظام.", "estimated impact": "الأثر المقدّر",
    "compare predicted energy reduction.": "مقارنة تخفيض الطاقة المتوقع.", "human approval": "الموافقة البشرية",
    "require a decision before execution.": "اشتراط قرار قبل التنفيذ.", "current action": "الإجراء الحالي", "no action selected": "لم يُختر إجراء",
    "useful — matches or beats the agent": "مفيد — يساوي الوكيل أو يتفوق عليه", "close, but below the agent's best": "قريب، لكن دون أفضل حل للوكيل",
    "not enough on its own": "غير كافٍ وحده", "experiment running": "التجربة جارية", "adjust the controls to shed load.": "عدّل أدوات التحكم لخفض الحمل.",
    "no action selected ": "لم يُختر إجراء", "every control is at zero, so nothing changes.": "كل أدوات التحكم عند الصفر، فلا يتغير شيء.",
    "no agent benchmark yet": "لا يوجد معيار للوكيل بعد",
    "no active ev charging this hour — shifting ev load has no effect here.": "لا يوجد شحن سيارات فعلي في هذه الساعة — إزاحة حمل السيارات لا أثر لها هنا.",

    // ---------- verification ----------
    "close the loop with measured evidence.": "أغلق الحلقة بدليل مقاس.",
    "verification compares the simulated outcome with the expected operational target.": "التحقق يقارن النتيجة المحاكاة بالهدف التشغيلي المتوقع.",
    "simulated execution": "تنفيذ محاكى", "verification status": "حالة التحقق", "latest result": "آخر نتيجة", "expected saving": "التوفير المتوقع",
    "observed saving": "التوفير الفعلي", "performance ratio": "نسبة الأداء", "% ratio": "% نسبة", "threshold": "العتبة",
    "verification criterion": "معيار التحقق", "target not met": "لم يتحقق الهدف", "verified": "تم التحقق",
    "agent history": "سجل الوكيل", "verification trail": "مسار التحقق", "no verification history.": "لا يوجد سجل تحقق.",
    "what this means": "ماذا يعني هذا", "verification is a second decision layer": "التحقق طبقة قرار ثانية",
    "what the simulation predicted": "ما تنبأت به المحاكاة", "target impact calculated before the action.": "الأثر المستهدف المحسوب قبل الإجراء.",
    "observed": "الفعلي", "what the simulated execution produced": "ما أنتجه التنفيذ المحاكى", "outcome measured after the action.": "النتيجة المقاسة بعد الإجراء.",
    "decision": "القرار", "pass or replan": "نجاح أو إعادة تخطيط", "if the result is insufficient, the agent can select an alternative.": "إذا كانت النتيجة غير كافية، يمكن للوكيل اختيار بديل.",

    // ---------- decision flowchart ----------
    "agent execution roadmap": "خارطة تنفيذ الوكيل", "autonomous decision flow": "مسار القرار الذاتي",
    "11 stages · 4 decision points · human in the loop · closed-loop verification": "11 مرحلة · 4 نقاط قرار · الإنسان ضمن الحلقة · تحقق بحلقة مغلقة",
    "current state": "الحالة الحالية", "run live demo": "تشغيل عرض مباشر", "agent decision flowchart": "مخطط قرارات الوكيل",
    "act · learn": "التنفيذ · التعلّم", "no · keep watching": "لا · استمر بالمراقبة", "yes · approved": "نعم · تمت الموافقة",
    "alternative → approval again": "بديل ← موافقة من جديد", "event stream": "تدفق الأحداث", "ml predictions": "تنبؤات التعلم الآلي",
    "now": "الآن", "live telemetry": "قياس مباشر", "actionable": "حدث قابل", "event?": "للإجراء؟", "ml detection": "كشف التعلم الآلي",
    "energy.db · db tools": "energy.db · أدوات قاعدة البيانات", "event-hour snapshot": "لقطة ساعة الحدث", "event context": "سياق الحدث",
    "load model": "نموذج الحمل", "4 what-if actions": "4 إجراءات «ماذا لو»", "score + constraints": "النتيجة + القيود",
    "valid": "مرشّح", "candidate?": "صالح؟", "operator": "هل يوافق", "approves?": "المشغّل؟", "operator approves?": "هل يوافق المشغّل؟",
    "08 · hitl": "08 · موافقة بشرية", "logged · no action": "مسجّل · بلا إجراء", "simulated action": "إجراء محاكى",
    "achieved vs expected": "المحقّق مقابل المتوقع", "≥ 80% of": "≥ 80% من", "expected?": "المتوقع؟", "11 · completed": "11 · مكتمل",
    "savings verified": "توفير موثَّق", "next-best action": "الإجراء التالي الأفضل", "active now": "نشط الآن", "feedback loop": "حلقة تغذية راجعة",
    "stop / rejected": "توقف / رفض", "the agent is monitoring. press": "الوكيل يراقب. اضغط", "to watch it travel through the flow.": "لتشاهده يتنقل عبر المسار.",
    "click to open operations →": "اضغط لفتح العمليات ←", "click to open digital twin →": "اضغط لفتح التوأم الرقمي ←",
    "click to open verification →": "اضغط لفتح التحقق ←", "click to open energy →": "اضغط لفتح الطاقة ←", "click to open activity →": "اضغط لفتح السجل ←",
    "prediction events from prediction_engine.py (peak_demand_risk, energy_anomaly) trigger a run.": "أحداث التنبؤ من prediction_engine.py (خطر الذروة، شذوذ الطاقة) تُطلق التشغيل.",
    "the agent receives the event and logs it.": "يستلم الوكيل الحدث ويسجّله.",
    "only events with simulated actions are investigated; the rest keep the agent watching.": "يُحقَّق فقط في الأحداث التي لها إجراءات محاكاة؛ والباقي يبقي الوكيل في المراقبة.",
    "confirms the event against ml prediction events at the same timestamp.": "يؤكد الحدث مقابل أحداث تنبؤ التعلم الآلي في نفس الوقت.",
    "consumption, hvac, occupancy and solar at the event hour, 24 h history and grid status.": "الاستهلاك والتكييف والإشغال والطاقة الشمسية عند ساعة الحدث، وسجل 24 ساعة وحالة الشبكة.",
    "pulls the full ml event context for the timestamp.": "يجلب سياق حدث التعلم الآلي الكامل لذلك الوقت.",
    "attaches the predicted load from the ml forecasting model.": "يرفق الحمل المتوقع من نموذج التنبؤ.",
    "simulates hvac setpoint, ev charging shift, battery discharge and the combined action.": "يحاكي ضبط التكييف وإزاحة شحن السيارات وتفريغ البطارية والإجراء المركّب.",
    "score = reduction × severity weight − disruption penalty; invalid candidates are filtered out.": "النتيجة = التخفيض × وزن الخطورة − جزاء الإزعاج؛ وتُستبعد المرشّحات غير الصالحة.",
    "no valid recommendation, or any tool error, stops the run safely.": "غياب توصية صالحة أو أي خطأ في الأدوات يوقف التشغيل بأمان.",
    "human-in-the-loop gate. a recommendation is not an approval: nothing executes until an operator approves.": "بوابة الموافقة البشرية. التوصية ليست موافقة: لا يُنفَّذ شيء حتى يوافق المشغّل.",
    "the rejection is logged and no action is executed.": "يُسجَّل الرفض ولا يُنفَّذ أي إجراء.",
    "a tool returned no data; the agent stops instead of guessing.": "أداة لم تُرجع بيانات؛ الوكيل يتوقف بدل أن يخمّن.",
    "applies the approved action in simulation. no physical equipment is controlled.": "يطبّق الإجراء الموافَق عليه في المحاكاة. لا يتم التحكم بأي معدات فعلية.",
    "compares the achieved reduction with the expected reduction.": "يقارن التخفيض المحقّق بالتخفيض المتوقع.",
    "at least 80 % of the expected reduction → success, otherwise underperformed.": "80% على الأقل من التخفيض المتوقع ← نجاح، وإلا «دون الهدف».",
    "closed loop: the verified reduction is recorded.": "حلقة مغلقة: يُسجَّل التخفيض الموثَّق.",
    "excludes actions already tried, picks the next-best valid candidate and returns to the human gate.": "يستبعد الإجراءات المجرَّبة ويختار المرشّح الصالح التالي ويعود إلى بوابة الموافقة البشرية.",
    "confirms the event": "يؤكد الحدث",

    // ---------- knowledge ----------
    "ask the knowledge layer about the operation.": "اسأل طبقة المعرفة عن التشغيل.",
    "use the rag service to retrieve project knowledge and optionally ground the answer in the current agent run.": "استخدم خدمة RAG لاسترجاع معرفة المشروع، ويمكنك ربط الإجابة بتشغيل الوكيل الحالي.",
    "research & operations copilot": "مساعد البحث والعمليات", "smart energy knowledge": "المعرفة الذكية للطاقة",
    "ask a question to retrieve project knowledge.": "اطرح سؤالاً لاسترجاع معرفة المشروع.", "agentic workflow": "سير عمل الوكيل",
    "anomaly investigation": "التحقيق في الشذوذ", "verification & replanning": "التحقق وإعادة التخطيط", "energy on 2016-07-01": "الطاقة يوم 2016-07-01",
    "peak day 2017": "يوم الذروة 2017", "action success rate": "نسبة نجاح الإجراءات", "include current run": "تضمين التشغيل الحالي", "ask ai": "اسأل الذكاء الاصطناعي",
    "current context": "السياق الحالي", "agent grounding": "ربط الإجابة بالوكيل", "knowledge sources": "مصادر المعرفة", "project documents": "مستندات المشروع",
    "indexed rag knowledge base": "قاعدة معرفة RAG مفهرسة", "operational context": "السياق التشغيلي", "optional current agent state": "حالة الوكيل الحالية (اختياري)",
    "energy data": "بيانات الطاقة", "readings, events and actions in energy.db (2016-01-01 → 2017-12-31)": "القراءات والأحداث والإجراءات في energy.db (2016-01-01 ← 2017-12-31)",
    "ask about the project or its data, e.g. energy on 2016-07-01, peak day in 2017...": "اسأل عن المشروع أو بياناته، مثلاً: الطاقة يوم 2016-07-01، يوم الذروة في 2017...",
    "retrieving…": "جارٍ الاسترجاع…", "quoted from retrieved sections": "مقتبس من الأقسام المسترجعة", "computed from the project dataset": "محسوب من بيانات المشروع",
    "no matching data or document": "لا توجد بيانات أو مستندات مطابقة", "project data · computed from energy.db": "بيانات المشروع · محسوبة من energy.db",
    "[d] project data (computed from the dataset)": "[D] بيانات المشروع (محسوبة من البيانات)",
    "live operational data, from the agent (not from the knowledge base)": "بيانات تشغيلية مباشرة من الوكيل (ليست من قاعدة المعرفة)",
    "neither the knowledge base nor the project data covers this question. try asking about consumption on a specific date (e.g. 2016-07-01), a building, hvac, solar, batteries, ev charging, events, demand response or how the agent makes decisions.":
      "لا تغطي قاعدة المعرفة ولا بيانات المشروع هذا السؤال. جرّب السؤال عن الاستهلاك في تاريخ معيّن (مثل 2016-07-01) أو مبنى أو التكييف أو الطاقة الشمسية أو البطاريات أو شحن السيارات أو الأحداث أو كيف يتخذ الوكيل قراراته.",

    // ---------- activity ----------
    "every autonomous decision leaves a trail.": "كل قرار ذاتي يترك أثراً.",
    "review lifecycle transitions, events and the operational history of the current agent session.": "راجع انتقالات دورة الحياة والأحداث والسجل التشغيلي لجلسة الوكيل الحالية.",
    "reset agent session": "إعادة ضبط جلسة الوكيل", "lifecycle activity": "نشاط دورة الحياة", "no activity recorded.": "لا يوجد نشاط مسجّل.",
    "session": "الجلسة", "current agent state": "حالة الوكيل الحالية", "agent session reset.": "تمت إعادة ضبط جلسة الوكيل.",
    "retrieving ml prediction events for context": "جلب أحداث تنبؤ التعلم الآلي كسياق",
    "gathering operational evidence at the event hour via database tools": "جمع الأدلة التشغيلية عند ساعة الحدث عبر أدوات قاعدة البيانات",
    "retrieving ml event context for analysis": "جلب سياق حدث التعلم الآلي للتحليل", "reading forecast context from ml service": "قراءة سياق التنبؤ من خدمة التعلم الآلي",
    "retrieving digital twin simulation results": "جلب نتائج محاكاة التوأم الرقمي", "retrieving optimizer recommendation": "جلب توصية المُحسِّن",
    "waiting for human approval": "بانتظار الموافقة البشرية", "human approved — proceeding to execution": "وافق الإنسان — المتابعة إلى التنفيذ",
    "human rejected the recommendation": "رفض الإنسان التوصية", "action completed successfully": "اكتمل الإجراء بنجاح",
    "waiting for human approval of alternative action": "بانتظار الموافقة البشرية على الإجراء البديل",

    // ---------- admin / profile / auth ----------
    "registered across all roles": "مسجلون في جميع الأدوار", "full root access": "صلاحية كاملة", "hvac & action approvals": "التكييف والموافقة على الإجراءات",
    "telemetry & read-only access": "قياسات وصلاحية قراءة فقط", "2fa email verified": "تحقق ثنائي بالبريد", "unrestricted access": "وصول غير مقيّد",
    "audit trail tracked": "سجل تدقيق متتبَّع", "access control": "التحكم بالوصول", "administrator": "مدير النظام", "users": "المستخدمون",
    "analytics": "التحليلات", "data analyst": "محلل بيانات", "standard user": "مستخدم عادي", "operations manager": "مدير العمليات",
    "security audit": "تدقيق الأمان", "login": "تسجيل دخول", "registration": "تسجيل", "password_reset": "إعادة تعيين كلمة المرور",
    "expired": "منتهي", "superseded": "مستبدَل", "user provisioning": "إنشاء المستخدمين", "role provisioning": "تعيين الأدوار",
    "user:": "المستخدم:", "fine-grained security": "صلاحيات دقيقة", "user management": "إدارة المستخدمين", "security & credentials": "الأمان وبيانات الدخول",
    "login directly as this user": "الدخول مباشرة كهذا المستخدم", "toggle active status": "تبديل حالة التفعيل", "identity": "الهوية",
    "rbac access matrix": "مصفوفة الصلاحيات", "create, update roles & delete accounts": "إنشاء وتحديث الأدوار وحذف الحسابات",
    "adjust setpoints & zone temperatures": "تعديل نقاط الضبط ودرجات حرارة المناطق", "approve or reject agent recommendations": "الموافقة على توصيات الوكيل أو رفضها",
    "access telemetry, digital twin & lime": "الوصول للقياسات والتوأم الرقمي وLIME", "security credentials": "بيانات الأمان",
    "repeat your new password": "أعد كتابة كلمة المرور الجديدة", "e.g. jdoe": "مثال: jdoe", "min. 6 characters": "6 أحرف على الأقل",

    // ---------- LIME forecast explanation ----------
    "model forecast": "تنبؤ النموذج", "actual reading": "القراءة الفعلية", "residual": "الفرق",
    "surrogate baseline": "خط أساس النموذج البديل", "local fit r²": "دقة الملاءمة المحلية R²",
    "campus total": "إجمالي الحرم", "no contributing features returned.": "لم تُرجَع أي عوامل مساهمة.",
    "each bar is one feature's contribution to this single forecast. red pushes the forecast up, green pulls it down. a low r² means the local surrogate fits poorly here, so read the weights with that in mind.":
      "كل شريط يمثل مساهمة عامل واحد في هذا التنبؤ فقط. الأحمر يرفع التنبؤ والأخضر يخفضه. قيمة R² المنخفضة تعني أن النموذج البديل المحلي لا يلائم جيداً هنا، فاقرأ الأوزان مع أخذ ذلك بالحسبان.",
    // ---------- knowledge source card ----------
    "energy consumption": "استهلاك الطاقة", "hvac consumption": "استهلاك التكييف", "solar generation": "توليد الطاقة الشمسية",
    "ev charging": "شحن السيارات الكهربائية", "battery state of charge": "شحن البطارية", "outdoor temperature": "درجة الحرارة الخارجية",
    "solar radiation": "الإشعاع الشمسي", "grid stress level": "مستوى إجهاد الشبكة",
    "laboratory energy consumption significantly above expected baseline.": "استهلاك طاقة المختبرات أعلى بكثير من خط الأساس المتوقع.",
    "solar generation significantly below expected production.": "توليد الطاقة الشمسية أقل بكثير من الإنتاج المتوقع.",
    "(labelled anomaly)": "(شذوذ موسوم)",
    "repeat your password": "أعد كتابة كلمة المرور",
    "per event hour": "لكل ساعة حدث", "events": "حدثاً", "system ready": "النظام جاهز", "active": "مفعّل", "deactivated": "معطّل", "english": "English",
  };

  const MONTHS = { january: "كانون الثاني", february: "شباط", march: "آذار", april: "نيسان", may: "أيار", june: "حزيران", july: "تموز",
    august: "آب", september: "أيلول", october: "تشرين الأول", november: "تشرين الثاني", december: "كانون الأول" };

  // Translate a fragment (used inside patterns): exact match or unchanged.
  const w = s => AR[norm(s)] ?? s;
  const action = s => AR[norm(s)] ?? s;

  const PATTERNS = [
    [/^([−+-]?[\d.]+%) vs forecast$/i, (m) => `${m[1]} مقارنة بالتنبؤ`],
    [/^([\d.]+%) of grid limit$/i, (m) => `${m[1]} من حد الشبكة`],
    [/^score ([\d.]+)$/i, (m) => `النتيجة ${m[1]}`],
    [/^load → ([\d.]+) kW$/i, (m) => `الحمل ← ${m[1]} kW`],
    [/^battery ([\d.]+%)$/i, (m) => `البطارية ${m[1]}`],
    [/^EV ([\d.]+) kW$/, (m) => `السيارات ${m[1]} kW`],
    [/^stage (\d+) \/ (\d+)(?: · replans (\d+))?$/i, (m) => `المرحلة ${m[1]} / ${m[2]}` + (m[3] ? ` · جولات إعادة التخطيط ${m[3]}` : "")],
    [/^show all (\d+)$/i, (m) => `عرض الكل (${m[1]})`],
    [/^(\d+) (high|elevated|critical)$/i, (m) => `${m[1]} ${w(m[2])}`],
    [/^showing the (\d+) most recent of (\d+)\. the activity page lists them all\.$/i, (m) => `عرض أحدث ${m[1]} من ${m[2]}. صفحة سجل النشاط تعرضها كلها.`],
    [/^forecast campus demand reaches ([\d.]+)% of the grid import limit$/i, (m) => `الطلب المتوقع للحرم يبلغ ${m[1]}% من حد الاستيراد من الشبكة`],
    [/^forecast load at the event hour: ([\d.]+) kW\.$/i, (m) => `الحمل المتوقع عند ساعة الحدث: ${m[1]} kW.`],
    [/^([\d.]+) forecast demand vs\. grid import limit \(%\)$/i, (m) => `${m[1]} الطلب المتوقع مقابل حد الاستيراد (%)`],
    [/^([\d.]+)% of metered load$/i, (m) => `${m[1]}% من الحمل المقاس`],
    [/^([\d.]+) readings$/i, (m) => `${m[1]} قراءة`],
    [/^(\d+) (?:high severity|high), plus (\d+) campus peak-demand risks$/i, (m) => `${m[1]} مرتفعة الخطورة، و${m[2]} خطر ذروة طلب للحرم`],
    [/^estimated reduction ([\d.]+) kW \(minimum 1 kW\)$/i, (m) => `التخفيض المقدّر ${m[1]} kW (الحد الأدنى 1 kW)`],
    [/^battery soc ([\d.]+%) \(must be above 30%\)$/i, (m) => `شحن البطارية ${m[1]} (يجب أن يكون فوق 30%)`],
    [/^active ev charging load ([\d.]+) kW \(must be above 0 kW\)$/i, (m) => `حمل شحن السيارات الفعلي ${m[1]} kW (يجب أن يكون فوق 0 kW)`],
    [/^it has the highest optimization score \(([\d.]+)\)\.$/i, (m) => `لديه أعلى نتيجة تحسين (${m[1]}).`],
    [/^it passed every constraint, but scored ([\d.]+) against ([\d.]+) for (.+)\.$/i, (m) => `اجتاز كل القيود، لكن نتيجته ${m[1]} مقابل ${m[2]} لـ «${action(m[3])}».`],
    [/^score = reduction x ([\d.]+) minus disruption rank x ([\d.]+) \(weights for (\w+) severity\)\.$/i, (m) => `النتيجة = التخفيض × ${m[1]} ناقص درجة الإزعاج × ${m[2]} (أوزان خطورة «${w(m[3])}»).`],
    [/^highest optimization score \(([\d.]+)\) among (\d+) of (\d+) simulated candidates that passed the optimizer's constraints\.$/i,
      (m) => `أعلى نتيجة تحسين (${m[1]}) بين ${m[2]} من ${m[3]} مرشّحات محاكاة اجتازت قيود المُحسِّن.`],
    [/^simulated reduction of ([\d.]+) kW \(([\d.]+)% of the ([\d.]+) kW forecast\)\.$/i, (m) => `تخفيض محاكى قدره ${m[1]} kW (${m[2]}% من التنبؤ البالغ ${m[3]} kW).`],
    [/^optimizer note: (.+)$/i, (m) => `ملاحظة المُحسِّن: ${w(m[1])}`],
    [/^your mix sheds ([\d.]+) kW, at or above the agent's best \((.+), ([\d.]+) kW\)\.$/i, (m) => `مزيجك يخفّض ${m[1]} kW، بقدر أفضل حل للوكيل أو أكثر (${action(m[2])}، ${m[3]} kW).`],
    [/^your mix sheds ([\d.]+) kW — only (\d+)% of the agent's best \(([\d.]+) kW, (.+)\)\. turn up a control or add another\.$/i,
      (m) => `مزيجك يخفّض ${m[1]} kW — فقط ${m[2]}% من أفضل حل للوكيل (${m[3]} kW، ${action(m[4])}). ارفع أداة تحكم أو أضف أخرى.`],
    [/^your mix sheds ([\d.]+) kW — (\d+)% of the agent's ([\d.]+) kW \((.+)\)\.$/i, (m) => `مزيجك يخفّض ${m[1]} kW — ${m[2]}% من ${m[3]} kW لدى الوكيل (${action(m[4])}).`],
    [/^your mix sheds ([\d.]+) kW\. run an analysis to compare against the agent's chosen action\.$/i, (m) => `مزيجك يخفّض ${m[1]} kW. شغّل التحليل للمقارنة بإجراء الوكيل.`],
    [/^battery soc ([\d.]+)% is at or below 30% — the optimizer would reject this discharge\.$/i, (m) => `شحن البطارية ${m[1]}% عند 30% أو أقل — المُحسِّن سيرفض هذا التفريغ.`],
    [/^it achieved ([\d.]+) kW of the expected ([\d.]+) kW \(([\d.]+)%\)\.$/i, (m) => `حقق ${m[1]} kW من ${m[2]} kW المتوقعة (${m[3]}%).`],
    [/^this candidate has the largest remaining reduction: ([\d.]+) kW\.$/i, (m) => `هذا المرشّح صاحب أكبر تخفيض متبقٍ: ${m[1]} kW.`],
    [/^this candidate: ([\d.]+) kW\. selected \((.+)\): ([\d.]+) kW\.$/i, (m) => `هذا المرشّح: ${m[1]} kW. المختار (${action(m[2])}): ${m[3]} kW.`],
    [/^(.+) did not reach the verification target, so the agent's replanning step excluded it\.$/i, (m) => `${action(m[1])} لم يبلغ هدف التحقق، فاستبعده الوكيل في خطوة إعادة التخطيط.`],
    [/^replanning round (\d+)$/i, (m) => `إعادة التخطيط · الجولة ${m[1]}`],
    [/^(.+) reached ([\d.]+)% of its expected reduction \(target ([\d.]+)%\)\. the agent proposes$/i, (m) => `${action(m[1])} حقق ${m[2]}% من التخفيض المتوقع (الهدف ${m[3]}%). الوكيل يقترح`],
    [/^, which needs your approval\.$/i, () => "، وهو يحتاج موافقتك."],
    [/^it reached ([\d.]+)% of the reduction it was expected to deliver, short of the ([\d.]+)% target\. nothing further runs until you decide\.$/i,
      (m) => `حقق ${m[1]}% من التخفيض المتوقع، دون الهدف البالغ ${m[2]}%. لن يعمل شيء آخر حتى تقرر.`],
    [/^battery did not discharge \(([\d.]+) kW against plan\), plus (\d+) other factors? totalling ([\d.]+) kW\.$/i,
      (m) => `البطارية لم تُفرَّغ (${m[1]} kW عكس الخطة)، إضافة إلى ${m[2]} عوامل أخرى مجموعها ${m[3]} kW.`],
    [/^(.+?) \(([\d.]+) kW against plan\)(?:, plus (\d+) other factors? totalling ([\d.]+) kW)?\.$/i,
      (m) => `${w(m[1])} (${m[2]} kW عكس الخطة)` + (m[3] ? `، إضافة إلى ${m[3]} عوامل أخرى مجموعها ${m[4]} kW.` : ".")],
    [/^planned at (.+) · ran at (.+)$/i, (m) => `خُطط له في ${m[1]} · نُفّذ في ${m[2]}`],
    [/^state of charge held at ([\d.]+)% through the execution hour, so the planned ([\d.]+) kW never left the battery\.$/i,
      (m) => `بقي شحن البطارية عند ${m[1]}% طوال ساعة التنفيذ، فلم تخرج الـ ${m[2]} kW المخطط لها من البطارية.`],
    [/^deferring (\d+)% of the ([\d.]+) kW that was charging should have left ([\d.]+) kW on the chargers\. an hour later they were drawing ([\d.]+) kW — ([\d.]+) kW more than planned, so new charging replaced what was deferred\.$/i,
      (m) => `تأجيل ${m[1]}% من ${m[2]} kW كانت تُشحن كان يجب أن يُبقي ${m[3]} kW على الشواحن. بعد ساعة كانت تسحب ${m[4]} kW — أكثر بـ ${m[5]} kW من المخطط، فحلّ شحن جديد محل ما تم تأجيله.`],
    [/^solar was generating ([\d.]+) kW when the plan was made and ([\d.]+) kW an hour later\. that ([\d.]+) kW has to come from the grid instead, working against the reduction\.$/i,
      (m) => `كانت الطاقة الشمسية تولّد ${m[1]} kW عند وضع الخطة و${m[2]} kW بعد ساعة. هذه الـ ${m[3]} kW يجب أن تأتي من الشبكة بدلاً منها، ما يعاكس التخفيض.`],
    [/^the readings show ([\d.]+) kW of load running above what the plan assumed — more than the ([\d.]+) kW shortfall the verification record reports\. conditions that hour were harder than the recorded number suggests\.$/i,
      (m) => `تُظهر القراءات ${m[1]} kW من الحمل فوق ما افترضته الخطة — أكثر من العجز البالغ ${m[2]} kW في سجل التحقق. كانت ظروف تلك الساعة أصعب مما يوحي به الرقم المسجّل.`],
    [/^readings at the event hour \((.+)\)\. history covers the 24 hours up to the event\.(?: grid operating under normal conditions\.)?$/i,
      (m) => `القراءات عند ساعة الحدث (${m[1]}). السجل يغطي 24 ساعة حتى الحدث.` + (/normal conditions/i.test(m[0]) ? " الشبكة تعمل في ظروف طبيعية." : "")],
    [/^historical source baseline: (.+)$/i, (m) => `الأساس التاريخي للمصدر: ${m[1]}`],
    [/^latest reading in the database: (.+)$/i, (m) => `آخر قراءة في قاعدة البيانات: ${m[1]}`],
    [/^last 48 hours to (.+)$/i, (m) => `آخر 48 ساعة حتى ${m[1]}`],
    [/^48 hours around the event at (.+)$/i, (m) => `48 ساعة حول الحدث في ${m[1]}`],
    [/^simulated, (.+)$/i, (m) => `محاكى، ${action(m[1])}`],
    [/^rejected at (.+)\. nothing was executed\.$/i, (m) => `رُفض في ${m[1]}. لم يُنفَّذ شيء.`],
    [/^approved at (.+)$/i, (m) => `تمت الموافقة في ${m[1]}`],
    [/^rejected at (.+)$/i, (m) => `رُفض في ${m[1]}`],
    [/^reached at (.+)$/i, (m) => `وصل في ${m[1]}`],
    [/^click to open (.+) →$/i, (m) => `اضغط لفتح ${w(m[1])} ←`],
    [/^verification record found for (\w+)$/i, (m) => `وُجد سجل تحقق لـ ${w(m[1])}`],
    [/^underperformed — replanning from (\w+)$/i, (m) => `أداء دون الهدف — إعادة تخطيط بدءاً من ${w(m[1])}`],
    [/^event received: (\w+) @ (.+)$/i, (m) => `استلام حدث: ${w(m[1])} @ ${m[2]}`],
    [/^(\d+) of (\d+) anomalies \((\d+)%\) fall in the (.+) shutdown\. (.+)$/i, (m) => `${m[1]} من ${m[2]} حالة شذوذ (${m[3]}%) تقع ضمن إغلاق ${m[4]}. كلها أقل من التنبؤ؛ المباني كانت شبه فارغة بينما توقّع النموذج يوم عمل عادي — هذه نقاط عمياء في النموذج، لا أعطال في المباني.`],
    [/^anomalies in the (.+) shutdown \(([\d.]+)%\)$/i, (m) => `حالة شذوذ ضمن إغلاق ${m[1]} (${m[2]}%)`],
    [/^overall success across (\d+) executions$/i, (m) => `نسبة النجاح الإجمالية عبر ${m[1]} تنفيذ`],
    [/^consumed \((\d+)\)$/i, (m) => `مستخدَم (${m[1]})`],
    [/^(B\d{3}|CAMPUS) (ENERGY_ANOMALY|PEAK_DEMAND_RISK|SOLAR_UNDERPERFORMANCE) — (.+?)( \(labelled anomaly\))?$/,
      (m) => `${m[1]} ${w(m[2].replace(/_/g, " ").toLowerCase()) || m[2]} — ${w(m[3])}${m[4] ? " (شذوذ موسوم)" : ""}`],
    [/^building (B\d{3})$/i, (m) => `المبنى ${m[1]}`],
    [/^(?:.*[<>=].*|(?:day of week|month|weekend): .+)$/i, (m) => limeRule(m[0])],
    [/^([A-Z]{2,}\d*) (campus-wide|administration|labs|classrooms)$/i, (m) => `${m[1]} ${w(m[2])}`],
    [/^(peak demand risk|energy anomaly), (\w+) (.+)$/i, (m) => `${w(m[1])}، ${m[2]} ${w(m[3])}`],
    [/^(\d{1,2}:\d\d(?::\d\d)?) · ([\d.]+) \/ ([\d.]+) kW · (\w+)$/i, (m) => `${m[1]} · ${m[2]} / ${m[3]} kW · ${w(m[4])}`],
    [/^(\d{1,2}:\d\d(?::\d\d)?) · (.+)$/, (m) => `${m[1]} · ${tr(m[2])}`],
    [/^(january|february|march|april|may|june|july|august|september|october|november|december) (\d{1,2}), (\d{4})(.*)$/i,
      (m) => `${m[2]} ${MONTHS[m[1].toLowerCase()]} ${m[3]}${m[4]}`],
    [/^(\d+) · (.+)$/, (m) => { const t = AR[norm(m[2])]; return t ? `${m[1]} · ${t}` : null; }],
    [/^energy consumption for (.+) on (.+?): (.+)$/i, (m) => `استهلاك الطاقة لـ ${m[1]} في ${m[2]}: ${m[3]}`],
  ];


  // LIME rule strings: "78.70 < Last hour's usage <= 215.00", "Day of week: Monday"
  const LIME_FEATURES = {
    "last hour's usage": "استهلاك الساعة السابقة", "usage same hour yesterday": "استهلاك نفس الساعة أمس",
    "usage same hour last week": "استهلاك نفس الساعة الأسبوع الماضي", "24-hour average usage": "متوسط استهلاك 24 ساعة",
    "7-day average usage": "متوسط استهلاك 7 أيام", "time of day (cyclic)": "وقت اليوم (دوري)", "season (yearly cycle)": "الموسم (دورة سنوية)",
    "sunlight intensity": "شدة أشعة الشمس", "rainfall": "الأمطار", "wind speed": "سرعة الرياح", "occupancy": "الإشغال",
    "hour of day": "ساعة اليوم", "day of week": "يوم الأسبوع", "month": "الشهر", "day of year": "يوم السنة", "weekend": "عطلة نهاية الأسبوع",
    "outdoor temperature": "درجة الحرارة الخارجية", "temperature": "درجة الحرارة", "humidity": "الرطوبة", "cloud cover": "الغيوم",
    "solar generation": "توليد الطاقة الشمسية", "hvac load": "حمل التكييف", "hvac power": "قدرة التكييف", "ev charging": "شحن السيارات",
    "battery charge": "شحن البطارية", "battery power": "قدرة البطارية", "grid stress": "إجهاد الشبكة", "grid import limit": "حد الاستيراد",
    "building": "المبنى",
  };
  const DAYS = { monday: "الاثنين", tuesday: "الثلاثاء", wednesday: "الأربعاء", thursday: "الخميس", friday: "الجمعة", saturday: "السبت", sunday: "الأحد" };
  function limeRule(text) {
    let out = String(text), hit = false;
    const keys = Object.keys(LIME_FEATURES).sort((a, b) => b.length - a.length);
    for (const k of keys) {
      const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/'/g, "['’]"), "i");
      if (re.test(out)) { out = out.replace(re, LIME_FEATURES[k]); hit = true; break; }
    }
    if (!hit) return null;
    out = out.replace(/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i, d => DAYS[d.toLowerCase()]);
    out = out.replace(/\b(january|february|march|april|may|june|july|august|september|october|november|december)\b/i, m => MONTHS[m.toLowerCase()]);
    return out;
  }

  function norm(s) { return String(s).replace(/\s+/g, " ").trim().toLowerCase(); }

  // Translate one string; returns null when nothing matches.
  function tr(text) {
    const key = norm(text);
    if (!key || !/[a-z]{2,}/i.test(key)) return null;
    if (key in AR) return AR[key];
    for (const [re, fn] of PATTERNS) {
      const raw = String(text).replace(/\s+/g, " ").trim();
      const m = raw.match(re) || key.match(re);
      if (m) { const out = fn(m); if (out != null) return out; }
    }
    // Leading "— " (e.g. flowchart description after the stage name)
    const dash = String(text).match(/^(\s*[—–-]\s+)(.+)$/);
    if (dash) { const t = tr(dash[2]); if (t != null) return dash[1] + t; }
    // Composite "A · B · C": translate parts; succeed if at least one part changed.
    if (key.includes(" · ")) {
      const parts = String(text).trim().split(" · ");
      let changed = false;
      const outParts = parts.map(p => { const t = tr(p); if (t != null) { changed = true; return t; } return p; });
      if (changed) return outParts.join(" · ");
    }
    // Trailing arrow or leading bullet variants
    const m = String(text).trim().match(/^(•\s*)?(.*?)(\s*[→↓]\s*)?$/);
    if (m && (m[1] || m[3]) && m[2] && norm(m[2]) in AR) return (m[1] || "") + AR[norm(m[2])] + (m[3] ? " ←" : "");
    return null;
  }

  const isArabic = () => document.documentElement.getAttribute("lang") === "ar";
  const SKIP = "script,style,code,pre,textarea,[data-no-i18n]";
  const ATTRS = ["placeholder", "title", "aria-label"];
  let busy = false;

  function translateTextNode(n) {
    const el = n.parentElement;
    if (!el || el.closest(SKIP)) return;
    const cur = n.textContent;
    if (isArabic()) {
      if (n.__i18nAr === cur) return;                    // already ours
      const t = tr(cur);
      if (t == null) return;
      const lead = cur.match(/^\s*/)[0], trail = cur.match(/\s*$/)[0];
      n.__i18nEn = cur; n.__i18nAr = lead + t + trail;
      n.textContent = n.__i18nAr;
    } else if (n.__i18nEn != null && n.__i18nAr === cur) {
      n.textContent = n.__i18nEn;
      n.__i18nAr = null;
    }
  }

  function translateAttrs(el) {
    if (el.closest(SKIP)) return;
    for (const a of ATTRS) {
      if (!el.hasAttribute(a) || el.hasAttribute("data-i18n-" + (a === "aria-label" ? "aria" : a))) continue;
      const store = "__i18n_" + a, cur = el.getAttribute(a);
      if (isArabic()) {
        if (el[store + "ar"] === cur) continue;
        const t = tr(cur); if (t == null) continue;
        el[store + "en"] = cur; el[store + "ar"] = t; el.setAttribute(a, t);
      } else if (el[store + "en"] != null && el[store + "ar"] === cur) {
        el.setAttribute(a, el[store + "en"]); el[store + "ar"] = null;
      }
    }
  }

  function translateTree(root) {
    if (!root) return;
    busy = true;
    try {
      if (root.nodeType === 3) { translateTextNode(root); return; }
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let n; while ((n = walker.nextNode())) translateTextNode(n);
      if (root.nodeType === 1) {
        if (root.matches && root.matches("[placeholder],[title],[aria-label]")) translateAttrs(root);
        root.querySelectorAll && root.querySelectorAll("[placeholder],[title],[aria-label]").forEach(translateAttrs);
      }
    } finally { busy = false; }
  }

  window.trArabic = tr;                                   // used by app.js for chart labels
  window.translateAll = () => translateTree(document.body);

  function start() {
    translateTree(document.body);
    new MutationObserver(muts => {
      if (busy) return;
      for (const m of muts) {
        if (m.type === "characterData") translateTree(m.target);
        else if (m.type === "attributes") translateAttrs(m.target);
        else m.addedNodes.forEach(nd => translateTree(nd));
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    // Language switch (i18n_theme.js sets <html lang>)
    new MutationObserver(() => { translateTree(document.body); document.dispatchEvent(new CustomEvent("langchange")); })
      .observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
