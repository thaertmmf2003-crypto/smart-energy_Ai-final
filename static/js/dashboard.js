/* =========================================================
   Smart Energy AI - Operations Center frontend
   Talks only to the Flask JSON API. Every value rendered here
   comes from the backend; nothing operational is hard-coded.
   ========================================================= */
(() => {
  "use strict";

  // ------------------------------------------------------------------
  // Constants (labels only)
  // ------------------------------------------------------------------
  const STATE_LABELS = {
    MONITORING: "Monitoring",
    INVESTIGATING: "Investigating",
    GATHERING_EVIDENCE: "Gathering evidence",
    ANALYZING: "Analyzing",
    FORECASTING: "Forecasting",
    SIMULATING: "Simulating",
    VALIDATING: "Validating",
    WAITING_FOR_APPROVAL: "Waiting for approval",
    EXECUTING: "Executing (simulated)",
    VERIFYING: "Verifying",
    REPLANNING: "Replanning",
    COMPLETED: "Completed",
    FAILED: "Failed",
  };

  const STATE_CAPTIONS = {
    MONITORING: "Event received. The agent is starting its investigation.",
    INVESTIGATING: "Confirming the event against ML prediction events.",
    GATHERING_EVIDENCE: "Reading energy, HVAC, occupancy, solar, history and grid status through the tools.",
    ANALYZING: "Loading the ML event context for this timestamp.",
    FORECASTING: "Attaching the forecast context produced by the ML service.",
    SIMULATING: "Retrieving digital twin simulations of candidate actions.",
    VALIDATING: "Reading the optimizer's recommendation for the simulated candidates.",
    WAITING_FOR_APPROVAL: "Human approval required. Nothing will be executed until an operator decides.",
    EXECUTING: "Running a simulated execution. No equipment is controlled.",
    VERIFYING: "Comparing achieved reduction with the expected reduction.",
    REPLANNING: "The action missed its target. Selecting an alternative candidate.",
    COMPLETED: "The action met its verification target. Lifecycle complete.",
    FAILED: "The agent stopped because a required tool returned no data.",
  };

  const PRE_APPROVAL = ["MONITORING", "INVESTIGATING", "GATHERING_EVIDENCE", "ANALYZING", "FORECASTING", "SIMULATING", "VALIDATING"];
  const STEP_DELAY_MS = 340;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------
  const app = {
    building: "CAMPUS",
    snap: null,
    shownTrail: 0,       // number of trail entries already displayed
    busy: false,
    chart: null,
    lifecycle: [],
    openExplain: new Set(),  // candidate actions whose "why" panel is open
  };

  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------------
  // Utilities
  // ------------------------------------------------------------------
  async function api(path, options = {}) {
    const opts = { headers: { "Content-Type": "application/json" }, ...options };
    let res;
    try {
      res = await fetch(path, opts);
    } catch (err) {
      throw new Error("Cannot reach the server. Is app.py running?");
    }
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON */ }
    if (!body || body.success !== true) {
      throw new Error((body && body.error) || `Request failed (${res.status})`);
    }
    return body.data;
  }

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function fmt(value, digits = 1) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtTs(ts, withYear = true) {
    if (!ts) return "—";
    const m = String(ts).match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
    if (!m) return ts;
    const day = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
    return withYear ? `${day} ${m[1]}, ${m[4]}:${m[5]}` : `${day} ${m[4]}:${m[5]}`;
  }

  function toast(message, tone = "info") {
    const el = document.createElement("div");
    el.className = "toast";
    el.dataset.tone = tone;
    el.textContent = message;
    $("toasts").appendChild(el);
    setTimeout(() => el.remove(), tone === "error" ? 7000 : 4200);
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? 0 : ms));

  function toneFor(state, hasRun = true) {
    if (!hasRun && state === "MONITORING") return "idle";
    if (state === "WAITING_FOR_APPROVAL" || state === "REPLANNING") return "waiting";
    if (state === "COMPLETED") return "done";
    if (state === "FAILED") return "failed";
    return "active";
  }

  function setBusy(flag) {
    app.busy = flag;
    $("runBtn").classList.toggle("is-busy", flag);
    $("runBtn").disabled = flag;
    document.querySelectorAll(".feed-btn[data-actionable='1']").forEach((b) => { b.disabled = flag; });
    updateDecisionButtons();
  }

  // ------------------------------------------------------------------
  // Health / KPIs
  // ------------------------------------------------------------------
  async function loadHealth() {
    const box = $("systemStatus");
    try {
      const h = await api("/api/health");
      const core = h.database && h.ml_service;
      box.dataset.tone = core ? "online" : "degraded";
      $("systemStatusText").textContent = core ? "AI SYSTEM ONLINE" : "AI SYSTEM DEGRADED";
      box.title = `Database: ${h.database ? "ok" : "unavailable"} | ML service: ${h.ml_service ? "ok" : "unavailable"} | Optimizer: ${h.optimizer ? "ok" : "unavailable"} | Knowledge base: ${h.rag ? "ok" : "unavailable"}${h.mock_data ? " | MOCK DATA ENABLED" : ""}`;
    } catch (err) {
      box.dataset.tone = "offline";
      $("systemStatusText").textContent = "AI SYSTEM OFFLINE";
      box.title = err.message;
    }
  }

  async function loadDashboard() {
    const d = await api(`/api/dashboard?building=${app.building}`);
    const k = d.kpis;
    const scope = d.building === "CAMPUS" ? "All three buildings" : `${d.building} ${d.building_name}`;

    $("kpiLoad").textContent = fmt(k.current_load_kw);
    $("kpiLoadSub").textContent = `${scope}, reading of ${fmtTs(d.as_of)}`;
    $("kpiSolar").textContent = fmt(k.solar_kw);
    $("kpiSolarSub").textContent = k.solar_kw === 0 ? "No solar output at this hour" : `${scope}, latest reading`;
    $("kpiAnomalies").textContent = k.anomalies ?? "—";
    $("kpiAnomaliesSub").textContent = `${k.anomalies_high} high severity, plus ${k.peak_risks} campus peak-demand risks`;

    if (k.achieved_reduction_kw !== null && k.achieved_reduction_kw !== undefined) {
      $("kpiSaving").textContent = fmt(k.achieved_reduction_kw);
      $("kpiSavingSub").textContent = `Achieved in verification, ${fmt(k.estimated_reduction_kw)} kW currently proposed`;
    } else if (k.estimated_reduction_kw !== null && k.estimated_reduction_kw !== undefined) {
      $("kpiSaving").textContent = fmt(k.estimated_reduction_kw);
      $("kpiSavingSub").textContent = `Simulated, ${k.estimated_reduction_action}`;
    } else {
      $("kpiSaving").textContent = "—";
      $("kpiSavingSub").textContent = "Run an analysis to get a recommendation";
    }

    $("dataNote").textContent =
      `Replaying the project dataset. Latest reading in the database: ${fmtTs(d.as_of)}. Execution mode: simulated.`;

    const rag = d.rag || {};
    if (!rag.available) {
      $("kbStatus").textContent = "The knowledge base is unavailable. The rest of the dashboard works normally.";
    } else if (rag.generation === "llm") {
      $("kbStatus").textContent = `${rag.documents.length} documents indexed. Answers are written by ${rag.model} from retrieved sections only.`;
    } else {
      $("kbStatus").textContent = `${rag.documents.length} documents indexed. Answers quote the retrieved sections (no language model configured).`;
    }
  }

  // ------------------------------------------------------------------
  // Energy chart
  // ------------------------------------------------------------------
  const eventMarker = {
    id: "eventMarker",
    afterDatasetsDraw(chart, _args, opts) {
      if (opts.index === null || opts.index === undefined || opts.index < 0) return;
      const x = chart.scales.x.getPixelForValue(opts.index);
      const { top, bottom } = chart.chartArea;
      const ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = "rgba(227,179,92,0.85)";
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(227,179,92,0.95)";
      ctx.font = "600 11px Inter, system-ui, sans-serif";
      ctx.textAlign = x > chart.chartArea.right - 60 ? "right" : "left";
      ctx.fillText("Event", x + (ctx.textAlign === "left" ? 6 : -6), top + 12);
      ctx.restore();
    },
  };

  function buildChart() {
    if (typeof Chart === "undefined") {
      showChartMessage("Chart library failed to load.");
      return null;
    }
    const ctx = $("energyChart").getContext("2d");
    const grad = ctx.createLinearGradient(0, 0, 0, 300);
    grad.addColorStop(0, "rgba(91,196,219,0.28)");
    grad.addColorStop(1, "rgba(91,196,219,0)");
    const gradSolar = ctx.createLinearGradient(0, 0, 0, 300);
    gradSolar.addColorStop(0, "rgba(84,209,166,0.22)");
    gradSolar.addColorStop(1, "rgba(84,209,166,0)");

    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.color = "#6c7d79";

    return new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: "Consumption", data: [], borderColor: "#5bc4db", backgroundColor: grad, fill: true, tension: 0.35, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
          { label: "Solar", data: [], borderColor: "#54d1a6", backgroundColor: gradSolar, fill: true, tension: 0.35, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
          { label: "HVAC", data: [], borderColor: "#9a8cf0", backgroundColor: "transparent", fill: false, tension: 0.35, borderWidth: 1.6, borderDash: [5, 4], pointRadius: 0, hidden: true },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: reduceMotion ? false : { duration: 600 },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          eventMarker: { index: null },
          tooltip: {
            backgroundColor: "rgba(12,19,22,0.95)",
            borderColor: "rgba(168,210,200,0.2)",
            borderWidth: 1,
            titleColor: "#e6eeec",
            bodyColor: "#a3b3af",
            padding: 10,
            callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt(c.parsed.y)} kW` },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
          y: { grid: { color: "rgba(168,210,200,0.07)" }, border: { display: false }, ticks: { callback: (v) => `${v} kW` }, beginAtZero: true },
        },
      },
      plugins: [eventMarker],
    });
  }

  function showChartMessage(msg) {
    const el = $("chartEmpty");
    el.hidden = !msg;
    el.textContent = msg || "";
  }

  async function loadEnergy() {
    try {
      const d = await api(`/api/energy?building=${app.building}&hours=48`);
      if (!app.chart) app.chart = buildChart();
      if (!app.chart) return;
      if (!d.labels.length) {
        showChartMessage("No readings for this window.");
      } else {
        showChartMessage("");
      }
      app.chart.data.labels = d.labels.map((t) => fmtTs(t, false));
      app.chart.data.datasets[0].data = d.energy_kw;
      app.chart.data.datasets[1].data = d.solar_kw;
      app.chart.data.datasets[2].data = d.hvac_kw;
      app.chart.options.plugins.eventMarker.index = d.center ? d.labels.indexOf(d.center) : null;
      app.chart.update();
      const where = d.building === "CAMPUS" ? "Campus total" : `${d.building} ${d.building_name}`;
      $("chartCaption").textContent = d.center
        ? `${where}, 48 hours around the event at ${fmtTs(d.center)}`
        : `${where}, last 48 hours of readings to ${fmtTs(d.end)}`;
    } catch (err) {
      showChartMessage(err.message);
    }
  }

  // ------------------------------------------------------------------
  // Event feed
  // ------------------------------------------------------------------
  async function loadEvents() {
    const feed = $("eventFeed");
    try {
      const d = await api(`/api/events?building=${app.building}&limit=60`);
      $("feedCaption").textContent = `${d.total} events for this view, ${d.actionable_total} with simulations`;
      const current = app.snap && app.snap.event;
      if (!d.events.length) {
        feed.innerHTML = `<li class="feed-empty">No ML events for this building.</li>`;
        return;
      }
      feed.innerHTML = d.events.map((e) => {
        const isCurrent = current && current.timestamp === e.timestamp && current.building_id === e.building_id && current.event_type === e.event_type;
        return `
          <li class="feed-item${isCurrent ? " is-current" : ""}">
            <span class="feed-sev" data-sev="${esc(e.severity)}" title="${esc(e.severity)}"></span>
            <div class="feed-main">
              <div class="feed-title">${esc(e.event_label)}, ${esc(e.building_id === "CAMPUS" ? "campus" : `${e.building_id} ${e.building_name}`)}</div>
              <div class="feed-meta">${esc(fmtTs(e.timestamp))}, ${esc(e.severity.toLowerCase())}</div>
            </div>
            ${e.actionable
              ? `<button type="button" class="feed-btn" data-actionable="1" data-ts="${esc(e.timestamp)}" data-b="${esc(e.building_id)}" data-t="${esc(e.event_type)}" ${app.busy ? "disabled" : ""}>Analyze</button>`
              : `<button type="button" class="feed-btn" disabled title="The ML pipeline produced no simulation for this timestamp">No simulation</button>`}
          </li>`;
      }).join("");
    } catch (err) {
      feed.innerHTML = `<li class="feed-empty">${esc(err.message)}</li>`;
    }
  }

  // ------------------------------------------------------------------
  // Lifecycle track
  // ------------------------------------------------------------------
  function trackPosition(trail, uptoIndex, lifecycle) {
    const slice = trail.slice(0, uptoIndex + 1);
    const current = slice.length ? slice[slice.length - 1].state : "MONITORING";
    const times = {};
    slice.forEach((t) => { times[t.state] = t.time; });
    let pos;
    let failed = false;
    if (current === "FAILED") {
      failed = true;
      const prev = [...slice].reverse().find((t) => t.state !== "FAILED");
      pos = prev ? lifecycle.indexOf(prev.state) : 0;
    } else if (current === "REPLANNING") {
      pos = lifecycle.indexOf("VERIFYING");
    } else {
      pos = lifecycle.indexOf(current);
    }
    return { current, pos, failed, times };
  }

  const CHECK = `<svg viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7"/></svg>`;

  function renderTrack(snap, uptoIndex) {
    const lifecycle = snap.lifecycle || app.lifecycle;
    const trail = snap.trail || [];
    const hasRun = snap.has_run && trail.length > 0;
    const { current, pos, failed, times } = hasRun
      ? trackPosition(trail, uptoIndex, lifecycle)
      : { current: "MONITORING", pos: -1, failed: false, times: {} };

    $("trackRail").innerHTML = lifecycle.map((state, i) => {
      const cls = ["node"];
      if (state === "WAITING_FOR_APPROVAL") cls.push("is-gate");
      if (state === "COMPLETED") cls.push("is-final");
      let inner = `<span>${i + 1}</span>`;
      if (hasRun && i < pos) {
        cls.push("is-done");
        inner = `<span>${CHECK}</span>`;
      } else if (hasRun && i === pos) {
        cls.push(failed ? "is-failed" : "is-current");
        if (failed) inner = `<span>!</span>`;
        else if (state === "COMPLETED") inner = `<span>${CHECK}</span>`;
      }
      const label = state === "WAITING_FOR_APPROVAL" ? "Human approval" : STATE_LABELS[state].replace(" (simulated)", "");
      const time = hasRun && i <= pos ? (times[state] || "") : "";
      return `<li class="${cls.join(" ")}" aria-current="${i === pos ? "step" : "false"}">
          <span class="node-dot">${inner}</span>
          <span class="node-label">${esc(label)}</span>
          <span class="node-time">${esc(time)}</span>
        </li>`;
    }).join("");

    const shownState = hasRun ? current : "MONITORING";
    $("trackCaption").textContent = hasRun ? STATE_CAPTIONS[shownState] || "" : "The agent is idle. Run an AI analysis to start the lifecycle.";
    setStatePill(shownState, hasRun);
    return shownState;
  }

  function setStatePill(state, hasRun) {
    const tone = toneFor(state, hasRun);
    $("statePill").dataset.tone = tone;
    $("statePillText").textContent = hasRun ? STATE_LABELS[state] || state : "Monitoring";
    $("sidebarAgent").dataset.tone = tone;
    $("sidebarAgentState").textContent = hasRun ? STATE_LABELS[state] || state : "Monitoring";
  }

  // ------------------------------------------------------------------
  // Story panels
  // ------------------------------------------------------------------
  const reached = (shownState, target) => {
    const order = [...PRE_APPROVAL, "WAITING_FOR_APPROVAL", "EXECUTING", "VERIFYING", "REPLANNING", "COMPLETED"];
    if (shownState === "FAILED") return false;
    return order.indexOf(shownState) >= order.indexOf(target);
  };

  function renderProblem(snap, shown) {
    const p = snap.problem;
    const body = $("problemBody");
    if (!p || !reached(shown, "INVESTIGATING") && shown !== "FAILED") {
      body.innerHTML = `<p class="empty">${snap.has_run ? "Waiting for the investigation step…" : "No event under investigation."}</p>`;
      return;
    }
    body.innerHTML = `
      <div class="problem-tags reveal">
        <span class="tag" data-sev="${esc(p.severity)}">${esc(p.severity)}</span>
        <span class="tag">${esc(p.event_label)}</span>
        <span class="tag">${esc(p.building_id === "CAMPUS" ? "Campus-wide" : `${p.building_id} ${p.building_name}`)}</span>
      </div>
      <p class="problem-headline reveal">${esc(p.headline)}</p>
      ${p.facts.length ? `<ul class="problem-facts">${p.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}
      <div class="problem-meta">
        <div><div class="meta-label">Event time</div><div class="meta-value">${esc(fmtTs(p.timestamp))}</div></div>
        <div><div class="meta-label">${esc(p.value_meaning)}</div><div class="meta-value">${fmt(p.value, 2)}</div></div>
      </div>`;
  }

  function evTile(label, value, unit, sub, isText = false, subWarn = false) {
    return `<div class="ev reveal"><div class="ev-label">${esc(label)}</div>
      <div class="ev-value${isText ? " is-text" : ""}">${value}${unit ? `<small>${esc(unit)}</small>` : ""}</div>
      ${sub ? `<div class="ev-sub${subWarn ? " is-warn" : ""}">${esc(sub)}</div>` : ""}</div>`;
  }

  function renderEvidence(snap, shown) {
    const e = snap.evidence;
    const body = $("evidenceBody");
    const ready = e && (reached(shown, "GATHERING_EVIDENCE") || shown === "FAILED");
    if (!ready) {
      const msg = snap.has_run && shown !== "FAILED" ? "Gathering evidence…" : "Evidence appears once the agent investigates an event.";
      body.innerHTML = `<p class="empty">${msg}</p>`;
      return;
    }
    const g = e.grid || {};
    const hvacExceeds = e.energy_kw && e.hvac_kw > e.energy_kw;
    const hvacShare = !e.energy_kw ? ""
      : hvacExceeds ? "HVAC reading exceeds total load (data quality)"
      : `${fmt((e.hvac_kw / e.energy_kw) * 100, 0)}% of metered load`;
    body.innerHTML = `
      <div class="evidence-grid">
        ${evTile("Energy", fmt(e.energy_kw), "kW", e.scope === "campus" ? "Sum of three buildings" : null)}
        ${evTile("HVAC", fmt(e.hvac_kw), "kW", hvacShare, false, hvacExceeds)}
        ${evTile("Occupancy", fmt(e.occupancy_pct, 0), "%", e.occupancy_is_average ? "Average across buildings" : null)}
        ${evTile("Solar", fmt(e.solar_kw), "kW", e.solar_kw === 0 ? "No output at reading hour" : null)}
        ${evTile("Historical consumption", e.history_count !== null ? Number(e.history_count).toLocaleString("en-US") : "—", "readings", "Reviewed by the agent")}
        ${evTile("Grid status", esc(g.status ? g.status.charAt(0) + g.status.slice(1).toLowerCase() : "—"), "", g.grid_load_pct !== undefined && g.grid_load_pct !== null ? `Grid load ${fmt(g.grid_load_pct, 0)}%, price ${fmt(g.price_signal, 2)}` : null)}
      </div>
      ${e.per_building && e.per_building.length > 1 ? `
      <div class="table-scroll"><table class="breakdown">
        <thead><tr><th>Building</th><th>Energy kW</th><th>HVAC kW</th><th>Occupancy %</th><th>Solar kW</th><th>EV kW</th></tr></thead>
        <tbody>${e.per_building.map((b) => `<tr><td>${esc(b.building_id)} ${esc(b.building_name)}</td><td>${fmt(b.energy_kw)}</td><td>${fmt(b.hvac_kw)}</td><td>${fmt(b.occupancy_pct, 0)}</td><td>${fmt(b.solar_kw)}</td><td>${fmt(b.ev_kw)}</td></tr>`).join("")}</tbody>
      </table></div>` : ""}
      <p class="ev-foot">Readings at the event hour (${esc(fmtTs(e.reading_time))}). History covers the 24 hours up to the event. ${e.ml_events_at_timestamp ? `${e.ml_events_at_timestamp} ML event record(s) matched the event timestamp.` : ""}${g.description ? ` Grid status comes from the database layer: ${esc(g.description)}` : ""}</p>`;
  }

  function renderCandidates(snap, shown) {
    const body = $("candidatesBody");
    const cands = snap.candidate_actions || [];
    if (!cands.length || !reached(shown, "SIMULATING")) {
      body.innerHTML = `<p class="empty">${snap.has_run && shown !== "FAILED" ? "Running the digital twin…" : shown === "FAILED" ? "No simulation results were available for this event." : "Candidate actions appear after simulation."}</p>`;
      return;
    }
    const scopeNote = snap.recommendation_scope_note
      ? `<div class="notice" style="margin-bottom:12px">${esc(snap.recommendation_scope_note)}</div>` : "";
    const max = Math.max(...cands.map((c) => Number(c.estimated_reduction_kw) || 0), 1);
    const missed = new Set((snap.verification_log || []).filter((v) => v.needs_replanning).map((v) => v.intended_action));
    body.innerHTML = `${scopeNote}<div class="cands">${cands.map((c) => {
      const constraint = c.passes_constraints === null ? "" :
        c.passes_constraints ? `<span class="tag" data-tone="ok">Passes constraints</span>` : `<span class="tag" data-tone="bad">Fails constraints</span>`;
      const meta = [
        c.reduction_percent !== undefined ? `${fmt(c.reduction_percent, 1)}% of forecast load` : null,
        c.new_predicted_load !== undefined ? `Load after: ${fmt(c.new_predicted_load)} kW` : null,
        c.optimization_score !== null ? `Optimizer score ${fmt(c.optimization_score, 2)}` : null,
        c.battery_soc_percent !== undefined ? `Battery SOC ${fmt(c.battery_soc_percent, 0)}%` : null,
        c.ev_load_kw !== undefined ? `EV load ${fmt(c.ev_load_kw)} kW` : null,
      ].filter(Boolean);
      return `<div class="cand reveal${c.is_selected ? " is-selected" : ""}">
          <div class="cand-name">${esc(c.label)} ${c.is_selected ? `<span class="tag" data-tone="ok">Recommended</span>` : ""}${missed.has(c.action) && reached(shown, "VERIFYING") || missed.has(c.action) && shown === "WAITING_FOR_APPROVAL" ? `<span class="tag" data-tone="warn">Missed target</span>` : ""} ${constraint}</div>
          <div class="cand-kw">${fmt(c.estimated_reduction_kw)}<small>kW</small></div>
          <div class="cand-bar"><span style="width:${((Number(c.estimated_reduction_kw) || 0) / max) * 100}%"></span></div>
          <div class="cand-meta">${meta.map((m) => `<span>${esc(m)}</span>`).join("")}<span>Simulation: complete</span></div>
          ${renderWhy(c)}
        </div>`;
    }).join("")}</div>
    ${snap.optimizer_constraints ? `<div class="constraints">Optimizer constraints (optimizer.py):<ul>${snap.optimizer_constraints.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>` : ""}`;
  }

  const WHY_LABELS = {
    failed_constraints: "Why was it rejected?",
    missed_target: "Why was it rejected?",
    not_selected: "Why wasn't it chosen?",
    selected: "Why was it chosen?",
    verified: "What happened?",
  };

  function renderWhy(c) {
    const e = c.explanation;
    if (!e || !e.verdict) return "";
    const open = app.openExplain.has(c.action);
    const tone = { failed_constraints: "bad", missed_target: "warn", selected: "ok", verified: "ok" }[e.verdict] || "";
    const checks = (c.constraint_checks || []).length ? `
      <table class="why-checks">
        <caption>Optimizer constraint checks</caption>
        <tbody>${c.constraint_checks.map((k) => `
          <tr data-state="${!k.applies ? "na" : k.passed ? "pass" : "fail"}">
            <td class="why-mark">${!k.applies ? "–" : k.passed ? "✓" : "✗"}</td>
            <td>${esc(k.detail)}</td>
          </tr>`).join("")}</tbody>
      </table>` : "";
    const cmp = e.comparison ? `
      <div class="table-scroll"><table class="breakdown why-score">
        <thead><tr><th>Score term</th><th>This action</th><th>${esc(e.comparison.selected_label)}</th></tr></thead>
        <tbody>
          <tr><td>Reduction x weight</td><td>${fmt(e.comparison.this.reduction_term, 2)}</td><td>${fmt(e.comparison.selected.reduction_term, 2)}</td></tr>
          <tr><td>Disruption rank x penalty</td><td>−${fmt(e.comparison.this.penalty_term, 2)}</td><td>−${fmt(e.comparison.selected.penalty_term, 2)}</td></tr>
          <tr><td>Score</td><td>${fmt(e.comparison.this.score, 2)}</td><td>${fmt(e.comparison.selected.score, 2)}</td></tr>
        </tbody>
      </table></div>` : "";
    return `
      <div class="why">
        <button type="button" class="why-btn" data-why="${esc(c.action)}" aria-expanded="${open}">
          ${esc(WHY_LABELS[e.verdict] || "Why?")}<span class="why-caret" aria-hidden="true">${open ? "▴" : "▾"}</span>
        </button>
        <div class="why-panel" ${open ? "" : "hidden"}>
          <div class="why-title"><span class="tag" data-tone="${tone}">${esc(e.title)}</span></div>
          <ul>${e.points.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
          ${checks}
          ${cmp}
          ${e.basis ? `<p class="rec-basis">Basis: ${esc(e.basis)}.</p>` : ""}
        </div>
      </div>`;
  }

  function renderRecommendation(snap, shown) {
    const body = $("recBody");
    const r = snap.recommendation;
    const last = snap.last_decision;
    if (["EXECUTING", "VERIFYING"].includes(shown) && last && last.decision === "APPROVED") {
      // Mid-replay: show the action being executed, not a later alternative.
      const cand = (snap.candidate_actions || []).find((c) => c.action === last.action);
      const label = cand ? cand.label : String(last.action || "").replaceAll("_", " ").toLowerCase();
      body.innerHTML = `<div class="problem-tags"><span class="tag" data-tone="ok">Approved</span></div>
        <div class="rec-action">${esc(label)}</div>
        <p class="card-sub" style="margin-top:8px">Running as a simulated execution.</p>`;
      return;
    }
    if (!r || !reached(shown, "VALIDATING")) {
      body.innerHTML = `<p class="empty">${snap.has_run && shown !== "FAILED" ? "Waiting for the optimizer…" : "No recommendation yet."}</p>`;
      return;
    }
    const status = { PENDING: ["Pending approval", "warn"], APPROVED: ["Approved", "ok"], REJECTED: ["Rejected", "bad"] }[r.approval_status] || [r.approval_status, ""];
    const reason = r.reason && r.reason.points && r.reason.points.length ? `
      <div class="rec-why">
        <h4>Why this action</h4>
        <ul>${r.reason.points.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
        <p class="rec-basis">Basis: ${esc(r.reason.basis)}. Assembled from recorded outputs, not generated text.</p>
      </div>` : "";
    body.innerHTML = `
      <div class="problem-tags">
        <span class="tag" data-tone="${status[1]}">${esc(status[0])}</span>
        ${r.source === "replanning" ? `<span class="tag" data-tone="warn">Alternative after replanning</span>` : `<span class="tag">From optimizer</span>`}
      </div>
      <div class="rec-action reveal">${esc(r.label)}</div>
      <div class="rec-figures">
        <div><div class="rec-fig-value">${fmt(r.estimated_reduction_kw)}<small>kW</small></div><div class="rec-fig-label">Estimated reduction</div></div>
        ${r.new_predicted_load !== null ? `<div><div class="rec-fig-value" style="color:var(--ink)">${fmt(r.new_predicted_load)}<small>kW</small></div><div class="rec-fig-label">Forecast load after action</div></div>` : ""}
      </div>
      ${reason}`;
  }

  function renderDecision(snap, shown) {
    const card = $("decisionCard");
    const text = $("decisionText");
    const waiting = snap.state === "WAITING_FOR_APPROVAL" && shown === "WAITING_FOR_APPROVAL";
    card.dataset.state = waiting ? "waiting" : snap.has_run ? "done" : "idle";
    const last = snap.last_decision;
    const rec = snap.recommendation;

    let html;
    if (waiting) {
      html = `<strong>Human approval required.</strong> Approve to run ${esc(rec ? rec.label : "the action")} as a simulated execution, or reject it.`;
      if (last && last.decision === "REJECTED" && rec && last.action === rec.action) {
        html += `<br><span class="card-sub">You rejected this recommendation at ${esc(last.time)}. Nothing was executed. Approve to reconsider, or run a new analysis.</span>`;
      }
    } else if (["EXECUTING", "VERIFYING"].includes(shown)) {
      html = `Approved at ${esc(last ? last.time : "")}.`;
    } else if (snap.state === "COMPLETED") {
      html = `Approved at ${esc(last ? last.time : "")}. The action met its verification target.`;
    } else if (snap.state === "FAILED") {
      html = "Nothing to approve. The agent stopped before reaching a recommendation.";
    } else if (snap.has_run) {
      html = "The agent is working. The decision opens when it reaches the approval step.";
    } else {
      html = "Nothing is waiting for approval.";
    }
    text.innerHTML = html;

    const existing = card.querySelector(".exec-banner");
    if (existing) existing.remove();
    if (["EXECUTING", "VERIFYING"].includes(shown)) {
      const banner = document.createElement("div");
      banner.className = "exec-banner";
      banner.innerHTML = `<span class="spinner"></span><span>${shown === "EXECUTING" ? "Simulated execution in progress. No equipment is being controlled." : "Verifying the simulated result…"}</span>`;
      card.querySelector(".decision-actions").after(banner);
    } else if (snap.state === "COMPLETED" && last) {
      const banner = document.createElement("div");
      banner.className = "exec-banner";
      banner.style.borderStyle = "solid";
      banner.innerHTML = `<span>Simulated execution of ${esc(last.action ? last.action.replaceAll("_", " ").toLowerCase() : "the action")} finished.</span>`;
      card.querySelector(".decision-actions").after(banner);
    }
    updateDecisionButtons(waiting);
  }

  function updateDecisionButtons(waitingOverride) {
    const waiting = waitingOverride !== undefined ? waitingOverride : (app.snap && app.snap.approval_required && app.shownTrail >= (app.snap.trail || []).length);
    $("approveBtn").disabled = app.busy || !waiting;
    $("rejectBtn").disabled = app.busy || !waiting;
  }

  function renderVerification(snap, shown) {
    const body = $("verifyBody");
    const log = snap.verification_log || [];
    // During replay, only show verification once VERIFYING has been reached in this pass.
    const showLatest = log.length && (reached(shown, "VERIFYING") || shown === "WAITING_FOR_APPROVAL" && snap.replanned);
    if (!showLatest) {
      body.innerHTML = `<p class="empty">${["EXECUTING"].includes(shown) ? "Waiting for the simulated execution to finish…" : "Verification runs after an approved action has been executed in simulation."}</p>`;
      return;
    }
    const v = log[log.length - 1];
    const ok = v.verification_status === "SUCCESS";
    const perf = Math.max(0, Math.min(Number(v.performance_ratio_percent) || 0, 120));
    const threshold = v.threshold_percent || 80;
    const pct = (x) => `${(x / 120) * 100}%`;

    const mismatch = v.action_mismatch ? `
      <div class="notice notice-error verify-warn">
        The verification dataset holds one record per event, for ${esc(v.verified_label)}. The agent checked ${esc(v.intended_label)}
        against that record, so this result describes ${esc(v.verified_label)}, not the action you just approved.
      </div>` : "";

    const history = log.length > 1 ? `
      <details class="verify-history">
        <summary>Earlier verifications in this run (${log.length - 1})</summary>
        <div class="table-scroll"><table class="breakdown">
          <thead><tr><th>Time</th><th>Approved action</th><th>Expected kW</th><th>Achieved kW</th><th>Performance</th><th>Status</th></tr></thead>
          <tbody>${log.slice(0, -1).map((x) => `<tr><td>${esc(x.time)}</td><td>${esc(x.intended_label)}</td><td>${fmt(x.expected_reduction_kw)}</td><td>${fmt(x.achieved_reduction_kw)}</td><td>${fmt(x.performance_ratio_percent)}%</td><td>${esc(x.verification_status)}</td></tr>`).join("")}</tbody>
        </table></div>
      </details>` : "";

    body.innerHTML = `
      <div class="verify-grid reveal">
        ${evTile("Expected reduction", fmt(v.expected_reduction_kw), "kW", `Load target ${fmt(v.expected_load_after_action)} kW`)}
        ${evTile("Actual reduction", fmt(v.achieved_reduction_kw), "kW", `Observed load ${fmt(v.observed_load_after_action)} kW`)}
        ${evTile("Performance", fmt(v.performance_ratio_percent), "%", `Target ${fmt(threshold, 0)}% or more`)}
        ${evTile("Verified action", esc(v.verified_label), "", `Record of ${fmtTs(snap.event && snap.event.timestamp)}`, true)}
        <div class="verify-status" data-tone="${ok ? "ok" : "bad"}">
          <strong>${ok ? "Verified" : "Target not met"}</strong>
          <span class="card-sub">${ok
            ? "The simulated action achieved its expected reduction."
            : "Performance target not achieved. The agent is replanning."}</span>
        </div>
      </div>
      <div class="perf">
        <div class="perf-track">
          <div class="perf-fill" data-tone="${ok ? "ok" : "bad"}" style="width:${pct(perf)}"></div>
          <div class="perf-mark" style="left:${pct(threshold)}" title="Verification threshold"></div>
        </div>
        <div class="perf-legend"><span>0%</span><span>Threshold ${fmt(threshold, 0)}%</span><span>120%</span></div>
      </div>
      ${mismatch}
      ${history}`;
  }

  function renderReplanBanner(snap, shown) {
    const box = $("trackReplan");
    const v = (snap.verification_log || []).slice(-1)[0];
    const show = snap.replanned && snap.state === "WAITING_FOR_APPROVAL" && shown === "WAITING_FOR_APPROVAL" && v && v.needs_replanning;
    box.hidden = !show;
    if (show) {
      const rec = snap.recommendation;
      $("trackReplanText").textContent =
        `Replanning round ${snap.replan_count}: ${v.intended_label} reached ${fmt(v.performance_ratio_percent)}% of its expected reduction (target ${fmt(v.threshold_percent || 80, 0)}%). ` +
        `The agent proposes ${rec ? rec.label : "an alternative"}, which needs your approval.`;
    }
  }

  function renderNotices(snap) {
    const note = $("selectionNote");
    note.hidden = !snap.selection_note;
    note.textContent = snap.selection_note || "";
    const err = $("agentError");
    err.hidden = !(snap.state === "FAILED" && snap.error);
    err.textContent = snap.error ? `Agent stopped: ${snap.error}` : "";
  }

  function renderLog(snap) {
    const list = $("activityLog");
    const items = snap.history || [];
    if (!items.length) {
      list.innerHTML = `<li class="log-empty">No activity yet.</li>`;
      return;
    }
    list.innerHTML = items.map((h) => {
      const msg = h.message || "";
      let tone = toneFor(h.state);
      if (/approved/i.test(msg)) tone = "done";
      if (/rejected|failed/i.test(msg)) tone = "failed";
      if (/completed successfully/i.test(msg)) tone = "done";
      return `<li class="log-item" data-tone="${tone}">
          <span class="log-time">${esc(h.time || "")}</span>
          <span class="log-dot"></span>
          <div><div class="log-msg">${esc(msg)}</div><div class="log-state">${esc(STATE_LABELS[h.state] || h.state)}</div></div>
        </li>`;
    }).join("");
    list.scrollTop = list.scrollHeight;
  }

  function renderAll(snap, uptoIndex) {
    const trail = snap.trail || [];
    const idx = uptoIndex === undefined ? trail.length - 1 : uptoIndex;
    const shown = renderTrack(snap, idx);
    renderNotices(snap);
    renderProblem(snap, shown);
    renderEvidence(snap, shown);
    renderCandidates(snap, shown);
    renderRecommendation(snap, shown);
    renderDecision(snap, shown);
    renderVerification(snap, shown);
    renderReplanBanner(snap, shown);
  }

  // Replays the transitions the agent actually recorded, one by one.
  async function presentSnapshot(snap, animate) {
    app.snap = snap;
    app.lifecycle = snap.lifecycle || app.lifecycle;
    const trail = snap.trail || [];
    if (trail.length < app.shownTrail) app.shownTrail = 0; // new run
    renderLog(snap);
    if (animate && !reduceMotion && trail.length > app.shownTrail) {
      for (let i = app.shownTrail; i < trail.length; i += 1) {
        app.shownTrail = i; // keep decision buttons locked mid-replay
        renderAll(snap, i);
        await sleep(STEP_DELAY_MS);
      }
    }
    app.shownTrail = trail.length;
    renderAll(snap);
  }

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------
  async function loadAgent() {
    const snap = await api("/api/agent/status");
    app.shownTrail = 0;
    await presentSnapshot(snap, false);
  }

  async function runAnalysis(body) {
    if (app.busy) return;
    setBusy(true);
    try {
      app.shownTrail = 0;
      app.openExplain.clear();
      const snap = await api("/api/agent/run", { method: "POST", body: JSON.stringify(body) });
      document.getElementById("operations").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      await presentSnapshot(snap, true);
      if (snap.state === "FAILED") toast(snap.error || "The agent could not complete the analysis.", "error");
      refreshSecondary();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function decide(approved) {
    if (app.busy) return;
    setBusy(true);
    try {
      const snap = await api(`/api/agent/${approved ? "approve" : "reject"}`, { method: "POST", body: "{}" });
      await presentSnapshot(snap, true);
      if (!approved) toast("Rejected. Nothing was executed.");
      else if (snap.state === "COMPLETED") toast("Approved. Simulated execution verified.", "ok");
      else if (snap.replanned && snap.state === "WAITING_FOR_APPROVAL") toast("Target not met. The agent proposes an alternative.");
      refreshSecondary();
    } catch (err) {
      toast(err.message, "error");
      loadAgent().catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  async function resetAgent() {
    if (app.busy) return;
    try {
      const snap = await api("/api/agent/reset", { method: "POST", body: "{}" });
      app.shownTrail = 0;
      await presentSnapshot(snap, false);
      refreshSecondary();
      toast("Agent session reset.");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function refreshSecondary() {
    loadDashboard().catch((e) => toast(e.message, "error"));
    loadEnergy();
    loadEvents();
  }

  // ------------------------------------------------------------------
  // Knowledge (RAG)
  // ------------------------------------------------------------------
  function renderAnswer(q, d) {
    const text = esc(d.answer).replace(/\[(\d+)\]/g, `<span class="ref">[$1]</span>`);
    const modeTag = {
      llm: `<span class="tag" data-tone="ok">Generated by ${esc(d.model)} from retrieved sections</span>`,
      extractive: `<span class="tag">Quoted from retrieved sections</span>`,
      no_match: `<span class="tag" data-tone="warn">No matching document</span>`,
    }[d.mode] || "";
    const live = d.live_context && Object.keys(d.live_context).length ? `
      <div class="live-box">
        <h5>Live operational data, from the agent (not from the knowledge base)</h5>
        <dl>${Object.entries(d.live_context).map(([k, v]) => `<dt>${esc(k.replaceAll("_", " "))}</dt><dd>${esc(typeof v === "number" ? fmt(v) : v)}</dd>`).join("")}</dl>
      </div>` : "";
    const sources = d.sources && d.sources.length ? `
      <details class="sources" open>
        <summary>Sources (${d.sources.length})</summary>
        <ol>${d.sources.map((s) => `<li><strong>${esc(s.title)}</strong>, ${esc(s.section)} <span>(${esc(s.document)})</span><span class="src-excerpt">${esc(s.excerpt)}</span></li>`).join("")}</ol>
      </details>` : "";
    return `
      <div class="msg-a reveal">
        <div class="msg-a-head"><span class="tag">Knowledge base</span>${modeTag}</div>
        <div class="msg-a-text">${text}</div>
        ${d.notice ? `<p class="msg-notice">${esc(d.notice)}</p>` : ""}
        ${live}
        ${sources}
      </div>`;
  }

  async function ask(question) {
    const q = question.trim();
    if (!q) return;
    const thread = $("kbThread");
    thread.insertAdjacentHTML("beforeend", `<div class="msg-q">${esc(q)}</div>`);
    const qEl = thread.lastElementChild;
    const pending = document.createElement("div");
    pending.className = "msg-a typing";
    pending.innerHTML = `<span class="spinner"></span>Searching the knowledge base…`;
    thread.appendChild(pending);
    thread.scrollTop = thread.scrollHeight;
    $("kbSend").disabled = true;
    try {
      const d = await api("/api/rag/query", {
        method: "POST",
        body: JSON.stringify({ question: q, include_live_context: $("kbLive").checked }),
      });
      pending.outerHTML = renderAnswer(q, d);
    } catch (err) {
      pending.outerHTML = `<div class="msg-a"><p class="msg-notice">${esc(err.message)}</p></div>`;
    } finally {
      $("kbSend").disabled = false;
      // Bring the question and the start of its answer into view.
      thread.scrollTop = qEl.offsetTop - 4;
    }
  }

  // ------------------------------------------------------------------
  // Navigation highlighting
  // ------------------------------------------------------------------
  function setupScrollSpy() {
    const links = [...document.querySelectorAll(".nav-link")];
    const targets = links.map((l) => document.getElementById(l.dataset.section)).filter(Boolean);
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          links.forEach((l) => l.classList.toggle("is-active", l.dataset.section === entry.target.id));
        }
      });
    }, { rootMargin: "-35% 0px -55% 0px" });
    targets.forEach((t) => obs.observe(t));
  }

  // ------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------
  function bind() {
    $("buildingSelector").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-building]");
      if (!btn) return;
      app.building = btn.dataset.building;
      document.querySelectorAll("#buildingSelector button").forEach((b) => {
        const on = b === btn;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-checked", on ? "true" : "false");
      });
      refreshSecondary();
    });

    $("runBtn").addEventListener("click", () => runAnalysis({
      building: app.building,
      scenario: $("scenarioSelect").value,
    }));

    $("eventFeed").addEventListener("click", (e) => {
      const btn = e.target.closest(".feed-btn[data-actionable='1']");
      if (!btn) return;
      runAnalysis({ timestamp: btn.dataset.ts, building_id: btn.dataset.b, event_type: btn.dataset.t });
    });

    $("candidatesBody").addEventListener("click", (e) => {
      const btn = e.target.closest(".why-btn");
      if (!btn) return;
      const action = btn.dataset.why;
      const panel = btn.nextElementSibling;
      const open = panel.hasAttribute("hidden");
      panel.toggleAttribute("hidden", !open);
      btn.setAttribute("aria-expanded", String(open));
      btn.querySelector(".why-caret").textContent = open ? "▴" : "▾";
      if (open) app.openExplain.add(action); else app.openExplain.delete(action);
    });

    $("approveBtn").addEventListener("click", () => decide(true));
    $("rejectBtn").addEventListener("click", () => decide(false));
    $("resetBtn").addEventListener("click", resetAgent);

    document.querySelectorAll(".chart-toggles .toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!app.chart) return;
        const i = Number(btn.dataset.series);
        const visible = app.chart.isDatasetVisible(i);
        app.chart.setDatasetVisibility(i, !visible);
        btn.classList.toggle("is-on", !visible);
        btn.setAttribute("aria-pressed", String(!visible));
        app.chart.update();
      });
    });

    $("kbChips").addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (chip) ask(chip.textContent);
    });
    $("kbForm").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("kbInput");
      ask(input.value);
      input.value = "";
    });
  }

  async function init() {
    bind();
    setupScrollSpy();
    renderTrack({ lifecycle: ["MONITORING", "INVESTIGATING", "GATHERING_EVIDENCE", "ANALYZING", "FORECASTING", "SIMULATING", "VALIDATING", "WAITING_FOR_APPROVAL", "EXECUTING", "VERIFYING", "COMPLETED"], trail: [], has_run: false }, -1);
    loadHealth();
    try {
      await loadAgent();
    } catch (err) {
      toast(err.message, "error");
    }
    refreshSecondary();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
