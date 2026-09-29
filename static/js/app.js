(() => {
  "use strict";

  const page = document.body.dataset.page || "overview";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];

  const state = {
    building: localStorage.getItem("smart_energy_building") || "CAMPUS",
    dashboard: null,
    health: null,
    energy: null,
    events: [],
    agent: null,
    verification: null,
    chart: null,
    chartReady: null,
    requestBusy: false,
    replaying: false,
    openWhy: new Set()
  };

  const lifecycle = [
    "MONITORING", "INVESTIGATING", "GATHERING_EVIDENCE", "ANALYZING",
    "FORECASTING", "SIMULATING", "VALIDATING", "WAITING_FOR_APPROVAL",
    "EXECUTING", "VERIFYING", "COMPLETED"
  ];

  const stateLabel = {
    MONITORING: "Monitoring",
    INVESTIGATING: "Investigating",
    GATHERING_EVIDENCE: "Gathering evidence",
    ANALYZING: "Analyzing",
    FORECASTING: "Forecasting",
    SIMULATING: "Simulating",
    VALIDATING: "Validating",
    WAITING_FOR_APPROVAL: "Waiting for approval",
    EXECUTING: "Executing",
    VERIFYING: "Verifying",
    COMPLETED: "Completed",
    FAILED: "Failed"
  };

  const num = value => {
    if (value === null || value === undefined || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };

  const fmt = (value, digits = 1) => {
    const n = num(value);
    return n === null ? "—" : n.toFixed(digits);
  };

  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[c]));

  const safeArray = value => Array.isArray(value) ? value : [];

  function humanState(value) {
    return stateLabel[value] || String(value || "—").replaceAll("_", " ");
  }

  function setText(selector, value) {
    const el = $(selector);
    if (el) el.textContent = value == null || value === "" ? "—" : String(value);
  }

  async function api(url, options = {}) {
    const res = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) }
    });
    const body = await res.json().catch(() => ({}));
    if (body.success === false) throw new Error(body.error || `HTTP ${res.status}`);
    if (!body.success) throw new Error(body.error || `Invalid API response (HTTP ${res.status})`);
    return body.data;
  }

  function toast(message) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.remove("show"), 3200);
  }

  function setBusy(busy) {
    state.requestBusy = busy;
    $$("button").forEach(btn => {
      if (btn.dataset.persistentDisabled === "true") return;
      // The decision gates stay live while the agent works. The replanning
      // dialog appears during that same busy window, so its buttons belong on
      // this list too: disabling them leaves a dialog that ignores clicks.
      if (["approve-agent", "reject-agent",
           "replan-approve", "replan-reject", "replan-later"].includes(btn.id)) return;
      btn.disabled = busy && !btn.classList.contains("seg");
    });
    const run = $("#run-agent");
    if (run) run.disabled = busy || state.replaying;
  }

  function setDecisionButtons() {
    setExplainButtons();
    const waiting = state.agent?.state === "WAITING_FOR_APPROVAL";
    const canAct = waiting && !state.requestBusy && !state.replaying;
    const approve = $("#approve-agent");
    const reject = $("#reject-agent");
    if (approve) approve.disabled = !canAct;
    if (reject) reject.disabled = !canAct;

    // Once the gate has closed, Approve and Reject are dead controls sitting on
    // the page. The question the reader has at that point is "did it work?",
    // and the answer lives on the Verification page, so the primary button
    // becomes the way there. It is relabelled rather than silently repurposed:
    // a button that still says "Approve" must never do something else.
    const settled = ["COMPLETED", "FAILED"].includes(state.agent?.state);
    if (approve) {
      if (settled) {
        approve.disabled = false;
        approve.textContent = "View verification";
        approve.dataset.role = "verification";
      } else {
        approve.textContent = "Approve";
        delete approve.dataset.role;
      }
    }
  }

  /** The Approve button after the cycle closes: go and see the outcome. */
  function goToVerification() {
    const href = document.querySelector('.nav-item[href$="verification"]')?.getAttribute("href");
    window.location.assign(href || "/verification");
  }

  function setStatus(label, healthy) {
    ["#top-status", "#sidebar-status"].forEach(s => setText(s, label));
    ["#top-status-dot", "#sidebar-status-dot"].forEach(s => {
      const el = $(s);
      if (el) el.style.background = healthy ? "var(--success)" : "var(--danger)";
    });
  }

  async function loadHealth() {
    try {
      const h = await api("/api/health");
      state.health = h;
      const healthy = Boolean(h.database && h.ml_service);
      setStatus(healthy ? "Online" : "Degraded", healthy);
      renderHealth(h);
    } catch (e) {
      state.health = null;
      setStatus("Offline", false);
      renderHealth(null, e.message);
    }
  }

  function renderHealth(h, error = null) {
    const root = $("#overview-health");
    if (!root) return;

    if (!h) {
      root.innerHTML = ["database", "ml_service", "optimizer", "rag"].map(k =>
        `<div class="health-row"><span>${esc(k.replaceAll("_", " ").toUpperCase())}</span><b>Unavailable</b></div>`
      ).join("");
    } else {
      root.innerHTML = ["database", "ml_service", "optimizer", "rag"].map(k => `
        <div class="health-row">
          <span>${esc(k.replaceAll("_", " ").toUpperCase())}</span>
          <b>${h[k] ? "OK" : "Unavailable"}</b>
        </div>`).join("");

      const mock = $("#mock-data-warning");
      if (mock) mock.hidden = !h.mock_data;
      setText("#overview-ml", h.ml_service ? "Available" : "Unavailable");
      setText("#overview-rag", h.rag ? "Available" : "Unavailable");
    }
    if (error) {
      const mock = $("#mock-data-warning");
      if (mock) { mock.hidden = false; mock.textContent = `Health unavailable: ${error}`; }
    }
  }

  async function loadDashboard() {
    try {
      const d = await api(`/api/dashboard?building=${encodeURIComponent(state.building)}`);
      state.dashboard = d;
      renderDashboard(d);
      return d;
    } catch (e) {
      toast(`Dashboard: ${e.message}`);
      return null;
    }
  }

  function renderDashboard(d) {
    if (!d) return;
    const k = d.kpis || {};
    setText("#overview-load", num(k.current_load_kw) == null ? "—" : `${fmt(k.current_load_kw)} kW`);
    setText("#overview-solar", num(k.solar_kw) == null ? "—" : `${fmt(k.solar_kw)} kW`);
    setText("#overview-anomalies", num(k.anomalies) == null ? "—" : k.anomalies);
    const anomalyButton = $("#show-anomalies");
    if (anomalyButton) anomalyButton.disabled = !num(k.anomalies);
    const high = num(k.anomalies_high);
    const risks = num(k.peak_risks);
    const anomalyMeta = $("#overview-anomalies")?.nextElementSibling;
    if (anomalyMeta) anomalyMeta.textContent =
      `${high == null ? "—" : high} high severity, plus ${risks == null ? "—" : risks} campus peak-demand risks`;
    const asOf = $("#overview-as-of");
    if (asOf) asOf.textContent = d.as_of ? `Latest reading in the database: ${d.as_of}` : "Latest reading in the database: —";

    const achieved = num(k.achieved_reduction_kw);
    const estimated = num(k.estimated_reduction_kw);
    if (achieved != null) {
      setText("#overview-reduction", `${fmt(achieved)} kW`);
      setText("#overview-reduction-meta", "Achieved in verification");
    } else if (estimated != null) {
      setText("#overview-reduction", `${fmt(estimated)} kW`);
      setText("#overview-reduction-meta", `Simulated, ${k.estimated_reduction_action || "selected action"}`);
    } else {
      setText("#overview-reduction", "—");
      setText("#overview-reduction-meta", "Run an analysis first");
    }
    renderOverviewImpact(achieved != null ? achieved : estimated);

    const agent = d.agent || {};
    setText("#overview-agent-state", humanState(agent.state));
    setText("#overview-agent-event", state.agent?.problem?.headline || "No active event.");
    setText("#overview-approval", approvalText(state.agent || agent));
    renderRagStatus(d.rag);
  }

  // Money and carbon for the reduction card. Factors come from /api/impact/factors
  // (impact_translation.py) so every page quotes the same numbers.
  const impactFactors = { tariff_jod_per_kwh: 0.14, grid_co2_kg_per_kwh: 0.55, duration_hours: 1 };
  async function loadImpactFactors() {
    try {
      const f = await api("/api/impact/factors");
      if (f?.tariff_jod_per_kwh) Object.assign(impactFactors, f);
    } catch (_) { /* defaults stand */ }
    renderOverviewImpact(state.overviewReductionKw ?? null);
  }
  function renderOverviewImpact(kw) {
    state.overviewReductionKw = kw;
    if (!$("#overview-impact")) return;
    const k = num(kw);
    const kwh = k == null ? null : k * (num(impactFactors.duration_hours) || 1);
    setText("#overview-impact-money", kwh == null ? "—" : `${fmt(kwh * impactFactors.tariff_jod_per_kwh, 2)} JOD`);
    setText("#overview-impact-co2", kwh == null ? "—" : `${fmt(kwh * impactFactors.grid_co2_kg_per_kwh, 1)} kg`);
    setText("#overview-impact-basis",
      `${fmt(impactFactors.tariff_jod_per_kwh, 2)} JOD/kWh · ${fmt(impactFactors.grid_co2_kg_per_kwh, 2)} kg CO₂/kWh · per event hour`);
    $("#overview-impact").classList.toggle("empty", kwh == null);
  }

  // Overview shows the five most recent events; the rest stay one click away.
  function setupOverviewEvents() {
    const list = $("#overview-events"), btn = $("#overview-events-toggle");
    if (!list || !btn) return;
    const sync = () => {
      const rows = $$(".event-row", list).length;
      btn.hidden = rows <= 5;
      btn.textContent = list.classList.contains("expanded") ? "Show less" : `Show all ${rows}`;
    };
    btn.addEventListener("click", () => { list.classList.toggle("expanded"); sync(); });
    new MutationObserver(sync).observe(list, { childList: true });
    sync();
  }

  function renderRagStatus(rag) {
    const el = $("#overview-rag-detail");
    if (!el || !rag) return;
    if (!rag.available) el.textContent = "Unavailable";
    else if (rag.generation === "llm") el.textContent = rag.model ? `LLM · ${rag.model}` : "LLM";
    else el.textContent = "Extractive, no language model configured";
  }

  function approvalText(a) {
    if (!a) return "—";
    if (a.last_decision?.decision === "REJECTED") return `Rejected at ${a.last_decision.time}. Nothing was executed.`;
    if (a.state === "WAITING_FOR_APPROVAL") return "Human approval required";
    if (a.state === "EXECUTING") return "Simulated execution in progress";
    if (a.state === "VERIFYING") return "Verification in progress";
    if (a.state === "COMPLETED") return "Completed";
    if (a.approval_required) return "Approval required";
    return "No approval gate active";
  }

  function normalizeEnergy(d) {
    return {
      labels: safeArray(d?.labels),
      consumption: safeArray(d?.energy_kw),
      solar: safeArray(d?.solar_kw),
      hvac: safeArray(d?.hvac_kw),
      ev: safeArray(d?.ev_kw),
      occupancy: safeArray(d?.occupancy_pct),
      center: d?.center ?? null,
      end: d?.end ?? null
    };
  }

  function loadChartLibrary() {
    if (window.Chart) return Promise.resolve(window.Chart);
    if (state.chartReady) return state.chartReady;
    state.chartReady = new Promise(resolve => {
      const script = document.createElement("script");
      script.src = "/static/vendor/chart.umd.min.js";
      script.onload = () => resolve(window.Chart || null);
      script.onerror = () => resolve(null);
      document.head.appendChild(script);
    });
    return state.chartReady;
  }

  // Chart colours per theme. The dark values are the original ones; the light
  // theme needs a dark consumption line (the cream one vanished on ivory).
  function chartPalette() {
    const light = document.documentElement.getAttribute("data-theme") === "light";
    const v = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const alpha = (hex, a) => { const h = hex.replace("#", ""); const n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };
    // Light colours come from the palette's CSS variables (--chart-1..3, --accent).
    return light ? {
      series: {
        consumption: { borderColor: v("--chart-1"), backgroundColor: alpha(v("--chart-1"), .05) },
        solar: { borderColor: v("--chart-2"), backgroundColor: alpha(v("--chart-2"), .06) },
        hvac: { borderColor: v("--chart-3"), backgroundColor: alpha(v("--chart-3"), .05) }
      },
      gridX: alpha(v("--chart-1"), .05), gridY: alpha(v("--chart-1"), .07), ticks: v("--muted-2"), eventLine: v("--accent"),
      tooltip: { backgroundColor: "#FFFFFF", borderColor: alpha(v("--chart-1"), .15), titleColor: v("--cream"), bodyColor: v("--muted") }
    } : {
      // Dark: the theme's cream / gold / accent-3 (Luxury = the original colours).
      series: {
        consumption: { borderColor: v("--cream"), backgroundColor: alpha(v("--cream"), .04) },
        solar: { borderColor: v("--gold"), backgroundColor: alpha(v("--gold"), .04) },
        hvac: { borderColor: v("--accent-3"), backgroundColor: alpha(v("--accent-3"), .04) }
      },
      gridX: "rgba(255,255,255,.035)", gridY: "rgba(255,255,255,.045)", ticks: "#68625d", eventLine: v("--gold"),
      tooltip: { backgroundColor: v("--surface-deep"), borderColor: alpha(v("--gold"), .2), titleColor: "#fff", bodyColor: "#fff" }
    };
  }

  // Recolour live charts when the theme toggles, without reloading data.
  function applyChartTheme() {
    const pal = chartPalette();
    Object.values(state.charts || {}).forEach(chart => {
      if (!chart?.options) return;
      chart.data.datasets.forEach(ds => Object.assign(ds, pal.series[ds.key] || {}));
      const sc = chart.options.scales || {};
      if (sc.x) { sc.x.grid.color = pal.gridX; sc.x.ticks.color = pal.ticks; }
      if (sc.y) { sc.y.grid.color = pal.gridY; sc.y.ticks.color = pal.ticks; }
      Object.assign(chart.options.plugins.tooltip, pal.tooltip);
      chart.update("none");
    });
    // Series names follow the interface language (tooltips are drawn on canvas).
    const ar = document.documentElement.getAttribute("lang") === "ar" && window.trArabic;
    Object.values(state.charts || {}).forEach(chart => {
      if (!chart?.data) return;
      chart.data.datasets.forEach(ds => {
        ds.__en = ds.__en || ds.label;
        ds.label = ar ? (window.trArabic(ds.__en) || ds.__en) : ds.__en;
      });
      chart.update("none");
    });
    const legend = { consumption: pal.series.consumption.borderColor, solar: pal.series.solar.borderColor, hvac: pal.series.hvac.borderColor };
    $$(".ov-chart-legend i").forEach((el, i) => { el.style.background = Object.values(legend)[i]; });
  }
  new MutationObserver(applyChartTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-palette", "lang"] });

  async function buildChart(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const chart = await loadChartLibrary();
    const wrap = canvas.closest(".chart-wrap");
    if (!chart) {
      if (wrap) wrap.innerHTML = `<div class="empty-state chart-error">Chart library failed to load</div>`;
      return;
    }
    state.charts = state.charts || {};
    if (state.charts[canvasId]) state.charts[canvasId].destroy();

    const datasets = [
      { key: "consumption", label: "Consumption", data: data.consumption },
      { key: "solar", label: "Solar", data: data.solar },
      { key: "hvac", label: "HVAC", data: data.hvac }
    ].map(x => ({ ...x, ...chartPalette().series[x.key], borderWidth: 2, pointRadius: 0, tension: .35 }));

    // Dashed line at the selected event hour. Chart.js 4 only accepts inline
    // plugins at construction (config.plugins is read-only afterwards).
    const centerIndex = data.center == null ? -1 : data.labels.indexOf(data.center);
    const inlinePlugins = [];
    if (centerIndex >= 0) {
      const annotationPlugin = {
        id: "eventLine",
        afterDraw(chart) {
          if (!chart.scales?.x || !chart.chartArea) return;
          const x = chart.scales.x.getPixelForValue(centerIndex);
          if (!Number.isFinite(x)) return;
          const { ctx, chartArea: { top, bottom } } = chart;
          ctx.save();
          ctx.setLineDash([6, 5]);
          ctx.strokeStyle = chartPalette().eventLine;
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
          ctx.restore();
        }
      };
      inlinePlugins.push(annotationPlugin);
    }
    const chartInstance = new Chart(canvas, {
      type: "line",
      data: { labels: data.labels, datasets },
      plugins: inlinePlugins,
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { ...chartPalette().tooltip, borderWidth: 1 }
        },
        scales: {
          x: { grid: { color: chartPalette().gridX }, ticks: { color: chartPalette().ticks, maxTicksLimit: 10, font: { size: 9 } } },
          y: { grid: { color: chartPalette().gridY }, ticks: { color: chartPalette().ticks, font: { size: 9 } } }
        }
      }
    });
    state.charts[canvasId] = chartInstance;
    state.chart = chartInstance;
    applyChartTheme();

  }

  async function loadEnergy(canvasId) {
    let d;
    try {
      d = await api(`/api/energy?building=${encodeURIComponent(state.building)}&hours=48`);
    } catch (e) {
      toast(`Energy data: ${e.message}`);
      return null;
    }

    state.energy = normalizeEnergy(d);

    // Fill the tiles before drawing. Chart.js paints the canvas while it is
    // being constructed, so an exception thrown after that point leaves a
    // correct-looking chart on screen and the tiles frozen at "—". They need
    // only data that has already arrived, so they must not wait on the chart.
    renderEnergyTiles();
    renderEnergyCaption(d);

    try {
      await buildChart(canvasId, state.energy);
    } catch (e) {
      console.error("Chart render failed", e);
      toast("Chart could not be drawn. The readings above are current.");
    }

    return d;
  }

  function renderEnergyTiles() {
    const e = state.energy;
    if (!e) return;
    const last = arr => arr.length ? arr[arr.length - 1] : null;
    setText("#energy-load", last(e.consumption) == null ? "—" : `${fmt(last(e.consumption))} kW`);
    setText("#energy-solar", last(e.solar) == null ? "—" : `${fmt(last(e.solar))} kW`);
    setText("#energy-hvac", last(e.hvac) == null ? "—" : `${fmt(last(e.hvac))} kW`);
    setText("#energy-occupancy", last(e.occupancy) == null ? "—" : `${fmt(last(e.occupancy))}%`);
    const lastTs = e.labels[e.labels.length - 1];
    ["#energy-load-time", "#energy-solar-time", "#energy-hvac-time", "#energy-occupancy-time"].forEach(id => {
      const el = $(id); if (el) el.textContent = lastTs ? `Chart window: ${lastTs}` : "Chart window timestamp unavailable";
    });
  }

  function renderEnergyCaption(d) {
    const el = $("#energy-caption");
    if (!el) return;
    el.textContent = d.center
      ? `48 hours around the event at ${d.center}`
      : `last 48 hours to ${d.end || "—"}`;
  }

  function eventText(ev) {
    const label = ev?.event_label || "Event";
    const building = ev?.building_id
      ? `${ev.building_id} ${ev.building_name || ""}`.trim()
      : "campus";
    return `${label}, ${building}`;
  }

  async function loadEvents(targetId) {
    try {
      const d = await api(`/api/events?building=${encodeURIComponent(state.building)}&limit=60`);
      state.events = safeArray(d.events);
      renderEvents(targetId);
      return state.events;
    } catch (e) {
      const target = $(targetId);
      if (target) target.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
      return [];
    }
  }

  function renderEvents(targetId) {
    const target = $(targetId);
    if (!target) return;
    target.innerHTML = state.events.slice(0, 10).map((ev, i) => {
      const sev = String(ev.severity || "—");
      const bad = ["high", "critical"].includes(sev.toLowerCase());
      const action = ev.actionable
        ? `<button class="text-link event-analyze" data-index="${i}" type="button">Analyze</button>`
        : `<button class="text-link" type="button" disabled>No simulation</button>`;
      return `<div class="event-row">
        <span class="event-dot ${bad ? "bad" : ""}"></span>
        <div>
          <b>${esc(eventText(ev))}</b>
          <span style="display:block;margin-top:4px">${esc(ev.timestamp || "—")} · ${esc(sev)}</span>
        </div>
        ${action}
      </div>`;
    }).join("") || `<div class="empty-state">No events returned.</div>`;

    $$(".event-analyze", target).forEach(btn => btn.addEventListener("click", () => {
      const ev = state.events[Number(btn.dataset.index)];
      if (ev) runAgent(ev);
    }));
  }

  async function loadAgent() {
    try {
      state.agent = await api("/api/agent/status");
      renderAgentEverywhere();
      return state.agent;
    } catch (e) {
      toast(`Agent: ${e.message}`);
      return null;
    }
  }

  function renderAgentEverywhere() {
    if (!state.agent) return;
    renderLifecycle(state.agent.state);
    renderOperation(state.agent);
    renderTwin(state.agent);
    renderActivitySession(state.agent);
    renderOverviewAgent(state.agent);
    setDecisionButtons();
  }

  function renderOverviewAgent(a) {
    setText("#overview-agent-state", humanState(a.state));
    setText("#overview-agent-event", a.problem?.headline || "No active event.");
    setText("#overview-approval", approvalText(a));
  }

  function renderLifecycle(stateName) {
    const current = lifecycle.indexOf(stateName);
    const failed = stateName === "FAILED";
    let lastReached = current;
    if (failed && state.agent?.trail?.length) {
      lastReached = Math.max(...state.agent.trail.map(x => lifecycle.indexOf(x.state)).filter(x => x >= 0), 0);
    }

    $$(".life-step").forEach(el => {
      const i = lifecycle.indexOf(el.dataset.state);
      el.classList.toggle("active", !failed && i === current);
      el.classList.toggle("done", !failed && i >= 0 && i < current);
      el.classList.toggle("failed", failed && i === lastReached);
      const trail = safeArray(state.agent?.trail).find(x => x.state === el.dataset.state);
      let time = el.querySelector(".life-time");
      if (trail?.time) {
        if (!time) { time = document.createElement("small"); time.className = "life-time"; el.appendChild(time); }
        time.textContent = trail.time;
      }
    });

    updateAgentFlow(stateName);
  }

  // =========================================================
  // AGENT EXECUTION ROADMAP — decision flowchart (Overview)
  // Mirrors agent.py: 11 states, REPLANNING, FAILED and the four real decision
  // points. Built once as inline SVG; updateAgentFlow() only toggles classes.
  // =========================================================
  const AF = {
    nodes: [
      { id: "start", type: "term", x: 150, y: 100, w: 112, h: 42, title: "Event stream", sub: "ML predictions", href: "energy",
        info: "Prediction events from prediction_engine.py (PEAK_DEMAND_RISK, ENERGY_ANOMALY) trigger a run." },
      { id: "mon", n: "01", x: 300, y: 100, title: "Monitoring", sub: "Live telemetry", href: "operations",
        info: "The agent receives the event and logs it." },
      { id: "dAct", type: "dec", x: 455, y: 100, title: "Actionable", title2: "event?", href: "operations",
        info: "Only events with simulated actions are investigated; the rest keep the agent watching." },
      { id: "inv", n: "02", x: 615, y: 100, title: "Investigating", sub: "ML detection", href: "operations",
        info: "Confirms the event against ML prediction events at the same timestamp." },
      { id: "evIn", type: "io", x: 775, y: 40, title: "energy.db · DB tools" },
      { id: "evi", n: "03", x: 775, y: 100, title: "Evidence", sub: "Event-hour snapshot", href: "operations",
        info: "Consumption, HVAC, occupancy and solar at the event hour, 24 h history and grid status." },
      { id: "ana", n: "04", x: 935, y: 100, title: "Analyzing", sub: "Event context", href: "operations",
        info: "Pulls the full ML event context for the timestamp." },
      { id: "fc", n: "05", x: 180, y: 275, title: "Forecasting", sub: "Load model", href: "energy",
        info: "Attaches the predicted load from the ML forecasting model." },
      { id: "twin", n: "06", x: 335, y: 275, title: "Digital Twin", sub: "4 what-if actions", href: "digital-twin",
        info: "Simulates HVAC setpoint, EV charging shift, battery discharge and the combined action." },
      { id: "opt", n: "07", x: 490, y: 275, title: "Optimizer", sub: "Score + constraints", href: "digital-twin",
        info: "Score = reduction × severity weight − disruption penalty; invalid candidates are filtered out." },
      { id: "dValid", type: "dec", x: 645, y: 275, title: "Valid", title2: "candidate?", href: "operations",
        info: "No valid recommendation, or any tool error, stops the run safely." },
      { id: "gate", type: "dec", big: true, n: "08", x: 815, y: 275, title: "Operator", title2: "approves?", href: "operations",
        info: "Human-in-the-loop gate. A recommendation is not an approval: nothing executes until an operator approves." },
      { id: "rejected", type: "term", tone: "danger", x: 1010, y: 275, w: 132, h: 44, title: "Rejected", sub: "Logged · no action", href: "activity",
        info: "The rejection is logged and no action is executed." },
      { id: "failed", type: "term", tone: "danger", x: 645, y: 346, w: 112, h: 30, title: "Failed", href: "operations",
        info: "A tool returned no data; the agent stops instead of guessing." },
      { id: "exe", n: "09", x: 200, y: 450, title: "Executing", sub: "Simulated action", href: "verification",
        info: "Applies the approved action in simulation. No physical equipment is controlled." },
      { id: "ver", n: "10", x: 400, y: 450, title: "Verifying", sub: "Achieved vs expected", href: "verification",
        info: "Compares the achieved reduction with the expected reduction." },
      { id: "dVer", type: "dec", x: 600, y: 450, title: "≥ 80% of", title2: "expected?", href: "verification",
        info: "At least 80 % of the expected reduction → SUCCESS, otherwise UNDERPERFORMED." },
      { id: "done", type: "term", tone: "success", n: "11", x: 830, y: 450, w: 170, h: 50, title: "Completed", sub: "Savings verified", href: "verification",
        info: "Closed loop: the verified reduction is recorded." },
      { id: "replan", type: "proc", tone: "warn", x: 600, y: 545, title: "Replanning", sub: "Next-best action", href: "operations",
        info: "Excludes actions already tried, picks the next-best valid candidate and returns to the human gate." }
    ],
    edges: [
      { f: "start", t: "mon", p: [[206, 100], [232, 100]] },
      { f: "mon", t: "dAct", p: [[368, 100], [397, 100]] },
      { f: "dAct", t: "inv", p: [[513, 100], [547, 100]], label: "Yes", lx: 530, ly: 92 },
      { f: "dAct", t: "mon", p: [[455, 138], [455, 156], [300, 156], [300, 128]], kind: "never loop", label: "No · keep watching", lx: 378, ly: 168 },
      { f: "inv", t: "evi", p: [[683, 100], [707, 100]] },
      { f: "evIn", t: "evi", p: [[775, 53], [775, 72]], kind: "input" },
      { f: "evi", t: "ana", p: [[843, 100], [867, 100]] },
      { f: "ana", t: "fc", p: [[1003, 100], [1110, 100], [1110, 182], [180, 182], [180, 247]] },
      { f: "fc", t: "twin", p: [[248, 275], [267, 275]] },
      { f: "twin", t: "opt", p: [[403, 275], [422, 275]] },
      { f: "opt", t: "dValid", p: [[558, 275], [587, 275]] },
      { f: "dValid", t: "gate", p: [[703, 275], [749, 275]], label: "Yes", lx: 726, ly: 267 },
      { f: "dValid", t: "failed", p: [[645, 313], [645, 331]], kind: "neg", label: "No", lx: 662, ly: 325 },
      { f: "gate", t: "rejected", p: [[881, 275], [944, 275]], kind: "neg", label: "No", lx: 912, ly: 267 },
      { f: "gate", t: "exe", p: [[815, 317], [815, 372], [200, 372], [200, 422]], label: "Yes · approved", lx: 862, ly: 352 },
      { f: "exe", t: "ver", p: [[268, 450], [332, 450]] },
      { f: "ver", t: "dVer", p: [[468, 450], [542, 450]] },
      { f: "dVer", t: "done", p: [[658, 450], [745, 450]], label: "Yes", lx: 700, ly: 442 },
      { f: "dVer", t: "replan", p: [[600, 488], [600, 520]], kind: "neg", label: "No", lx: 617, ly: 508 },
      { f: "replan", t: "gate", p: [[668, 545], [1170, 545], [1170, 205], [815, 205], [815, 233]], kind: "loop", label: "Alternative → approval again", lx: 1000, ly: 198 }
    ],
    phases: [
      { y: 18, h: 158, n: "01", name: "SENSE" },
      { y: 192, h: 172, n: "02", name: "DECIDE" },
      { y: 388, h: 200, n: "03", name: "ACT · LEARN" }
    ],
    stateNode: {
      MONITORING: "mon", INVESTIGATING: "inv", GATHERING_EVIDENCE: "evi", ANALYZING: "ana",
      FORECASTING: "fc", SIMULATING: "twin", VALIDATING: "opt", WAITING_FOR_APPROVAL: "gate",
      EXECUTING: "exe", VERIFYING: "ver", REPLANNING: "replan", COMPLETED: "done", FAILED: "failed"
    },
    built: false
  };

  const SVGNS = "http://www.w3.org/2000/svg";
  function svgEl(tag, attrs = {}, parent = null) {
    const el = document.createElementNS(SVGNS, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    if (parent) parent.appendChild(el);
    return el;
  }

  // Polyline with rounded corners.
  function afPath(points, r = 12) {
    let d = `M${points[0][0]},${points[0][1]}`;
    for (let i = 1; i < points.length; i++) {
      const [x, y] = points[i];
      if (i === points.length - 1) { d += ` L${x},${y}`; break; }
      const [px, py] = points[i - 1], [nx, ny] = points[i + 1];
      const d1 = Math.hypot(x - px, y - py), d2 = Math.hypot(nx - x, ny - y);
      const k = Math.min(r, d1 / 2, d2 / 2);
      const ax = x - (x - px) / d1 * k, ay = y - (y - py) / d1 * k;
      const bx = x + (nx - x) / d2 * k, by = y + (ny - y) / d2 * k;
      d += ` L${ax},${ay} Q${x},${y} ${bx},${by}`;
    }
    return d;
  }

  function buildAgentFlow() {
    const host = $("#agent-flow");
    if (!host || AF.built) return;
    const svg = svgEl("svg", { viewBox: "0 0 1200 600", class: "af-svg", role: "img" });
    const defs = svgEl("defs", {}, svg);
    defs.innerHTML = `
      <pattern id="af-grid" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" class="af-griddot"/></pattern>
      <filter id="af-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <linearGradient id="af-gold" x1="0" y1="0" x2="1" y2="1"><stop offset="0" class="af-g1"/><stop offset="1" class="af-g2"/></linearGradient>
      ${["base", "done", "live", "neg", "loop"].map(k => `<marker id="af-arrow-${k}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="af-arrow-${k}"/></marker>`).join("")}`;
    svgEl("rect", { x: 0, y: 0, width: 1200, height: 600, fill: "url(#af-grid)", class: "af-gridbg" }, svg);

    AF.phases.forEach(ph => {
      svgEl("rect", { x: 86, y: ph.y, width: 1104, height: ph.h, rx: 18, class: "af-band" }, svg);
      const t = svgEl("text", { x: 44, y: ph.y + ph.h / 2, class: "af-phase", transform: `rotate(-90 44 ${ph.y + ph.h / 2})`, "text-anchor": "middle" }, svg);
      t.innerHTML = `<tspan class="af-phase-n">${ph.n}</tspan> ${ph.name}`;
    });

    const edgeLayer = svgEl("g", { class: "af-edges" }, svg);
    AF.edges.forEach((e, i) => {
      const g = svgEl("g", { class: `af-edge ${e.kind || ""}`, "data-i": i }, edgeLayer);
      const d = afPath(e.p);
      e.d = d;
      svgEl("path", { d, class: "af-line", "marker-end": `url(#af-arrow-${/loop/.test(e.kind || "") ? "loop" : /neg/.test(e.kind || "") ? "neg" : "base"})` }, g);
      if (e.label) {
        const lbl = svgEl("text", { x: e.lx, y: e.ly, class: "af-elabel", "text-anchor": "middle" }, g);
        lbl.textContent = e.label;
      }
      e.g = g;
    });

    const nodeLayer = svgEl("g", { class: "af-nodes" }, svg);
    AF.nodes.forEach(n => {
      const g = svgEl("g", { class: `af-node af-${n.type || "proc"} ${n.tone ? "tone-" + n.tone : ""}`, "data-id": n.id, tabindex: n.info ? 0 : -1 }, nodeLayer);
      let shape, pulse;
      if (n.type === "dec") {
        const hw = n.big ? 65 : 58, hh = n.big ? 42 : 38;
        const pts = `${n.x},${n.y - hh} ${n.x + hw},${n.y} ${n.x},${n.y + hh} ${n.x - hw},${n.y}`;
        pulse = svgEl("polygon", { points: pts, class: "af-pulse" }, g);
        shape = svgEl("polygon", { points: pts, class: "af-shape" }, g);
        const t1 = svgEl("text", { x: n.x, y: n.y - 3, class: "af-dtitle", "text-anchor": "middle" }, g);
        t1.innerHTML = `<tspan x="${n.x}">${n.title}</tspan><tspan x="${n.x}" dy="13">${n.title2 || ""}</tspan>`;
        if (n.n) { const b = svgEl("text", { x: n.x - 40, y: n.y - 32, class: "af-num", "text-anchor": "end" }, g); b.textContent = `${n.n} · HITL`; }
      } else if (n.type === "io") {
        const w = 150, h = 26, sk = 10;
        shape = svgEl("polygon", { points: `${n.x - w / 2 + sk},${n.y - h / 2} ${n.x + w / 2 + sk},${n.y - h / 2} ${n.x + w / 2 - sk},${n.y + h / 2} ${n.x - w / 2 - sk},${n.y + h / 2}`, class: "af-shape" }, g);
        const t = svgEl("text", { x: n.x, y: n.y + 3.5, class: "af-iotext", "text-anchor": "middle" }, g);
        t.textContent = n.title;
      } else {
        const w = n.w || 136, h = n.h || 56, rx = n.type === "term" ? h / 2 : 14;
        pulse = svgEl("rect", { x: n.x - w / 2, y: n.y - h / 2, width: w, height: h, rx, class: "af-pulse" }, g);
        shape = svgEl("rect", { x: n.x - w / 2, y: n.y - h / 2, width: w, height: h, rx, class: "af-shape" }, g);
        if (n.n && n.type !== "term") {
          const b = svgEl("text", { x: n.x - w / 2 + 12, y: n.y - h / 2 + 15, class: "af-num" }, g); b.textContent = n.n;
          const ck = svgEl("text", { x: n.x + w / 2 - 12, y: n.y - h / 2 + 15, class: "af-check", "text-anchor": "end" }, g); ck.textContent = "✓";
        }
        const small = h < 40;
        const tt = svgEl("text", { x: n.x, y: n.sub && !small ? n.y + (n.type === "term" ? -1 : 3) : n.y + 4, class: "af-title", "text-anchor": "middle" }, g);
        tt.textContent = (n.type === "term" && n.n ? `${n.n} · ` : "") + n.title;
        if (n.sub && !small) { const st = svgEl("text", { x: n.x, y: n.y + (n.type === "term" ? 13 : 17), class: "af-sub", "text-anchor": "middle" }, g); st.textContent = n.sub; }
      }
      const now = svgEl("g", { class: "af-nowtag" }, g);
      const top = n.type === "dec" ? n.y - (n.big ? 42 : 38) : n.y - (n.h || 56) / 2;
      svgEl("rect", { x: n.x - 22, y: top - 20, width: 44, height: 15, rx: 7.5 }, now);
      const nt = svgEl("text", { x: n.x, y: top - 9.5, "text-anchor": "middle" }, now); nt.textContent = "NOW";
      n.g = g;
      if (n.href) g.addEventListener("click", () => window.location.assign(`/${n.href}`));
      if (n.info) {
        g.addEventListener("mouseenter", ev => afTip(n, ev));
        g.addEventListener("mousemove", ev => afTip(n, ev));
        g.addEventListener("mouseleave", () => afTip(null));
        g.addEventListener("focus", () => afTip(n, null));
        g.addEventListener("blur", () => afTip(null));
        g.addEventListener("keydown", ev => { if (ev.key === "Enter" && n.href) window.location.assign(`/${n.href}`); });
      }
    });

    // Moving pulse along the edge that leads into the active node.
    const comet = svgEl("circle", { r: 4.2, class: "af-comet" }, svg);
    const motion = svgEl("animateMotion", { dur: "1.4s", repeatCount: "indefinite", path: "M0,0" }, comet);
    AF.comet = comet; AF.motion = motion;

    host.innerHTML = "";
    host.appendChild(svg);
    const tip = document.createElement("div");
    tip.className = "af-tip";
    host.appendChild(tip);
    AF.tip = tip;
    AF.svg = svg;
    AF.built = true;

    $("#af-run")?.addEventListener("click", () => runAgent());
  }

  function afTip(n, ev) {
    const tip = AF.tip;
    if (!tip) return;
    if (!n) { tip.classList.remove("show"); return; }
    const reached = safeArray(state.agent?.trail).filter(x => AF.stateNode[x.state] === n.id).pop();
    tip.innerHTML = `<b>${esc((n.n ? n.n + " · " : "") + n.title + (n.title2 ? " " + n.title2 : ""))}</b><p>${esc(n.info)}</p>${reached?.time ? `<span>Reached at ${esc(reached.time)}</span>` : ""}${n.href ? `<em>Click to open ${esc(n.href.replace("-", " "))} →</em>` : ""}`;
    const host = $("#agent-flow").getBoundingClientRect();
    let x, y;
    if (ev) { x = ev.clientX - host.left + $("#agent-flow").scrollLeft + 16; y = ev.clientY - host.top + 16; }
    else { const r = n.g.getBoundingClientRect(); x = r.right - host.left + 8; y = r.top - host.top; }
    tip.style.left = `${Math.min(x, $("#agent-flow").scrollWidth - 270)}px`;
    tip.style.top = `${y}px`;
    tip.classList.add("show");
  }

  function updateAgentFlow(stateName) {
    if (!$("#agent-flow")) return;
    buildAgentFlow();
    const a = state.agent || {};
    const hasRun = Boolean(a.has_run);
    const trailAll = safeArray(a.trail);
    // During a replay the trail is walked entry by entry: only count states up to
    // the latest occurrence of the state being shown.
    let upto = -1;
    for (let i = trailAll.length - 1; i >= 0; i--) if (trailAll[i].state === stateName) { upto = i; break; }
    const trail = upto >= 0 ? trailAll.slice(0, upto + 1) : trailAll;

    const visited = new Set(["start"]);
    if (hasRun) trail.forEach(t => { const id = AF.stateNode[t.state]; if (id) visited.add(id); });
    const current = hasRun ? (AF.stateNode[stateName] || "mon") : "mon";
    visited.add(current);
    if (visited.has("inv")) visited.add("dAct");
    if (visited.has("gate")) visited.add("dValid");
    if (visited.has("done") || visited.has("replan")) visited.add("dVer");
    if (visited.has("evi")) visited.add("evIn");

    const failed = stateName === "FAILED";
    let broken = null;
    if (failed) {
      const last = [...trail].reverse().find(t => t.state !== "FAILED");
      broken = last ? AF.stateNode[last.state] : null;
      if (visited.has("opt")) visited.add("dValid");
    }
    const rejected = hasRun && stateName === "WAITING_FOR_APPROVAL" &&
      (a.recommendation?.approval_status === "REJECTED" || a.last_decision?.decision === "REJECTED") &&
      a.recommendation?.approval_status !== "PENDING";
    if (rejected) visited.add("rejected");
    const active = rejected ? "rejected" : current;

    AF.nodes.forEach(n => {
      const cls = n.g.classList;
      cls.toggle("is-current", n.id === active);
      cls.toggle("is-done", visited.has(n.id) && n.id !== active);
      cls.toggle("is-pending", !visited.has(n.id));
      cls.toggle("is-broken", n.id === broken);
    });

    let liveEdge = null;
    AF.edges.forEach(e => {
      const never = /never/.test(e.kind || "");
      const both = visited.has(e.f) && visited.has(e.t) && !never;
      const live = both && e.t === active && !(e.f === "replan" && active !== "gate");
      e.g.classList.toggle("done", both && !live);
      e.g.classList.toggle("live", live);
      const neg = /neg/.test(e.kind || ""), loop = /loop/.test(e.kind || "") && !never;
      const mk = live ? (neg ? "neg" : loop ? "loop" : "live") : both ? (loop ? "loop" : neg ? "neg" : "done") : (neg ? "neg" : loop ? "loop" : "base");
      e.g.querySelector(".af-line").setAttribute("marker-end", `url(#af-arrow-${mk})`);
      if (live && (!liveEdge || e.f !== "evIn")) liveEdge = e;
    });
    if (liveEdge && !window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) {
      AF.motion.setAttribute("path", liveEdge.d);
      AF.comet.classList.add("show");
      AF.comet.classList.toggle("danger", /neg/.test(liveEdge.kind || ""));
      try { AF.motion.beginElement(); } catch (_) { /* SMIL not supported */ }
    } else {
      AF.comet.classList.remove("show");
    }

    // Header status
    const order = ["MONITORING", "INVESTIGATING", "GATHERING_EVIDENCE", "ANALYZING", "FORECASTING", "SIMULATING",
      "VALIDATING", "WAITING_FOR_APPROVAL", "EXECUTING", "VERIFYING", "COMPLETED"];
    let stage = order.indexOf(stateName) + 1;
    if (stateName === "REPLANNING") stage = 10;
    if (failed && broken) stage = order.indexOf(Object.keys(AF.stateNode).find(k => AF.stateNode[k] === broken)) + 1;
    stage = Math.max(stage, 1);
    const label = rejected ? "Rejected · waiting" : humanState(stateName);
    setText("#overview-path-current-state", label);
    setText("#af-stage", `Stage ${stage} / 11${a.replan_count ? ` · replans ${a.replan_count}` : ""}`);
    const last = trail[trail.length - 1];
    setText("#af-time", hasRun && last?.time ? last.time : "—");
    const bar = $("#af-progress-bar");
    if (bar) bar.style.width = `${Math.round(stage / 11 * 100)}%`;
    const dot = $("#af-dot");
    if (dot) dot.className = `af-dot ${failed || rejected ? "danger" : stateName === "COMPLETED" ? "success" : stateName === "WAITING_FOR_APPROVAL" ? "gold" : "live"}`;
    const nowEl = $("#af-now");
    if (nowEl) {
      const node = AF.nodes.find(n => n.id === active);
      const event = a.problem?.headline;
      nowEl.innerHTML = hasRun
        ? `<b>${esc(node ? (node.title + (node.title2 ? " " + node.title2 : "")) : label)}</b> — ${esc(node?.info || "")}${event ? `<span>${esc(event)}</span>` : ""}`
        : "The agent is monitoring. Press <b>Run live demo</b> to watch it travel through the flow.";
    }
  }

  function renderOperation(a) {
    const p = a.problem || {};
    setText("#op-problem-title", p.headline || "No active event");
    const facts = safeArray(p.facts);
    const factText = facts.join(" · ");
    const problemText = [
      factText,
      p.event_label || "—",
      p.building_name ? `${p.building_id || "—"} ${p.building_name}` : p.building_id || "campus",
      p.timestamp || "—",
      p.value != null ? `${p.value} ${p.value_meaning || ""}`.trim() : ""
    ].filter(Boolean).join(" · ");
    setText("#op-problem-text", problemText || "Run an analysis first.");
    setText("#op-event-id", p.timestamp ? `${p.timestamp} · ${p.event_label || "Event"}` : "—");
    renderSelectionNotice(a.selection_note);
    renderEvidence(a.evidence);
    renderCandidates(a.candidate_actions);
    renderRecommendation(a);
    renderDecision(a);
    renderVerification(a.verification, a.verification_log);
    renderReplan(a);
    const scope = $("#op-replan-scope");
    if (scope) {
      scope.hidden = !a.recommendation_scope_note;
      scope.textContent = a.recommendation_scope_note || "";
    }
    const constraints = $("#op-constraints");
    if (constraints) {
      constraints.innerHTML = safeArray(a.optimizer_constraints).map(x => `<span>${esc(x)}</span>`).join("");
    }
    const error = $("#op-error");
    if (error) {
      error.hidden = a.state !== "FAILED";
      error.textContent = a.state === "FAILED" ? (a.error || "Agent failed.") : "";
    }
  }

  function renderSelectionNotice(note) {
    const root = $("#op-selection-note");
    if (!root) return;
    root.hidden = !note;
    root.textContent = note || "";
  }

  function renderEvidence(e) {
    const root = $("#op-evidence");
    if (!root) return;
    const vals = [
      ["Energy", e?.energy_kw, "kW"],
      ["HVAC", e?.hvac_kw, "kW"],
      ["Occupancy", e?.occupancy_pct, "%"],
      ["Solar", e?.solar_kw, "kW"],
      ["Historical readings", e?.history_count, "readings"],
      ["Grid status", e?.grid?.status, ""]
    ];
    root.innerHTML = vals.map(([name, value, unit]) => {
      const hvacWarning = name === "HVAC" && num(e?.hvac_kw) != null && num(e?.energy_kw) != null && e.hvac_kw > e.energy_kw;
      const sub = name === "HVAC" && num(e?.hvac_kw) != null && num(e?.energy_kw) != null
        ? `${fmt((e.hvac_kw / e.energy_kw) * 100)}% of metered load`
        : name === "Occupancy" && e?.occupancy_is_average ? "Average across buildings" : "";
      return `<div class="evidence-tile ${hvacWarning ? "warning" : ""}">
        <span>${esc(name)}</span>
        <b>${esc(value == null ? "—" : (unit ? `${fmt(value)} ${unit}` : value))}</b>
        ${sub ? `<small>${esc(sub)}</small>` : ""}
        ${hvacWarning ? `<small class="warning-text">HVAC reading exceeds total load (data quality)</small>` : ""}
      </div>`;
    }).join("");

    const pb = safeArray(e?.per_building);
    const table = $("#op-per-building");
    if (table) {
      table.hidden = pb.length <= 1;
      table.innerHTML = pb.length > 1 ? `
        <div class="table-scroll"><table>
          <thead><tr><th>Building</th><th>Energy kW</th><th>HVAC kW</th><th>Occupancy</th><th>Solar kW</th><th>EV kW</th></tr></thead>
          <tbody>${pb.map(x => `<tr>
            <td>${esc(`${x.building_id} ${x.building_name || ""}`)}</td>
            <td>${esc(fmt(x.energy_kw))}</td><td>${esc(fmt(x.hvac_kw))}</td>
            <td>${esc(fmt(x.occupancy_pct))}%</td><td>${esc(fmt(x.solar_kw))}</td><td>${esc(fmt(x.ev_kw))}</td>
          </tr>`).join("")}</tbody>
        </table></div>` : "";
    }
    const foot = $("#op-evidence-foot");
    if (foot) foot.textContent = e?.reading_time
      ? `Readings at the event hour (${e.reading_time}). History covers the 24 hours up to the event.${e?.grid?.description ? ` ${e.grid.description}` : ""}`
      : "Readings at the event hour (—). History covers the 24 hours up to the event.";
  }

  function whyLabel(verdict) {
    return ({
      failed_constraints: "Why was it rejected?",
      missed_target: "Why was it rejected?",
      not_selected: "Why wasn't it chosen?",
      selected: "Why was it chosen?",
      verified: "What happened?"
    })[verdict] || "Why?";
  }

  function renderCandidates(list) {
    const html = safeArray(list).map((c, i) => {
      const exp = c.explanation;
      const verdict = exp?.verdict;
      const selected = c.is_selected === true;
      const reduction = num(c.estimated_reduction_kw);
      const maxReduction = Math.max(...safeArray(list).map(x => num(x.estimated_reduction_kw) || 0), 1);
      const missed = safeArray(state.agent?.verification_log).some(v =>
        v?.needs_replanning && v?.intended_action === c.action
      );
      const statusTag = missed ? "Missed target" : selected ? "Recommended" : (c.passes_constraints ? "Passes constraints" : "Fails constraints");
      const open = state.openWhy.has(i);
      return `<article class="candidate ${selected ? "selected" : ""}">
        <div class="candidate-top">
          <span class="candidate-name">${esc(c.label || c.action || "—")}</span>
          <span class="candidate-score">Score ${esc(fmt(c.optimization_score, 2))}</span>
        </div>
        <div class="candidate-meta">
          <span class="tag">${esc(statusTag)}</span>
          <span class="tag">${esc(fmt(reduction))} kW</span>
          <span class="tag">${esc(fmt(c.reduction_percent))}%</span>
          <span class="tag">Load → ${esc(fmt(c.new_predicted_load))} kW</span>
          <span class="tag">Battery ${esc(fmt(c.battery_soc_percent))}%</span>
          <span class="tag">EV ${esc(fmt(c.ev_load_kw))} kW</span>
        </div>
        <div class="bar"><i style="width:${Math.max(0, Math.min(100, ((reduction || 0) / maxReduction) * 100))}%"></i></div>
        ${verdict ? `<button class="why-btn" type="button" data-why="${i}" aria-expanded="${open}">${esc(whyLabel(verdict))}</button>
          <div class="why-panel" ${open ? "" : "hidden"}>
            <span class="tag">${esc(exp.title || verdict)}</span>
            <ul>${safeArray(exp.points).map(x => `<li>${esc(x)}</li>`).join("")}</ul>
            ${safeArray(c.constraint_checks).length ? `<div class="constraint-list">${c.constraint_checks.map(x =>
        `<div><b>${!x.applies ? "–" : x.passed ? "✓" : "✗"}</b><span>${esc(x.detail || x.rule || "Constraint")}</span></div>`
      ).join("")}</div>` : ""}
            ${exp.comparison ? `<div class="comparison"><table><thead><tr><th></th><th>This</th><th>Selected</th></tr></thead><tbody>
              <tr><td>Reduction × weight</td><td>${esc(fmt(exp.comparison.this?.reduction_term, 2))}</td><td>${esc(fmt(exp.comparison.selected?.reduction_term, 2))}</td></tr>
              <tr><td>Disruption rank × penalty</td><td>−${esc(fmt(exp.comparison.this?.penalty_term, 2))}</td><td>−${esc(fmt(exp.comparison.selected?.penalty_term, 2))}</td></tr>
              <tr><td>Score</td><td>${esc(fmt(exp.comparison.this?.score, 2))}</td><td>${esc(fmt(exp.comparison.selected?.score, 2))}</td></tr>
            </tbody></table></div>` : ""}
            <p class="why-basis">${esc(exp.basis || "")}</p>
          </div>` : ""}
      </article>`;
    }).join("") || `<div class="empty-state">No candidate actions available. Run an analysis first.</div>`;

    const roots = [$("#op-candidates"), $("#twin-candidates")].filter(Boolean);
    roots.forEach(root => root.innerHTML = html);
    roots.forEach(root => $$(".why-btn", root).forEach(btn => btn.addEventListener("click", () => {
      const i = Number(btn.dataset.why);
      state.openWhy.has(i) ? state.openWhy.delete(i) : state.openWhy.add(i);
      renderCandidates(state.agent?.candidate_actions || []);
    })));
  }

  function renderRecommendation(a) {
    const root = $("#op-recommendation");
    const r = a.recommendation;
    if (!root) return;
    if (!r) {
      root.innerHTML = `<div class="empty-state">Waiting for simulation results.</div>`;
      return;
    }
    const executing = ["EXECUTING", "VERIFYING"].includes(a.state);
    const action = executing && a.last_decision?.action
      ? (safeArray(a.candidate_actions).find(x => x.action === a.last_decision.action) || r)
      : r;
    root.innerHTML = `
      <div class="recommendation-title">${esc(action.label || action.action || "—")}</div>
      <div class="candidate-meta">
        <span class="tag">${esc(fmt(action.estimated_reduction_kw))} kW</span>
        <span class="tag">Load → ${esc(fmt(action.new_predicted_load))} kW</span>
        <span class="tag">${esc(r.approval_status || "—")}</span>
        <span class="tag">${r.source === "replanning" ? "Alternative after replanning" : "From optimizer"}</span>
      </div>
      <ul class="reason-list">${safeArray(r.reason?.points).map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      <p class="reason-basis">${esc(r.reason?.basis || "Assembled from recorded outputs, not generated text.")}</p>
    `;
  }

  function renderDecision(a) {
    const status = $("#op-decision-state");
    const text = $("#op-decision-text");
    if (!status || !text) return;
    status.textContent = humanState(a.state);
    if (a.state === "WAITING_FOR_APPROVAL" && a.replanned) {
      text.textContent = "Human approval required.";
    } else if (a.last_decision?.decision === "REJECTED") {
      text.textContent = `Rejected at ${a.last_decision.time}. Nothing was executed.`;
    } else if (a.state === "EXECUTING") {
      text.textContent = "Simulated execution in progress. No equipment is being controlled.";
    } else if (a.state === "VERIFYING") {
      text.textContent = "Verification is comparing the simulated outcome with the expected target.";
    } else {
      text.textContent = approvalText(a);
    }
  }

  // A replanned proposal that is still waiting for a human decision.
  function replanPending(a) {
    return Boolean(a && a.replanned && a.state === "WAITING_FOR_APPROVAL" && a.verification
      && a.recommendation?.approval_status !== "REJECTED");
  }

  function renderReplan(a) {
    // The dialog must not depend on the in-page callout: #op-replan was once
    // missing from operations.html, this function returned early, and the
    // replanning dialog silently never appeared.
    const v = a.verification;
    const show = replanPending(a);
    const root = $("#op-replan");
    if (root) {
      root.hidden = !show;
      if (show) root.innerHTML = `
        <b>Replanning round ${esc(a.replan_count)}</b>
        <p>${esc(v.intended_label || "Previous action")} reached ${esc(fmt(v.performance_ratio_percent))}% of its expected reduction (target ${esc(fmt(v.threshold_percent))}%). The agent proposes <strong>${esc(a.recommendation?.label || "an alternative")}</strong>, which needs your approval.</p>
        <button class="text-link" id="review-replan" type="button">${esc(tr("replan_review", "Review the replanning decision"))} →</button>`;
      $("#review-replan")?.addEventListener("click", () => reopenReplanDialog());
    }
    // Pops up by itself only on Operations, where the decision is made.
    if (show && page === "operations") showReplanDialog(a);
    else if (!show) closeReplanDialog();
  }

  function renderVerification(v, log) {
    const root = $("#op-verification");
    if (!root) return;
    if (!v) {
      root.className = "verification-result empty-state";
      root.textContent = "No execution has been verified yet.";
      return;
    }
    const ok = v.verification_status === "SUCCESS";
    root.className = `verification-result ${ok ? "pass" : "fail"}`;
    root.innerHTML = `
      <div class="verification-main-title">${ok ? "Verified" : "Target not met. The agent is replanning."}</div>
      <div class="verification-grid">
        <div><span>Expected</span><b>${esc(fmt(v.expected_reduction_kw))} kW</b></div>
        <div><span>Actual</span><b>${esc(fmt(v.achieved_reduction_kw))} kW</b></div>
        <div><span>Performance</span><b>${esc(fmt(v.performance_ratio_percent))}%</b></div>
        <div><span>Verified action</span><b>${esc(v.verified_label || "—")}</b></div>
      </div>
      <div class="threshold-marker">Threshold ${esc(fmt(v.threshold_percent))}%</div>
      ${ok ? "" : `<button class="secondary-btn diagnose-btn" id="diagnose-shortfall" type="button">Why did it fall short?</button>
      <div id="shortfall-diagnosis" hidden></div>`}
      ${v.action_mismatch ? `<div class="warning-text">This verification record belongs to ${esc(v.verified_label || "the verified action")}.</div>` : ""}
      ${safeArray(log).length > 1 ? `<details class="verification-history"><summary>Verification history</summary>${safeArray(log).map(x =>
      `<div class="timeline-row"><b>${esc(x.intended_label || "—")}</b><span>${esc(x.time || "—")} · ${esc(fmt(x.achieved_reduction_kw))} / ${esc(fmt(x.expected_reduction_kw))} kW · ${esc(x.verification_status || "—")}</span></div>`
    ).join("")}</details>` : ""}
    `;

    $("#diagnose-shortfall", root)?.addEventListener("click", () => loadShortfallDiagnosis());
  }

  // =========================================================
  // SHORTFALL DIAGNOSIS
  // =========================================================
  //
  // "It reached 77.9% of target" says nothing an operator can act on. This
  // asks the server to compare the hour the action ran in against the level
  // the plan assumed, and shows the measured differences.

  async function loadShortfallDiagnosis() {
    const box = $("#shortfall-diagnosis");
    const button = $("#diagnose-shortfall");
    if (!box) return;

    if (!box.hidden) {
      box.hidden = true;
      if (button) button.textContent = "Why did it fall short?";
      return;
    }

    box.hidden = false;
    box.className = "diagnosis-panel";
    box.innerHTML = `<div class="empty-state">Reading the conditions during that hour…</div>`;
    if (button) { button.disabled = true; button.textContent = "Reading…"; }

    try {
      renderShortfallDiagnosis(await api("/api/verification/diagnosis"));
      if (button) button.textContent = "Hide the diagnosis";
    } catch (e) {
      box.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
      if (button) button.textContent = "Why did it fall short?";
    } finally {
      if (button) button.disabled = false;
    }
  }

  function renderShortfallDiagnosis(d) {
    renderDiagnosisInto($("#shortfall-diagnosis"), d);
  }

  /**
   * Draw a diagnosis into any container: the Verification panel and the
   * replanning dialog show the same thing, so they share one renderer rather
   * than two copies that drift.
   */
  function renderDiagnosisInto(box, d) {
    if (!box || !d) return;

    const drivers = safeArray(d.drivers);
    const held = safeArray(d.held);

    box.innerHTML = `
      <div class="diagnosis-head">
        <b>${esc(d.headline || "")}</b>
        <span>Planned at ${esc(d.plan_hour)} · ran at ${esc(d.execution_hour)}</span>
      </div>

      ${drivers.length ? `<ul class="diagnosis-list">${drivers.map(x => `
        <li class="${x.controllable === false ? "external" : ""}">
          <div class="diagnosis-row">
            <b>${esc(x.label)}</b>
            <span class="diagnosis-delta">+${esc(fmt(x.delta_kw))} kW</span>
          </div>
          <p>${esc(x.detail)}</p>
          ${x.context ? `<p class="diagnosis-context">${esc(x.context)}</p>` : ""}
        </li>`).join("")}</ul>`
      : `<p class="diagnosis-none">Every component of the action held to its plan in the readings for that hour.</p>`}

      ${held.length ? `<div class="diagnosis-held">${held.map(x =>
        `<span>✓ ${esc(x.label)}</span>`).join("")}</div>` : ""}

      <p class="diagnosis-coverage">${esc(d.coverage || "")}</p>`;
  }

  function renderTwin(a) {
    const p = a.problem || {};
    setText("#twin-event", p.timestamp ? `${p.timestamp} · ${p.event_label || "Event"}` : "No active event");
    setText("#twin-selected", a.recommendation?.label || "No action selected");
    const meta = $("#twin-selected-meta");
    if (meta) meta.innerHTML = a.recommendation ? `
      <div><span>Reduction</span><b>${esc(fmt(a.recommendation.estimated_reduction_kw))} kW</b></div>
      <div><span>New predicted load</span><b>${esc(fmt(a.recommendation.new_predicted_load))} kW</b></div>
    ` : `<div><span>Status</span><b>Run an analysis first</b></div>`;
    renderCandidates(a.candidate_actions);
    refreshTwinLabFromAgent(a);
  }

  // =========================================================
  // DIGITAL TWIN — INTERACTIVE WHAT-IF EXPERIMENT LAB
  // Pure client-side. Mirrors simulator.py's math exactly:
  //   HVAC reduction  = hvac_load * cut%       (agent uses 15%)
  //   EV   reduction  = ev_load   * shift%     (agent uses 80%)
  //   Batt reduction  = discharge kW           (max 25, needs SOC > 30)
  // Nothing here is sent to the backend or executed.
  // =========================================================
  const twinLab = {
    ready: false,
    campus: null,          // { predicted, hvac, ev, soc }
    benchmark: null,       // { kw, pct, label }
    factors: { tariff_jod_per_kwh: 0.14, grid_co2_kg_per_kwh: 0.55 },
    gaugeMax: 20
  };

  const HVAC_DEFAULT = 15, EV_DEFAULT = 80, BATT_MAX = 25, MIN_BATTERY_SOC = 30;

  async function setupTwinLab() {
    // Single-source the money/carbon factors; fall back silently on failure.
    try {
      const f = await api("/api/impact/factors");
      if (f?.tariff_jod_per_kwh) twinLab.factors = f;
    } catch (_) { /* defaults stand */ }

    ["#lab-hvac", "#lab-ev", "#lab-batt"].forEach(sel => {
      $(sel)?.addEventListener("input", renderTwinLab);
    });
    $("#lab-match")?.addEventListener("click", () => setLabControls(HVAC_DEFAULT, EV_DEFAULT, BATT_MAX));
    $("#lab-zero")?.addEventListener("click", () => setLabControls(0, 0, 0));
  }

  function setLabControls(hvac, ev, batt) {
    const h = $("#lab-hvac"), e = $("#lab-ev"), b = $("#lab-batt");
    if (h) h.value = hvac;
    if (e) e.value = ev;
    if (b) b.value = batt;
    renderTwinLab();
  }

  // Read campus state + benchmark out of the current agent snapshot.
  function refreshTwinLabFromAgent(a) {
    if (page !== "digital_twin") return;
    const empty = $("#twin-lab-empty"), body = $("#twin-lab-body");
    const cands = safeArray(a?.candidate_actions);
    const rec = a?.recommendation;
    const c0 = cands[0];
    const predicted = num(rec?.original_predicted_load) ?? num(c0?.original_predicted_load);

    if (!c0 || predicted === null || predicted <= 0) {
      twinLab.ready = false;
      if (empty) empty.hidden = false;
      if (body) body.hidden = true;
      return;
    }

    twinLab.campus = {
      predicted,
      hvac: num(c0.hvac_load_kw) ?? 0,
      ev: num(c0.ev_load_kw) ?? 0,
      soc: num(c0.battery_soc_percent) ?? 0
    };
    twinLab.benchmark = rec ? {
      kw: num(rec.estimated_reduction_kw) ?? 0,
      pct: num(rec.reduction_percent) ?? 0,
      label: rec.label || "Agent solution"
    } : null;

    // Stable gauge ceiling: the most this event could shed with every knob
    // maxed, so the needle scale does not shift while the user drags.
    const maxKw = twinLab.campus.hvac * 0.30 + twinLab.campus.ev * 1.0 + BATT_MAX;
    const maxPct = (maxKw / predicted) * 100;
    twinLab.gaugeMax = Math.max(10, maxPct, twinLab.benchmark?.pct || 0) * 1.05;

    twinLab.ready = true;
    if (empty) empty.hidden = true;
    if (body) body.hidden = false;

    setText("#lab-hvac-load", fmt(twinLab.campus.hvac));
    setText("#lab-ev-load", fmt(twinLab.campus.ev));
    setText("#lab-batt-soc", `${fmt(twinLab.campus.soc)}%`);
    setText("#lab-benchmark-pct", twinLab.benchmark ? `${fmt(twinLab.benchmark.pct)}%` : "—");
    renderTwinLab();
  }

  function computeTwinLab() {
    const c = twinLab.campus;
    const hvacPct = num($("#lab-hvac")?.value) ?? 0;
    const evPct = num($("#lab-ev")?.value) ?? 0;
    const battKw = num($("#lab-batt")?.value) ?? 0;

    const hvacKw = c.hvac * hvacPct / 100;
    const evKw = c.ev * evPct / 100;
    const battKwEff = battKw; // raw; constraint feasibility flagged separately
    const totalKw = Math.max(0, hvacKw + evKw + battKwEff);
    const pct = c.predicted > 0 ? (totalKw / c.predicted) * 100 : 0;
    const newLoad = Math.max(0, c.predicted - totalKw);

    // Constraint feasibility (same rules as optimizer.py).
    const warnings = [];
    if (battKw > 0 && c.soc <= MIN_BATTERY_SOC)
      warnings.push(`Battery SOC ${fmt(c.soc)}% is at or below ${MIN_BATTERY_SOC}% — the optimizer would reject this discharge.`);
    if (evPct > 0 && c.ev <= 0)
      warnings.push("No active EV charging this hour — shifting EV load has no effect here.");

    return { hvacPct, evPct, battKw, hvacKw, evKw, battKw2: battKwEff, totalKw, pct, newLoad, warnings };
  }

  function renderTwinLab() {
    if (!twinLab.ready || page !== "digital_twin") return;
    const r = computeTwinLab();
    const f = twinLab.factors;

    // Slider value labels
    setText("#lab-hvac-val", `${r.hvacPct}%`);
    setText("#lab-ev-val", `${r.evPct}%`);
    setText("#lab-batt-val", `${r.battKw} kW`);

    // Outcome numbers
    setText("#lab-reduction-pct", `${r.pct.toFixed(1)}%`);
    setText("#lab-reduction-kw", `${r.totalKw.toFixed(1)} kW`);
    setText("#lab-new-load", `${r.newLoad.toFixed(1)} kW`);
    setText("#lab-jod", `${(r.totalKw * f.tariff_jod_per_kwh).toFixed(2)} JOD`);
    setText("#lab-co2", `${(r.totalKw * f.grid_co2_kg_per_kwh).toFixed(1)} kg`);

    // Gauge
    updateGauge(r.pct, twinLab.benchmark?.pct || 0);

    // Verdict
    renderLabVerdict(r);
  }

  // Needle/target on a 180° arc (center 100,100, r used for marks).
  function polar(valuePct, len) {
    const frac = Math.max(0, Math.min(1, valuePct / twinLab.gaugeMax));
    const ang = Math.PI - frac * Math.PI; // 180° (left) -> 0° (right)
    return { x: 100 + len * Math.cos(ang), y: 100 - len * Math.sin(ang) };
  }

  function updateGauge(userPct, benchPct) {
    const fill = $("#gauge-fill"), needle = $("#gauge-needle"), target = $("#gauge-target");
    const fillFrac = Math.max(0, Math.min(1, userPct / twinLab.gaugeMax));
    if (fill) fill.setAttribute("stroke-dasharray", `${(fillFrac * 100).toFixed(2)} 100`);
    if (needle) { const p = polar(userPct, 66); needle.setAttribute("x2", p.x.toFixed(1)); needle.setAttribute("y2", p.y.toFixed(1)); }
    if (target) {
      const p = polar(benchPct, 78), base = polar(benchPct, 40);
      target.setAttribute("x1", base.x.toFixed(1)); target.setAttribute("y1", base.y.toFixed(1));
      target.setAttribute("x2", p.x.toFixed(1)); target.setAttribute("y2", p.y.toFixed(1));
      target.style.opacity = benchPct > 0 ? "1" : "0";
    }
  }

  function renderLabVerdict(r) {
    const root = $("#lab-verdict");
    if (!root) return;
    const warns = r.warnings.map(w => `<div class="lab-warn">⚠ ${esc(w)}</div>`).join("");
    const bench = twinLab.benchmark;

    let cls = "neutral", head = "Experiment running", body = "Adjust the controls to shed load.";
    if (r.totalKw <= 0) {
      cls = "neutral"; head = "No action selected"; body = "Every control is at zero, so nothing changes.";
    } else if (bench && bench.kw > 0) {
      const ratio = r.totalKw / bench.kw;
      if (ratio >= 0.99) {
        cls = "good"; head = "Useful — matches or beats the agent";
        body = `Your mix sheds ${r.totalKw.toFixed(1)} kW, at or above the agent's best (${bench.label}, ${bench.kw.toFixed(1)} kW).`;
      } else if (ratio >= 0.9) {
        cls = "warn"; head = "Close, but below the agent's best";
        body = `Your mix sheds ${r.totalKw.toFixed(1)} kW — ${(ratio * 100).toFixed(0)}% of the agent's ${bench.kw.toFixed(1)} kW (${bench.label}).`;
      } else {
        cls = "bad"; head = "Not enough on its own";
        body = `Your mix sheds ${r.totalKw.toFixed(1)} kW — only ${(ratio * 100).toFixed(0)}% of the agent's best (${bench.kw.toFixed(1)} kW, ${bench.label}). Turn up a control or add another.`;
      }
    } else {
      cls = "neutral"; head = "No agent benchmark yet";
      body = `Your mix sheds ${r.totalKw.toFixed(1)} kW. Run an analysis to compare against the agent's chosen action.`;
    }

    root.className = `twin-verdict ${cls}`;
    root.innerHTML = `<div class="lab-verdict-head">${esc(head)}</div><div class="lab-verdict-body">${esc(body)}</div>${warns}`;
  }

  // Model self-audit (idea #3): how many anomalies are just holiday blindness.
  async function loadHolidayAudit() {
    const root = $("#holiday-audit");
    if (!root) return;
    try {
      const d = await api("/api/anomaly/holiday-audit");
      const rows = safeArray(d.sample).slice(0, 3).map(s =>
        `<div class="insight-row"><span>${esc(s.timestamp)} · ${esc(s.building_id)}</span><b>${esc(fmt(s.residual_percent))}%</b></div>`).join("");
      root.innerHTML = `
        <div class="insight-stat"><b>${esc(d.in_window)}/${esc(d.total_anomalies)}</b><span>anomalies in the ${esc(d.holiday_window)} shutdown (${esc(fmt(d.share_percent))}%)</span></div>
        <p class="insight-text">${esc(d.finding)}</p>
        ${rows ? `<div class="insight-rows">${rows}</div>` : ""}
        <p class="insight-note">${esc(d.recommendation)}</p>`;
    } catch (e) {
      root.innerHTML = `<div class="empty-state">Self-audit unavailable: ${esc(e.message)}</div>`;
    }
  }

  // Learned confidence (idea #2): per-action success rate from history.
  async function loadAgentLearning() {
    const root = $("#agent-learning");
    if (!root) return;
    try {
      const d = await api("/api/agent/learning");
      const rows = safeArray(d.actions).map(a => {
        const pct = num(a.success_rate_percent) || 0;
        const cls = pct >= 75 ? "good" : pct >= 50 ? "warn" : "bad";
        return `<div class="conf-row">
          <span class="conf-label">${esc(a.label)}</span>
          <div class="conf-bar"><i class="conf-${cls}" style="width:${Math.max(3, Math.min(100, pct))}%"></i></div>
          <b>${esc(fmt(pct))}%</b></div>`;
      }).join("");
      root.innerHTML = `
        <div class="insight-stat"><b>${esc(fmt(d.overall_success_percent))}%</b><span>overall success across ${esc(d.total_attempts)} executions</span></div>
        <div class="conf-list">${rows}</div>
        <p class="insight-note">${esc(d.note)}</p>`;
    } catch (e) {
      root.innerHTML = `<div class="empty-state">Learning unavailable: ${esc(e.message)}</div>`;
    }
  }

  function renderActivitySession(a) {
    setText("#activity-state", humanState(a.state));
    setText("#activity-event", a.problem?.timestamp ? `${a.problem.timestamp} · ${a.problem.event_label || "Event"}` : "—");
    setText("#activity-approval", approvalText(a));
  }

  async function runAgent(event = null) {
    if (state.requestBusy || state.replaying) return;
    const oldTrail = safeArray(state.agent?.trail);
    state.openWhy.clear();

    // A new analysis re-arms the replanning dialog. Without this, postponing or
    // deciding round 1 on one event left replanDialogDismissed at 1, and the
    // next event that reached round 1 never raised the dialog at all: same
    // round number, still marked as already seen.
    resetReplanDialogState();

    setBusy(true);
    try {
      const body = event
        ? { timestamp: event.timestamp, building_id: event.building_id, event_type: event.event_type }
        : { building: state.building, scenario: $("#demo-path")?.value || "auto" };
      const snapshot = await api("/api/agent/run", {
        method: "POST", body: JSON.stringify(body)
      });
      state.agent = snapshot;

      // Analyze pressed on another page: continue on Operations, where the
      // lifecycle and the decision gate live. `event` here is runAgent's own
      // parameter, not the global window.event.
      if (event && page !== "operations") {
        const href = document.querySelector('.nav-item[href$="operations"]')?.getAttribute("href");
        window.location.assign(href || "/operations");
        return;
      }

      await replayNewTrail(oldTrail, snapshot.trail || []);
      toast(snapshot.state === "WAITING_FOR_APPROVAL" ? "Analysis complete. Human approval required." : "Analysis completed.");
    } catch (e) {
      toast(`Agent: ${e.message}`);
    } finally {
      setBusy(false);
      setDecisionButtons();
    }
  }

  async function replayNewTrail(oldTrail, newTrail) {
    state.replaying = true;
    setDecisionButtons();
    const oldKeys = new Set(oldTrail.map(x => `${x.state}|${x.time}`));
    const fresh = safeArray(newTrail).filter(x => !oldKeys.has(`${x.state}|${x.time}`));
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (!fresh.length || reduceMotion) {
      renderAgentEverywhere();
      state.replaying = false;
      setDecisionButtons();
      return;
    }
    for (const entry of fresh) {
      const partial = { ...state.agent, state: entry.state };
      renderLifecycle(entry.state);
      renderOperation(partial);
      renderTwin(partial);
      await new Promise(r => setTimeout(r, 340));
    }
    renderAgentEverywhere();
    state.replaying = false;
    setDecisionButtons();
  }

  async function decision(path) {
    if (state.requestBusy || state.replaying) return;
    const oldTrail = safeArray(state.agent?.trail);
    setBusy(true);
    try {
      const snapshot = await api(`/api/agent/${path}`, { method: "POST", body: "{}" });
      state.agent = snapshot;

      await replayNewTrail(oldTrail, snapshot.trail || []);
      if (path === "approve") {
        if (snapshot.state === "WAITING_FOR_APPROVAL" && snapshot.replanned) toast("Target not met. The agent proposes an alternative.");
        else if (snapshot.state === "COMPLETED") toast("Approved. Simulated execution verified.");
      } else {
        toast("Rejected. Nothing was executed.");
      }
      if (page === "verification") await loadVerification();
      if (page === "activity") await loadActivity();
      await loadDashboard();
    } catch (e) {
      toast(`Decision: ${e.message}`);
    } finally {
      setBusy(false);
      setDecisionButtons();
    }
  }

  async function loadVerification() {
    try {
      state.verification = await api("/api/verification");
      const v = state.verification.latest;
      setText("#ver-status", v ? (v.verification_status === "SUCCESS" ? "Verified" : "Target not met") : "—");
      setText("#ver-expected", v ? `${fmt(v.expected_reduction_kw)} kW` : "—");
      setText("#ver-observed", v ? `${fmt(v.achieved_reduction_kw)} kW` : "—");
      setText("#ver-performance", v ? `${fmt(v.performance_ratio_percent)}%` : "—");
      setText("#ver-threshold", v ? `${fmt(v.threshold_percent)}%` : "—");
      const main = $("#verification-main");
      if (main) {
        main.className = `verification-card ${v?.verification_status === "SUCCESS" ? "pass" : v ? "fail" : ""}`;
        main.innerHTML = v ? `
          <div class="verification-main-title">${v.verification_status === "SUCCESS" ? "Verified" : "Target not met"}</div>
          <div class="verification-main-sub">${esc(v.intended_label || "—")} → ${esc(v.verified_label || "—")}</div>
          <div class="verification-grid">
            <div><span>Expected</span><b>${esc(fmt(v.expected_reduction_kw))} kW</b></div>
            <div><span>Actual</span><b>${esc(fmt(v.achieved_reduction_kw))} kW</b></div>
            <div><span>Performance</span><b>${esc(fmt(v.performance_ratio_percent))}%</b></div>
            <div><span>Threshold</span><b>${esc(fmt(v.threshold_percent))}%</b></div>
          </div>
          ${v.action_mismatch ? `<div class="warning-text">This record belongs to ${esc(v.verified_label || "the verified action")}.</div>` : ""}
        ` : `<div class="empty-state">No verification result available yet.</div>`;
      }
      const history = $("#verification-history");
      if (history) history.innerHTML = safeArray(state.verification.log).map(x =>
        `<div class="timeline-row"><b>${esc(x.intended_label || "—")}</b><span>${esc(x.time || "—")} · ${esc(fmt(x.expected_reduction_kw))} / ${esc(fmt(x.achieved_reduction_kw))} kW · ${esc(x.verification_status || "—")}</span></div>`
      ).join("") || `<div class="empty-state">No verification history.</div>`;
    } catch (e) {
      toast(`Verification: ${e.message}`);
    }
  }

  async function loadActivity() {
    try {
      const d = await api("/api/agent/history");
      const root = $("#activity-history");
      if (root) root.innerHTML = safeArray(d.history).slice().sort((a, b) => String(a.time).localeCompare(String(b.time))).map(x =>
        `<div class="timeline-row ${/reject|fail/i.test(x.message || "") ? "danger" : /wait/i.test(x.state || "") ? "waiting" : /approv/i.test(x.message || "") ? "success" : ""}">
          <b>${esc(humanState(x.state))}</b><span>${esc(x.time || "—")} · ${esc(x.message || "—")}</span>
        </div>`).join("") || `<div class="empty-state">No activity recorded.</div>`;
    } catch (e) { toast(`Activity: ${e.message}`); }
  }

  // Keeps dates, times and "607.9 kW" readable inside right-to-left (Arabic) text.
  function ltrNumbers(html) {
    return html.replace(/(?<![&#\w])(\d[\d.,:\/\-]*(?:\s?(?:→|->)\s?\d[\d.,:\/\-]*)?(?:\s?(?:kWh|kW|W\/m²|°C|%))?)/g, '<span dir="ltr">$1</span>');
  }

  function renderRagSources(sources) {
    return safeArray(sources).map((s, i) => `
      <details class="rag-source${s.kind === "data" ? " data-source" : ""}" ${s.kind === "data" ? "" : "open"}>
        <summary>[${esc(s.ref ?? i + 1)}] ${esc(s.title || s.document || "Source")}</summary>
        <div><b>${esc(s.section || "—")}</b> · ${esc(s.document || "—")}</div>
        <p>${esc(s.excerpt || "")}</p>
      </details>`).join("");
  }

  async function askRag(question) {
    if (!question) return;
    const root = $("#rag-answer");
    if (root) root.innerHTML = `<div class="empty-state">Retrieving…</div>`;
    try {
      const d = await api("/api/rag/query", {
        method: "POST",
        body: JSON.stringify({ question, include_live_context: Boolean($("#rag-context")?.checked) })
      });
      const modeText = d.mode === "llm"
        ? `Generated by ${d.model || "the configured model"} from ${d.data ? "project data" : "retrieved sections"}${d.data && safeArray(d.sources).length > 1 ? " and documents" : ""}`
        : d.mode === "data"
          ? "Computed from the project dataset"
          : d.mode === "extractive"
            ? "Quoted from retrieved sections"
            : "No matching data or document";
      const rtl = /[\u0600-\u06FF]/.test(question) ? ' dir="auto"' : "";
      const facts = d.data && safeArray(d.data.facts).length
        ? `<section class="rag-data"><b>Project data · computed from energy.db</b><ul${rtl}>${
            safeArray(d.data.facts).map(f => `<li class="${/^\s/.test(f) ? "sub" : ""}">${rtl ? ltrNumbers(esc(String(f).trim())) : esc(String(f).trim())}</li>`).join("")
          }</ul></section>`
        : "";
      if (root) root.innerHTML = `
        <div class="rag-mode tag">${esc(modeText)}</div>
        <div class="rag-content"${rtl}>${(rtl ? ltrNumbers(esc(d.answer || "—")) : esc(d.answer || "—")).replace(/\[(<span dir="ltr">)?(\d+|D)(<\/span>)?\]/g, '<mark>[$2]</mark>')}</div>
        ${d.notice ? `<div class="notice">${esc(d.notice)}</div>` : ""}
        ${facts}
        ${d.live_context ? `<section class="live-context"><b>Live operational data, from the agent (not from the knowledge base)</b><pre>${esc(JSON.stringify(d.live_context, null, 2))}</pre></section>` : ""}
        <div class="rag-sources">${renderRagSources(d.sources)}</div>`;
      setText("#rag-status", modeText);
    } catch (e) {
      if (root) root.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
    }
  }

  function bindGlobal() {
    const sel = $("#building-select");
    if (sel) {
      sel.value = state.building;
      sel.addEventListener("change", async () => {
        setBuilding(sel.value);
        await Promise.all([loadDashboard(), loadEnergy(page === "energy" ? "energy-chart" : "overview-chart"), loadEvents(page === "overview" ? "#overview-events" : "#energy-events")]);
        if (page === "energy" || page === "history") await executeHistoryQuery();
        if (page === "operations" || page === "digital_twin" || page === "activity") await loadAgent();
      });
    }
    const menu = $("#mobile-menu");
    if (menu) menu.addEventListener("click", () => $("#sidebar")?.classList.toggle("open"));
  }

  function setBuilding(value) {
    state.building = value;
    localStorage.setItem("smart_energy_building", value);
  }

  async function initPage() {
    bindGlobal();
    bindReplanDialog();
    await loadHealth();
    await loadDashboard();

    if (page === "overview") {
      $("#show-anomalies")?.addEventListener("click", () => toggleAnomalies());
      $("#close-anomalies")?.addEventListener("click", () => {
        const panel = $("#anomaly-panel");
        if (panel) panel.hidden = true;
      });
      $$("#anomaly-filters .seg").forEach(btn => btn.addEventListener("click", () => {
        $$("#anomaly-filters .seg").forEach(other => other.classList.toggle("active", other === btn));
        anomalyState.kind = btn.dataset.kind;
        renderAnomalies();
      }));
      setupOverviewEvents();
      await Promise.all([loadEnergy("overview-chart"), loadEvents("#overview-events"), loadAgent(), loadImpactFactors()]);
      startLiveStream();
    } else if (page === "history") {
      await initHistoryPage();
    } else if (page === "energy") {
      await Promise.all([loadEnergy("energy-chart"), loadEvents("#energy-events")]);
      startLiveStream();
      await initHistoryPage();
      $$(".seg").forEach(btn => btn.addEventListener("click", () => {
        btn.classList.toggle("active");
        const key = btn.dataset.series;
        const targetChart = state.charts?.["energy-chart"] || state.chart;
        const ds = targetChart?.data?.datasets?.find(x => x.key === key);
        if (ds) { ds.hidden = !btn.classList.contains("active"); targetChart.update(); }
      }));
    } else if (page === "operations") {
      const run = $("#run-agent");
      if (run) run.addEventListener("click", () => runAgent());
      // While a replanned proposal is pending, the decision buttons reopen the
      // replanning dialog (also after "Decide later"), so the operator sees why
      // the first action fell short before approving the alternative.
      $("#approve-agent")?.addEventListener("click", e => {
        if (e.currentTarget.dataset.role === "verification") goToVerification();
        else if (replanPending(state.agent)) reopenReplanDialog();
        else decision("approve");
      });
      $("#reject-agent")?.addEventListener("click", () => {
        if (replanPending(state.agent)) reopenReplanDialog();
        else decision("reject");
      });
      $("#explain-forecast")?.addEventListener("click", () => loadExplanation());
      $("#download-pdf")?.addEventListener("click", () => downloadReport());
      await loadEvents("#op-events");
      await loadAgent();
    } else if (page === "digital_twin") {
      await setupTwinLab();
      loadHolidayAudit();
      loadAgentLearning();
      await loadAgent();
      startLiveStream();
    } else if (page === "verification") {
      // The decision flowchart lives here: it needs the agent's live state.
      await Promise.all([loadVerification(), loadAgent()]);
    } else if (page === "knowledge") {
      $("#rag-form")?.addEventListener("submit", e => {
        e.preventDefault();
        askRag($("#rag-input")?.value.trim());
      });
      // Quick questions are asked in the interface language.
      $$(".quick-questions button").forEach(btn => btn.addEventListener("click", () => {
        const ar = document.documentElement.getAttribute("lang") === "ar";
        askRag(ar && btn.dataset.questionAr ? btn.dataset.questionAr : btn.dataset.question);
      }));
      await loadAgent();
    } else if (page === "activity") {
      $("#reset-agent")?.addEventListener("click", async () => {
        if (state.requestBusy) return;
        setBusy(true);
        try {
          state.agent = await api("/api/agent/reset", { method: "POST", body: "{}" });
          resetReplanDialogState();
          closeReplanDialog();
          toast("Agent session reset.");
          await loadActivity();
          renderAgentEverywhere();
        } catch (e) { toast(`Reset: ${e.message}`); }
        finally { setBusy(false); }
      });
      await Promise.all([loadActivity(), loadEvents("#activity-events"), loadAgent()]);
    }
  }

  // =========================================================
  // LIVE OPERATIONAL SIMULATION STREAM ENGINE
  // =========================================================

  let lastStreamFetchTime = Date.now();
  let liveStreamWarned = false;

  function startLiveStream() {
    updateLiveStream();
    setInterval(updateLiveStream, 5000);
    setInterval(updateUpdatedTicker, 1000);
  }

  function updateUpdatedTicker() {
    const elapsed = Math.floor((Date.now() - lastStreamFetchTime) / 1000);
    const val = Math.max(0, elapsed);
    // Update whichever "Xs ago" span exists on the current page
    const ids = ["#live-updated-ago", "#live-updated-ago-energy", "#live-updated-ago-dt"];
    ids.forEach(id => { const el = $(id); if (el) el.textContent = val; });
  }

  async function updateLiveStream() {
    if (page === "history") return;
    try {
      const live = await api(`/api/live/stream?building=${encodeURIComponent(state.building)}`);
      lastStreamFetchTime = Date.now();
      liveStreamWarned = false;
      renderLiveStream(live);
    } catch (e) {
      // The stream must not interrupt the page, but swallowing the error
      // silently leaves a stalled dashboard with no way to tell why. Log it,
      // and say so on screen once rather than on every 5s tick.
      console.error("Live stream failed:", e);
      if (!liveStreamWarned) {
        liveStreamWarned = true;
        toast(`Live stream: ${e.message}`);
        setText("#live-op-time", "Stream unavailable");
        setText("#live-op-time-energy", "Stream unavailable");
        setText("#dt-op-time", "Stream unavailable");
      }
    }
  }

  function renderLiveStream(live) {
    if (!live) return;
    state.liveState = live;

    // 1. Overview Page Live Elements
    setText("#live-op-time", live.operational_time || "—");
    setText("#overview-load", `${fmt(live.current_load_kw)} kW`);
    setText("#overview-solar", `${fmt(live.solar_kw)} kW`);
    const asOf = $("#overview-as-of");
    if (asOf) asOf.textContent = `Historical Source Baseline: ${live.historical_source_time}`;

    // NASA POWER Weather Details
    const w = live.weather || {};
    setText("#weather-temp", `${fmt(w.temperature_c)} °C`);
    setText("#weather-rh", `${fmt(w.humidity_pct)}% RH`);
    setText("#weather-irradiance", `${fmt(w.solar_irradiance_wm2)} W/m²`);
    setText("#weather-wind", `${fmt(w.wind_speed_ms)} m/s`);
    setText("#weather-source", w.source || "NASA POWER");
    setText("#weather-utc-time", w.nasa_observation_utc || "—");
    setText("#weather-jordan-time", w.jordan_local_time || "—");
    setText("#weather-retrieved-time", w.last_retrieved_at || "—");

    // 2. Energy Monitor Page Live Elements
    if (page === "energy") {
      setText("#energy-load", `${fmt(live.current_load_kw)} kW`);
      setText("#energy-solar", `${fmt(live.solar_kw)} kW`);
      setText("#energy-hvac", `${fmt(live.hvac_kw)} kW`);
      setText("#energy-occupancy", `${fmt(live.occupancy_pct)}%`);
      setText("#energy-grid-import", `${fmt(live.grid_import_kw)} kW`);
      setText("#live-op-time-energy", live.operational_time || "—");
    }

    // 3. Digital Twin Page Live Elements
    if (page === "digital_twin") {
      setText("#dt-load", `${fmt(live.current_load_kw)} kW`);
      setText("#dt-solar", `${fmt(live.solar_kw)} kW`);
      setText("#dt-grid", `${fmt(live.grid_import_kw)} kW`);
      setText("#dt-op-time", live.operational_time || "—");
    }
  }

  // =========================================================
  // HISTORICAL DATA EXPLORER
  // =========================================================

  async function initHistoryPage() {
    // Dynamically populate available years from database
    try {
      const yearsData = await api("/api/history/years");
      const years = safeArray(yearsData.years);
      const yearSelect = $("#hist-year-select");
      if (yearSelect && years.length) {
        yearSelect.innerHTML = years.map(y => `<option value="${y}" ${y === "2017" ? "selected" : ""}>${y}</option>`).join("");
        setText("#hist-years-range", `${years[0]} – ${years[years.length - 1]}`);
      }
    } catch (e) {
      // Fallback if network check fails
    }

    const form = $("#history-form");
    if (form) {
      form.addEventListener("submit", async e => {
        e.preventDefault();
        await executeHistoryQuery();
      });
    }

    const testBtn = $("#btn-test-sample-event");
    if (testBtn) {
      testBtn.addEventListener("click", async () => {
        const yEl = $("#hist-year-select"); if (yEl) yEl.value = "2017";
        const mEl = $("#hist-month-select"); if (mEl) mEl.value = "08";
        const dEl = $("#hist-day-select"); if (dEl) dEl.value = "11";
        const hEl = $("#hist-hour-select"); if (hEl) hEl.value = "16";
        const mnEl = $("#hist-min-select"); if (mnEl) mnEl.value = "00";
        await executeHistoryQuery();
      });
    }

    await executeHistoryQuery();
  }

  async function executeHistoryQuery() {
    const yr = $("#hist-year-select")?.value || "2017";
    const mo = $("#hist-month-select")?.value || "09";
    const dy = $("#hist-day-select")?.value || "23";
    const hr = $("#hist-hour-select")?.value || "20";
    const mn = $("#hist-min-select")?.value || "00";
    const timestamp = `${yr}-${mo}-${dy} ${hr}:${mn}:00`;

    setText("#hist-selected-ts", timestamp);

    try {
      const data = await api(`/api/history/query?building=${encodeURIComponent(state.building)}&timestamp=${encodeURIComponent(timestamp)}`);
      renderHistoryResults(data);
    } catch (e) {
      toast(`History query: ${e.message}`);
    }
  }

  async function renderHistoryResults(data) {
    if (!data) return;
    const r = data.reading || {};
    const s = data.solar_reading || {};

    setText("#hist-load", r.energy_kw != null ? `${fmt(r.energy_kw)} kW` : "—");
    setText("#hist-solar", s.solar_kw != null ? `${fmt(s.solar_kw)} kW` : (r.solar_kw != null ? `${fmt(r.solar_kw)} kW` : "—"));
    setText("#hist-hvac", r.hvac_kw != null ? `${fmt(r.hvac_kw)} kW` : "—");
    setText("#hist-occupancy", r.occupancy_pct != null ? `${fmt(r.occupancy_pct)}%` : "—");
    setText("#hist-temp", r.temperature_c != null ? `${fmt(r.temperature_c)} °C` : "—");

    // Render historical events list
    const evList = $("#hist-events-list");
    if (evList) {
      const events = safeArray(data.incidents);
      evList.innerHTML = events.length ? events.map(ev => `
        <div class="event-row">
          <span class="event-dot bad"></span>
          <div>
            <b>${esc(ev.incident_type || "Incident")}</b>
            <span style="display:block;margin-top:4px">${esc(ev.created_at || "—")} · Severity: ${esc(ev.severity || "NORMAL")}</span>
          </div>
        </div>
      `).join("") : `<div class="empty-state">No recorded incidents at this historical timestamp.</div>`;
    }

    // Render historical 24h window chart with vertical marker at selected timestamp
    if (data.series) {
      const norm = normalizeEnergy(data.series);
      await buildChart("history-chart", norm);
    }
  }



  // =========================================================
  // LIME EXPLANATION
  // =========================================================

  /** The active event carries the timestamp and building the explainer needs. */
  function activeEvent() {
    return state.agent?.event || null;
  }

  function setExplainButtons() {
    const busy = state.requestBusy || state.replaying;
    const explain = $("#explain-forecast");
    if (explain) explain.disabled = busy || !activeEvent();
    const report = $("#download-pdf");
    if (report) report.disabled = busy || !state.agent?.has_run;
  }

  async function loadExplanation() {
    const ev = activeEvent();
    if (!ev) {
      toast("Run an analysis first, then explain its forecast.");
      return;
    }
    if (state.requestBusy || state.replaying) return;

    const box = $("#explanation-result");
    if (box) {
      box.className = "empty-state";
      box.textContent = "Fitting a local surrogate around this prediction…";
    }

    setBusy(true);
    try {
      state.explanation = await api("/api/ml/explain", {
        method: "POST",
        body: JSON.stringify({
          timestamp: ev.timestamp,
          building_id: ev.building_id || "CAMPUS",
          num_features: 8
        })
      });
      renderExplanation();
    } catch (e) {
      state.explanation = null;
      if (box) {
        box.className = "";
        box.innerHTML = `<div class="error-banner">${esc(e.message)}</div>`;
      }
      toast(`Explain: ${e.message}`);
    } finally {
      setBusy(false);
      setExplainButtons();
    }
  }

  function renderExplanation() {
    const box = $("#explanation-result");
    if (!box) return;

    const exp = state.explanation;
    if (!exp) {
      box.className = "empty-state";
      box.textContent = "Run an analysis, then explain its forecast.";
      return;
    }

    // A CAMPUS explanation nests one result per building.
    const parts = safeArray(exp.buildings).length ? exp.buildings : [exp];

    // The paragraph is optional: it is absent when no language model is
    // configured, and the bars below carry the explanation on their own.
    const summary = exp.summary
      ? `<p class="lime-summary-text">${esc(exp.summary)}</p>`
      : "";

    box.className = "";
    box.innerHTML = summary + parts.map(part => limeBlock(part, parts.length > 1)).join("");
  }

  function limeBlock(part, showHeading) {
    const rows = safeArray(part.contributions);
    const span = Math.max(...rows.map(r => Math.abs(num(r.weight_kw) ?? 0)), 1e-9);

    const bars = rows.map(r => {
      const w = num(r.weight_kw) ?? 0;
      const width = (Math.abs(w) / span) * 100;
      return `<li class="lime-row">
        <span class="lime-label">${esc(r.readable || r.condition || r.feature || "—")}</span>
        <span class="lime-bar ${w >= 0 ? "up" : "down"}"><i style="width:${width.toFixed(1)}%"></i></span>
        <span class="lime-weight">${w >= 0 ? "+" : "−"}${Math.abs(w).toFixed(2)} kW</span>
      </li>`;
    }).join("");

    return `
      ${showHeading ? `<h4 class="lime-heading">${esc(building_label(part.building_id))}</h4>` : ""}
      <div class="lime-summary">
        <div><span class="lime-k">Model forecast</span><b>${fmt(part.predicted_kw)} kW</b></div>
        <div><span class="lime-k">Actual reading</span><b>${fmt(part.actual_kw)} kW</b></div>
        <div><span class="lime-k">Residual</span><b>${fmt(part.residual_percent)}%</b></div>
        <div><span class="lime-k">Surrogate baseline</span><b>${fmt(part.lime_intercept)} kW</b></div>
        <div><span class="lime-k">Local fit R²</span><b>${fmt(part.lime_score, 3)}</b></div>
      </div>
      <ul class="lime-list">${bars || `<li class="empty-state">No contributing features returned.</li>`}</ul>
      <p class="panel-footnote">Each bar is one feature's contribution to this single forecast.
      Red pushes the forecast up, green pulls it down. A low R² means the local surrogate fits
      poorly here, so read the weights with that in mind.</p>`;
  }

  function building_label(id) {
    return id === "CAMPUS" ? "Campus total" : `Building ${id}`;
  }

  // =========================================================
  // PDF REPORT
  // =========================================================

  async function downloadReport() {
    if (state.requestBusy || state.replaying) return;
    if (!state.agent?.has_run) {
      toast("Run an analysis first, then download the report.");
      return;
    }

    setBusy(true);
    try {
      const res = await fetch("/api/report/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_explanation: true })
      });

      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(payload.error || `HTTP ${res.status}`);
      }

      const name = (res.headers.get("Content-Disposition") || "")
        .match(/filename="?([^";]+)"?/)?.[1] || "incident-report.pdf";

      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast("Report downloaded.");
    } catch (e) {
      toast(`Report: ${e.message}`);
    } finally {
      setBusy(false);
      setExplainButtons();
    }
  }


  // =========================================================
  // ANOMALY BREAKDOWN
  // =========================================================
  //
  // Answers what the KPI count raises but cannot show: which hours were
  // flagged, in which building, and how far the reading sat from the forecast.
  // Built entirely on /api/events, so the backend needs no change.

  // Opens on ENERGY_ANOMALY, because the button sits on the anomalies card and
  // the first view has to match the number printed above it.
  const anomalyState = { kind: "ENERGY_ANOMALY", events: null, loading: false };

  async function toggleAnomalies() {
    const panel = $("#anomaly-panel");
    if (!panel) return;

    if (!panel.hidden) {
      panel.hidden = true;
      return;
    }

    panel.hidden = false;
    panel.scrollIntoView({
      behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? "auto" : "smooth",
      block: "start"
    });

    if (anomalyState.events) renderAnomalies();
    else await loadAnomalies();
  }

  async function loadAnomalies() {
    if (anomalyState.loading) return;
    anomalyState.loading = true;

    const button = $("#show-anomalies");
    if (button) button.disabled = true;

    const body = $("#anomaly-body");
    if (body) body.innerHTML = `<div class="empty-state">Loading the flagged hours…</div>`;

    try {
      // Each kind is fetched separately. One combined call is capped, and the
      // 348 peak-demand risks crowd out the 83 anomalies in the ordering, so a
      // single request would make this panel contradict the card above it.
      const building = encodeURIComponent(state.building);
      const [anomalies, peaks] = await Promise.all([
        api(`/api/events?building=${building}&type=ENERGY_ANOMALY&limit=500`),
        api(`/api/events?building=${building}&type=PEAK_DEMAND_RISK&limit=500`)
      ]);

      anomalyState.events = [...safeArray(anomalies.events), ...safeArray(peaks.events)]
        .sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp)));
      renderAnomalies();
    } catch (e) {
      anomalyState.events = null;
      if (body) body.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
    } finally {
      anomalyState.loading = false;
      if (button) button.disabled = false;
    }
  }

  function renderAnomalies() {
    const body = $("#anomaly-body");
    if (!body) return;

    const all = safeArray(anomalyState.events);
    const rows = anomalyState.kind === "all"
      ? all
      : all.filter(e => e.event_type === anomalyState.kind);

    if (!rows.length) {
      body.innerHTML = `<div class="empty-state">No events of this kind for this building.</div>`;
      return;
    }

    const tally = rows.reduce((acc, e) => {
      const key = e.severity || "UNKNOWN";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});

    const chips = ["CRITICAL", "HIGH", "ELEVATED"]
      .filter(level => tally[level])
      .map(level => `<span class="sev-chip ${level.toLowerCase()}">${tally[level]} ${level.toLowerCase()}</span>`)
      .join("");

    const shown = rows.slice(0, 60);

    body.innerHTML = `
      <div class="anomaly-tally"><b>${rows.length}</b> event${rows.length === 1 ? "" : "s"} ${chips}</div>
      <div class="table-scroll">
        <table class="anomaly-table">
          <thead>
            <tr>
              <th>When</th><th>Building</th><th>Kind</th>
              <th>Severity</th><th>Measure</th><th></th>
            </tr>
          </thead>
          <tbody>${shown.map(anomalyRow).join("")}</tbody>
        </table>
      </div>
      ${rows.length > shown.length
        ? `<p class="panel-footnote">Showing the ${shown.length} most recent of ${rows.length}. The Activity page lists them all.</p>`
        : ""}`;

    $$(".anomaly-analyze", body).forEach(btn => btn.addEventListener("click", () => {
      const ev = shown[Number(btn.dataset.index)];
      if (ev) runAgent(ev);
    }));
  }

  function anomalyRow(ev, index) {
    const value = num(ev.value);

    // `value` is a percentage in both cases, but it means two different things.
    // For an anomaly it is the residual: how far the measured load sat from the
    // forecast, as a share of the forecast. For a peak-demand risk it is the
    // campus total as a share of the grid limit. Printing either as kW, or
    // under one label, would be wrong.
    const measure = value == null
      ? "—"
      : ev.event_type === "PEAK_DEMAND_RISK"
        ? `${value.toFixed(1)}% of grid limit`
        : `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}% vs forecast`;

    return `
      <tr>
        <td class="nowrap">${esc(ev.timestamp || "—")}</td>
        <td>${esc(ev.building_name || ev.building_id || "—")}</td>
        <td>${esc(ev.event_label || ev.event_type || "—")}</td>
        <td><span class="sev-chip ${esc(String(ev.severity || "").toLowerCase())}">${esc(ev.severity || "—")}</span></td>
        <td class="nowrap">${esc(measure)}</td>
        <td>${ev.actionable
          ? `<button class="text-link anomaly-analyze" data-index="${index}" type="button">Analyze</button>`
          : `<span class="muted-note">Not actionable</span>`}</td>
      </tr>`;
  }


  // =========================================================
  // REPLANNING DIALOG
  // =========================================================
  //
  // When a verified action misses its target the agent proposes an
  // alternative and waits again. That second gate is easy to miss: it appears
  // as one more line on a long page the reader has already scrolled past. This
  // surfaces it as a dialog instead.
  //
  // It decides nothing on its own: both buttons call decision(), the same
  // function the panel buttons use, so there is one approval path, not two.

  let replanDialogRound = null;      // the round currently on screen
  let replanDialogDismissed = null;  // a round the reader chose to postpone

  function showReplanDialog(a) {
    const overlay = $("#replan-overlay");
    if (!overlay) return;

    const round = a.replan_count ?? 1;

    // Already showing this round, or the reader asked to decide later.
    if (replanDialogRound === round || replanDialogDismissed === round) return;

    const v = a.verification || {};
    setText("#replan-round", round);
    setText("#replan-proposal", a.recommendation?.label || "an alternative action");

    const stats = $("#replan-stats");
    if (stats) {
      stats.innerHTML = `
        <div><span>Action</span><b>${esc(v.intended_label || "Previous action")}</b></div>
        <div><span>Expected</span><b>${esc(fmt(v.expected_reduction_kw))} kW</b></div>
        <div><span>Achieved</span><b>${esc(fmt(v.achieved_reduction_kw))} kW</b></div>
        <div class="miss"><span>Reached</span><b>${esc(fmt(v.performance_ratio_percent))}%</b></div>
        <div><span>Target</span><b>${esc(fmt(v.threshold_percent))}%</b></div>`;
    }

    const body = $("#replan-body");
    if (body) {
      body.textContent =
        `It reached ${fmt(v.performance_ratio_percent)}% of the reduction it was expected to deliver, `
        + `short of the ${fmt(v.threshold_percent)}% target. Nothing further runs until you decide.`;
    }

    replanDialogRound = round;
    overlay.hidden = false;
    document.body.classList.add("modal-open");

    // Focus the primary action so the dialog is usable from the keyboard,
    // and so a screen reader lands inside it rather than behind it.
    setTimeout(() => $("#replan-approve")?.focus(), 30);
  }

  /** Show the dialog again for the pending round, e.g. after "Decide later". */
  function reopenReplanDialog() {
    if (!replanPending(state.agent)) return;
    replanDialogDismissed = null;
    replanDialogRound = null;
    showReplanDialog(state.agent);
  }

  /** Forget which round was already shown, so a new run can raise it again. */
  function resetReplanDialogState() {
    replanDialogRound = null;
    replanDialogDismissed = null;
    const box = $("#replan-diagnosis");
    if (box) { box.hidden = true; box.innerHTML = ""; }
    const why = $("#replan-why");
    if (why) why.textContent = tr("replan_why", "Why did it fall short?");
  }

  function closeReplanDialog() {
    const overlay = $("#replan-overlay");
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    document.body.classList.remove("modal-open");
    replanDialogRound = null;
  }

  /** Translate through i18n when it is loaded, fall back to the given text. */
  function tr(key, fallback) {
    const text = window.t?.(key);
    return !text || text === key ? fallback : text;
  }

  /**
   * Show the measured reasons inside the dialog.
   *
   * The same endpoint the Verification panel uses. Loaded on demand rather
   * than with the dialog: it reads an hour of data, and most of the time the
   * reader approves or rejects without needing it.
   */
  async function loadReplanDiagnosis() {
    const box = $("#replan-diagnosis");
    const button = $("#replan-why");
    if (!box) return;

    if (!box.hidden) {
      box.hidden = true;
      if (button) button.textContent = tr("replan_why", "Why did it fall short?");
      return;
    }

    box.hidden = false;
    box.className = "diagnosis-panel modal-diagnosis";
    box.innerHTML = `<div class="empty-state">${esc(tr("replan_why_loading", "Reading the conditions during that hour…"))}</div>`;
    if (button) button.disabled = true;

    try {
      renderDiagnosisInto(box, await api("/api/verification/diagnosis"));
      if (button) button.textContent = tr("replan_why_hide", "Hide the reasons");
    } catch (e) {
      box.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
      if (button) button.textContent = tr("replan_why", "Why did it fall short?");
    } finally {
      if (button) button.disabled = false;
    }
  }

  function bindReplanDialog() {
    const overlay = $("#replan-overlay");
    if (!overlay) return;

    $("#replan-approve")?.addEventListener("click", () => {
      replanDialogDismissed = replanDialogRound;
      closeReplanDialog();
      decision("approve");
    });

    $("#replan-reject")?.addEventListener("click", () => {
      // Close first, unconditionally. decision() bails out early while another
      // request is in flight, and a dialog that stays open after a click reads
      // as broken even when the refusal is deliberate.
      replanDialogDismissed = replanDialogRound;
      closeReplanDialog();
      decision("reject");
    });

    // The reasons open inside the dialog, so the decision is made next to the
    // evidence for it rather than after closing the gate to go and look.
    $("#replan-why")?.addEventListener("click", () => loadReplanDiagnosis());

    // Postponing keeps the proposal on the page; it does not decide anything.
    $("#replan-later")?.addEventListener("click", () => {
      replanDialogDismissed = replanDialogRound;
      closeReplanDialog();
      toast("The proposal is still waiting in the decision panel.");
    });

    // Escape postpones rather than approves or rejects, and a click on the
    // backdrop does nothing at all: this gate should not be closed by accident.
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && !overlay.hidden) $("#replan-later")?.click();
    });
  }


  initPage();
})();