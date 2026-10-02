/*
 * Smart Energy AI — 3D campus map for the Digital Twin page.
 *
 *   GET  /api/twin/map?timestamp=…   status of every building for one hour
 *   POST /api/agent/run              agent analyses the selected problem
 *   POST /api/agent/approve|reject   human decision → simulated execution
 *
 * A building with an ML-flagged problem at the chosen hour is red. The campus
 * itself is a target too: PEAK_DEMAND_RISK is campus-wide, so selecting the
 * campus ground paints every building red while that risk is open. A problem
 * the agent fixed (verified SUCCESS) turns green.
 *
 * Execution is the same simulated, human-approved path as AI Operations:
 * the "Execute" button IS the approval. Nothing is sent to equipment.
 *
 * After every agent call the snapshot is broadcast as "twin3d:agent" so the
 * rest of the page (candidate cards, what-if lab) stays in step.
 */
(() => {
  "use strict";

  if (document.body.dataset.page !== "digital_twin") return;
  const root = document.getElementById("twin3d");
  if (!root) return;

  const $ = (s, r = document) => r.querySelector(s);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[c]));
  const num = v => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v))) ? null : Number(v);
  const fmt = (v, d = 1) => num(v) === null ? "—" : num(v).toFixed(d);

  async function api(url, options = {}) {
    const res = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) }
    });
    const body = await res.json().catch(() => ({}));
    if (!body.success) throw new Error(body.error || `HTTP ${res.status}`);
    return body.data;
  }

  function toast(message) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toast.t);
    toast.t = setTimeout(() => el.classList.remove("show"), 3200);
  }

  const ui = {
    hour: $("#twin3d-hour"),
    chips: $("#twin3d-chips"),
    side: $("#twin3d-side"),
    stage: $("#twin3d-stage"),
    canvas: $("#twin3d-canvas"),
    labels: $("#twin3d-labels"),
    body: $("#twin3d-body"),
    toggle: $("#twin3d-toggle"),
    reset: $("#twin3d-reset"),
    fallback: $("#twin3d-fallback")
  };

  const model = {
    map: null,          // /api/twin/map payload
    agent: null,        // /api/agent/status snapshot
    selected: null,     // "CAMPUS" | "B001" | …
    busy: false,
    executing: false,   // drives the energy-pulse animation
    error: null
  };

  const TYPE_LABEL = {
    administration: "Administration", laboratory: "Laboratory", classroom: "Classroom"
  };

  // ======================================================================
  // DATA
  // ======================================================================

  async function loadMap(timestamp) {
    const q = timestamp ? `?timestamp=${encodeURIComponent(timestamp)}` : "";
    model.map = await api(`/api/twin/map${q}`);
    renderHours();
    renderChips();
    scene3d.applyStatus();
    renderSide();
  }

  async function loadAgent() {
    model.agent = await api("/api/agent/status");
  }

  function broadcast() {
    document.dispatchEvent(new CustomEvent("twin3d:agent", { detail: model.agent }));
  }

  function entry(id) {
    if (!model.map) return null;
    if (id === "CAMPUS") return model.map.campus;
    return model.map.buildings.find(b => b.building_id === id) || null;
  }

  /** Effective status as painted: buildings inherit an open campus problem when the campus is selected. */
  function paintedStatus(id) {
    const e = entry(id);
    if (!e) return "normal";
    if (id !== "CAMPUS" && model.selected === "CAMPUS" && model.map.campus.status !== "normal") {
      return e.status === "problem" ? "problem" : model.map.campus.status;
    }
    return e.status;
  }

  /** The agent is working on exactly this hour + target. */
  function agentOnSelection() {
    const ev = model.agent?.event;
    return !!(ev && model.map && ev.timestamp === model.map.focus_timestamp
      && (ev.building_id || "CAMPUS") === model.selected);
  }

  // ======================================================================
  // TOOLBAR
  // ======================================================================

  function renderHours() {
    const m = model.map;
    if (!m) return;
    const opts = (m.hours || []).map(h => {
      const where = h.buildings.map(b => b === "CAMPUS" ? "Campus" : b).join(", ");
      return `<option value="${esc(h.timestamp)}" ${h.timestamp === m.focus_timestamp ? "selected" : ""}>${esc(h.timestamp.slice(0, 16))} · ${esc(h.severity || "")} · ${esc(where)}</option>`;
    });
    ui.hour.innerHTML = opts.join("") || `<option>No events</option>`;
  }

  function renderChips() {
    const m = model.map;
    if (!m) return;
    const list = [m.campus, ...m.buildings];
    ui.chips.innerHTML = list.map(b => {
      const id = b.building_id;
      const label = id === "CAMPUS" ? "Campus" : `${id} ${b.name}`;
      return `<button type="button" role="tab" class="twin3d-chip is-${esc(b.status)} ${model.selected === id ? "active" : ""}"
        data-id="${esc(id)}" aria-selected="${model.selected === id}"><i class="twin3d-dot is-${esc(b.status)}"></i>${esc(label)}</button>`;
    }).join("");
  }

  // ======================================================================
  // SIDE PANEL — problem, solutions, execution
  // ======================================================================

  function eventLine(e, resolved) {
    const v = num(e.value);
    const measure = v === null ? "" : e.event_type === "PEAK_DEMAND_RISK"
      ? `${v.toFixed(1)}% of grid limit`
      : `${v > 0 ? "+" : ""}${v.toFixed(1)}% vs forecast`;
    return `<li class="twin3d-event sev-${esc((e.severity || "").toLowerCase())} ${resolved ? "is-resolved" : ""}">
      <div><b>${esc(e.event_label || e.event_type)}</b><span class="twin3d-sev">${esc(e.severity || "")}</span></div>
      ${measure ? `<em>${esc(measure)}</em>` : ""}
      <p>${esc(e.description || "")}</p>
    </li>`;
  }

  function statusPill(status) {
    const text = { problem: "Problem detected", resolved: "Resolved", normal: "Normal" }[status] || status;
    return `<span class="twin3d-pill is-${esc(status)}">${esc(text)}</span>`;
  }

  function candidateRow(c) {
    const ok = c.passes_constraints !== false;
    return `<li class="twin3d-cand ${c.is_selected ? "is-best" : ""} ${ok ? "" : "is-blocked"}">
      <div class="twin3d-cand-head">
        <b>${esc(c.label || c.action)}</b>
        ${c.is_selected ? `<span class="twin3d-tag">Recommended</span>` : ok ? "" : `<span class="twin3d-tag is-bad">Fails constraints</span>`}
      </div>
      <div class="twin3d-cand-nums">
        <span>−${esc(fmt(c.estimated_reduction_kw))} kW</span>
        <span>${esc(fmt(c.reduction_percent))}%</span>
        <span>score ${esc(fmt(c.optimization_score, 2))}</span>
      </div>
    </li>`;
  }

  const ASSET_NAMES = { battery: "Battery storage", ev: "EV charging hub", hvac: "Rooftop HVAC units" };
  function onMap(action) {
    const list = (scene3d.ACTION_ASSETS || {})[action] || [];
    if (!list.length) return "";
    return `<div class="twin3d-onmap"><span>On the map</span>${list.map(k => `<b class="is-${esc(k)}">${esc(ASSET_NAMES[k])}</b>`).join("")}</div>`;
  }

  function solutionBlock() {
    const a = model.agent;
    if (!a) return "";
    const rec = a.recommendation;
    const cands = Array.isArray(a.candidate_actions) ? [...a.candidate_actions] : [];
    cands.sort((x, y) => (y.is_selected - x.is_selected) || ((num(y.optimization_score) ?? -1e9) - (num(x.optimization_score) ?? -1e9)));
    const v = a.verification;
    const st = a.state;
    let html = "";

    if (st === "FAILED") {
      return `<div class="twin3d-result is-bad"><b>The agent stopped.</b><p>${esc(a.error || a.last_error || "Run the analysis again.")}</p></div>`;
    }

    if (a.replanned && st === "WAITING_FOR_APPROVAL" && v) {
      html += `<div class="twin3d-result is-warn"><b>Target not met. The agent proposes an alternative.</b>
        <p>${esc(v.intended_label || "")}: ${esc(fmt(v.achieved_reduction_kw))} / ${esc(fmt(v.expected_reduction_kw))} kW (${esc(fmt(v.performance_ratio_percent))}%)</p></div>`;
    }

    if (rec) {
      const pts = (rec.reason?.points || []).slice(0, 3).map(p => `<li>${esc(p)}</li>`).join("");
      html += `<div class="twin3d-rec">
        <div class="panel-kicker">PROPOSED SOLUTION</div>
        <h4>${esc(rec.label)}</h4>
        <div class="twin3d-rec-nums">
          <div><span>Reduction</span><b>${esc(fmt(rec.estimated_reduction_kw))} kW</b></div>
          <div><span>Load</span><b>${esc(fmt(rec.original_predicted_load))} → ${esc(fmt(rec.new_predicted_load))} kW</b></div>
        </div>
        ${pts ? `<ul class="twin3d-why">${pts}</ul>` : ""}
        ${onMap(rec.action)}
      </div>`;
    }

    if (a.recommendation_scope_note) {
      html += `<p class="twin3d-note">${esc(a.recommendation_scope_note)}</p>`;
    }

    if (cands.length && st !== "COMPLETED") {
      html += `<div class="panel-kicker twin3d-sub">ALL SIMULATED SOLUTIONS</div><ul class="twin3d-cands">${cands.map(candidateRow).join("")}</ul>`;
    }

    if (st === "WAITING_FOR_APPROVAL") {
      html += `<div class="twin3d-actions">
        <button type="button" class="primary-btn" data-act="approve">Execute solution</button>
        <button type="button" class="secondary-btn" data-act="reject">Reject</button>
      </div>
      <p class="twin3d-note">Executing is your approval. The action runs in simulation only, then the agent verifies the result.</p>`;
    } else if (st === "COMPLETED" && v) {
      const okRun = v.verification_status === "SUCCESS";
      html += `<div class="twin3d-result ${okRun ? "is-ok" : "is-warn"}">
        <b>${okRun ? "Problem resolved" : "Executed, below target"}</b>
        <p>${esc(v.verified_label || v.intended_label || "")} · ${esc(fmt(v.achieved_reduction_kw))} / ${esc(fmt(v.expected_reduction_kw))} kW (${esc(fmt(v.performance_ratio_percent))}%)</p>
      </div>`;
    } else if (st === "COMPLETED" && a.last_decision?.decision === "REJECTED") {
      html += `<div class="twin3d-result is-warn"><b>Rejected. Nothing was executed.</b></div>`;
    }
    return html;
  }

  function renderSide() {
    const m = model.map;
    if (!m) return;
    scene3d.applyAssets?.();
    const id = model.selected;
    if (!id) {
      const open = [m.campus, ...m.buildings].filter(b => b.status === "problem");
      ui.side.innerHTML = `
        <div class="panel-kicker">CAMPUS STATUS</div>
        <h4 class="twin3d-title">${open.length ? `${open.length} open problem${open.length > 1 ? "s" : ""}` : "All clear"}</h4>
        <p class="twin3d-note">${esc(m.focus_timestamp || "")}</p>
        ${open.length ? `<ul class="twin3d-open">${open.map(b => `<li><button type="button" class="twin3d-link" data-id="${esc(b.building_id)}"><i class="twin3d-dot is-problem"></i>${esc(b.building_id === "CAMPUS" ? "Campus" : `${b.building_id} ${b.name}`)}</button></li>`).join("")}</ul>` : ""}
        <p class="twin3d-note">Select a building on the map or above.</p>`;
      return;
    }

    const e = entry(id);
    if (!e) return;
    const isCampus = id === "CAMPUS";
    const status = e.status;
    const title = isCampus ? "Campus" : `${e.name}`;
    const assets = isCampus ? "" : [
      e.has_solar ? "Solar PV" : null,
      e.has_ev_charging ? "EV charging" : null,
      e.has_battery ? "Battery" : null
    ].filter(Boolean).map(x => `<span class="twin3d-asset">${esc(x)}</span>`).join("");

    const facts = isCampus
      ? `<div><span>Buildings</span><b>${m.buildings.length}</b></div>
         <div><span>Live load</span><b>${esc(fmt(m.buildings.reduce((s, b) => s + (num(b.live_load_kw) || 0), 0)))} kW</b></div>`
      : `<div><span>Live load</span><b>${esc(fmt(e.live_load_kw))} kW</b></div>
         <div><span>Solar</span><b>${esc(fmt(e.live_solar_kw))} kW</b></div>
         <div><span>Floor area</span><b>${esc(fmt(e.floor_area_m2, 0))} m²</b></div>
         <div><span>Max power</span><b>${esc(fmt(e.maximum_power_kw, 0))} kW</b></div>`;

    let actions = "";
    if (agentOnSelection()) {
      actions = solutionBlock();
    } else if (status === "problem") {
      actions = `<div class="twin3d-actions">
        <button type="button" class="primary-btn" data-act="analyze">Analyze &amp; suggest solutions</button>
      </div>
      <p class="twin3d-note">The agent gathers evidence, forecasts, simulates every candidate action in the digital twin and recommends the best one.</p>`;
    } else if (status === "resolved") {
      actions = `<div class="twin3d-result is-ok"><b>Problem resolved</b><p>The agent executed and verified a solution for this hour.</p></div>`;
    } else {
      actions = `<p class="twin3d-note">No problem flagged here at this hour. Pick an hour from the list that names this building.</p>`;
    }

    ui.side.innerHTML = `
      <div class="twin3d-side-head">
        <div>
          <div class="panel-kicker">${esc(isCampus ? "CAMPUS-WIDE" : `${id} · ${(TYPE_LABEL[e.type] || e.type || "").toUpperCase()}`)}</div>
          <h4 class="twin3d-title">${esc(title)}</h4>
        </div>
        ${statusPill(status)}
      </div>
      ${assets ? `<div class="twin3d-assets">${assets}</div>` : ""}
      <div class="twin3d-facts">${facts}</div>
      ${e.events?.length ? `<div class="panel-kicker twin3d-sub">PROBLEMS AT ${esc((m.focus_timestamp || "").slice(0, 16))}</div><ul class="twin3d-events">${e.events.map(x => eventLine(x, status === "resolved")).join("")}</ul>` : ""}
      ${model.busy ? `<div class="twin3d-busy"><span class="twin3d-spin"></span>${esc(model.executing ? "Executing in simulation and verifying…" : "The agent is analysing…")}</div>` : actions}
    `;
  }

  // ======================================================================
  // ACTIONS
  // ======================================================================

  function select(id) {
    model.selected = id;
    renderChips();
    scene3d.applyStatus();
    scene3d.focus(id);
    renderSide();
  }

  async function analyze() {
    const id = model.selected;
    const e = entry(id);
    if (!e || model.busy) return;
    const worst = [...(e.events || [])].sort((a, b) => rank(b.severity) - rank(a.severity))[0];
    model.busy = true; model.executing = false; renderSide();
    try {
      model.agent = await api("/api/agent/run", {
        method: "POST",
        body: JSON.stringify({
          timestamp: model.map.focus_timestamp,
          building_id: id,
          event_type: worst?.event_type
        })
      });
      broadcast();
      toast(model.agent.state === "WAITING_FOR_APPROVAL" ? "Solutions ready. Your approval executes one." : "Analysis completed.");
    } catch (err) {
      toast(`Agent: ${err.message}`);
    } finally {
      model.busy = false;
      renderSide();
    }
  }

  async function decide(path) {
    if (model.busy) return;
    model.busy = true;
    model.executing = path === "approve";
    renderSide();
    const started = performance.now();
    try {
      const snap = await api(`/api/agent/${path}`, { method: "POST", body: "{}" });
      // Let the energy pulse play for a moment so the execution is visible.
      const wait = model.executing ? Math.max(0, 1400 - (performance.now() - started)) : 0;
      await new Promise(r => setTimeout(r, wait));
      model.agent = snap;
      broadcast();
      if (path === "approve") {
        if (snap.state === "COMPLETED" && snap.verification?.verification_status === "SUCCESS") toast("Executed and verified. Problem resolved.");
        else if (snap.state === "WAITING_FOR_APPROVAL" && snap.replanned) toast("Target not met. The agent proposes an alternative.");
        else toast("Executed (simulated).");
      } else {
        toast("Rejected. Nothing was executed.");
      }
      await loadMap(model.map?.focus_timestamp);
    } catch (err) {
      toast(`Decision: ${err.message}`);
    } finally {
      model.busy = false;
      model.executing = false;
      renderSide();
    }
  }

  const rank = s => ({ CRITICAL: 3, HIGH: 2, ELEVATED: 1 }[s] || 0);

  // ======================================================================
  // 3D SCENE
  // ======================================================================

  const scene3d = (() => {
    const T = window.THREE;
    let ok = false;
    let renderer, scene, camera, raycaster, pointer, clock;
    let ground, groundGlow, perimeter;
    const B = {};            // building_id → { group, mats, roofMats, edges, marker, label, center, status }
    let campusLabel = null, campusMarker = null;
    const pulses = [];
    const flows = {};        // name → { curve, dots, line, speed, on, color }
    const assets = {};       // solar | battery | ev → { label, … }
    let hoverId = null;

    // Campus extent (metres-ish). Everything clickable inside it selects CAMPUS.
    const HALF_W = 130, HALF_D = 95;
    const HOME = { dist: 300, theta: -0.7, phi: 0.92 };
    const orbit = { theta: HOME.theta, phi: HOME.phi, dist: HOME.dist, target: null, goal: null, goalDist: HOME.dist, auto: true };
    let dragging = false, dragMoved = false, last = { x: 0, y: 0 };
    let visible = true;

    const COLORS = {
      problem: 0xe0464e, resolved: 0x4fbf7f, selected: 0xdeb85c,
      tint: { normal: 0xffffff, problem: 0xff8080, resolved: 0xa6eac0 }
    };

    const LAYOUT = {
      B001: { x: -64, z: -22, floors: 4, aspect: 1.7, style: "admin" },
      B002: { x: 22, z: -38, floors: 3, aspect: 1.3, style: "labs" },
      B003: { x: -4, z: 40, floors: 3, aspect: 2.4, style: "classrooms" }
    };
    const FLOOR_H = 4.2;

    // Which campus assets each agent action works through.
    const ACTION_ASSETS = {
      BATTERY_DISCHARGE: ["battery"],
      EV_CHARGING_SHIFT: ["ev"],
      HVAC_SETPOINT_ADJUSTMENT: ["hvac"],
      COMBINED_ACTION: ["hvac", "ev", "battery"]
    };

    // ---------------- shared materials ---------------------------------
    let M = null;
    function materials() {
      const std = (color, o = {}) => new T.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0.05, ...o });
      M = {
        grass: std(0x5b9a5f, { roughness: 1 }),
        grassDark: std(0x4a8550, { roughness: 1 }),
        path: std(0xd8cfbd, { roughness: 1 }),
        plaza: std(0xe4ddcf, { roughness: 0.95 }),
        asphalt: std(0x34373d, { roughness: 1 }),
        gravel: std(0x9a958b, { roughness: 1 }),
        pad: std(0xc9c6bf, { roughness: 1 }),
        paint: new T.MeshBasicMaterial({ color: 0xf2f2ee }),
        paintYellow: new T.MeshBasicMaterial({ color: 0xf0c53c }),
        concrete: std(0xf1eee8, { roughness: 0.7 }),
        plinth: std(0x7d7a75, { roughness: 0.9 }),
        trim: std(0x3e434b, { roughness: 0.6, metalness: 0.3 }),
        metal: std(0xa6acb4, { roughness: 0.45, metalness: 0.6 }),
        darkMetal: std(0x4b5058, { roughness: 0.5, metalness: 0.5 }),
        glass: new T.MeshStandardMaterial({ color: 0x9fc4e0, roughness: 0.08, metalness: 0.4, transparent: true, opacity: 0.45 }),
        pv: std(0x1d3a78, { roughness: 0.22, metalness: 0.65, emissive: 0x081633, emissiveIntensity: 1 }),
        pvFrame: std(0xd4d7db, { roughness: 0.4, metalness: 0.7 }),
        hvac: std(0xc7ccd2, { roughness: 0.45, metalness: 0.5, emissive: 0x2a8cff, emissiveIntensity: 0 }),
        fan: std(0x2b2f35, { roughness: 0.6 }),
        batt: std(0xf3f4f5, { roughness: 0.5, metalness: 0.2, emissive: 0x29d07a, emissiveIntensity: 0 }),
        battStripe: std(0x0f9d8f, { roughness: 0.4, emissive: 0x0f9d8f, emissiveIntensity: 0.35 }),
        socFill: new T.MeshBasicMaterial({ color: 0x3ee07f }),
        socBack: new T.MeshBasicMaterial({ color: 0x1f2a24 }),
        transformer: std(0x8b939d, { roughness: 0.5, metalness: 0.5 }),
        insulator: std(0x7a4b2c, { roughness: 0.5 }),
        charger: std(0x23272d, { roughness: 0.4, metalness: 0.3 }),
        evScreen: new T.MeshBasicMaterial({ color: 0x35d07f }),
        evRing: new T.MeshBasicMaterial({ color: 0x40c4ff }),
        tyre: std(0x1b1d20, { roughness: 0.9 }),
        carGlass: std(0x1c2836, { roughness: 0.1, metalness: 0.6 }),
        trunk: std(0x6e5139),
        lampHead: new T.MeshBasicMaterial({ color: 0xffe2a6 }),
        water: std(0x6fb6e6, { roughness: 0.1, metalness: 0.3, emissive: 0x16486b, emissiveIntensity: 0.4 }),
        flag1: std(0x007a3d, { side: T.DoubleSide }),
        flag2: std(0xce1126, { side: T.DoubleSide }),
        leaves: [0x3f8f4e, 0x4d9f55, 0x2f7d48, 0x6aa84f].map(c => std(c, { roughness: 0.85, flatShading: true }))
      };
    }

    function init() {
      if (!T) return false;
      try {
        renderer = new T.WebGLRenderer({ canvas: ui.canvas, antialias: true, alpha: false });
      } catch (_) { return false; }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = T.PCFSoftShadowMap;
      renderer.toneMapping = T.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.1;

      scene = new T.Scene();
      camera = new T.PerspectiveCamera(40, 1, 1, 2500);
      raycaster = new T.Raycaster();
      pointer = new T.Vector2();
      clock = new T.Clock();
      orbit.target = new T.Vector3(0, 4, 0);
      orbit.goal = orbit.target.clone();

      scene.add(new T.HemisphereLight(0xe8f1ff, 0x4a4436, 0.95));
      const sun = new T.DirectionalLight(0xfff0d6, 1.6);
      sun.position.set(-120, 180, 110);
      sun.castShadow = true;
      sun.shadow.mapSize.set(2048, 2048);
      sun.shadow.bias = -0.0004;
      Object.assign(sun.shadow.camera, { left: -190, right: 190, top: 160, bottom: -160, near: 10, far: 600 });
      scene.add(sun);

      materials();
      buildGround();
      buildRoads();
      buildPlaza();
      buildSolarFarm();
      buildBatteryYard();
      buildSubstation();
      buildEvHub();
      buildTrees();
      buildLamps();
      buildFlows();
      applyTheme();
      bindInput();
      resize();
      new ResizeObserver(resize).observe(ui.stage);
      new MutationObserver(applyTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      if ("IntersectionObserver" in window) {
        new IntersectionObserver(es => { visible = es.some(e => e.isIntersecting); }).observe(ui.stage);
      }
      requestAnimationFrame(loop);
      return true;
    }

    function applyTheme() {
      const light = document.documentElement.getAttribute("data-theme") === "light";
      const bg = new T.Color(light ? 0xdfe7ee : 0x111318);
      scene.background = bg;
      scene.fog = new T.Fog(bg, 420, 900);
      if (ground) ground.material.color.set(light ? 0xc9cfc8 : 0x23262b);
    }

    // ---------------- helpers ------------------------------------------

    function mesh(geo, mat, id, { x = 0, y = 0, z = 0, cast = true, receive = true, parent = scene } = {}) {
      const m = new T.Mesh(geo, mat);
      m.position.set(x, y, z);
      m.castShadow = cast;
      m.receiveShadow = receive;
      if (id) m.userData.id = id;
      parent.add(m);
      return m;
    }

    function flat(w, d, mat, x, z, y = 0.06, id = "CAMPUS", parent = scene) {
      const m = new T.Mesh(new T.PlaneGeometry(w, d), mat);
      m.rotation.x = -Math.PI / 2;
      m.position.set(x, y, z);
      m.receiveShadow = true;
      if (id) m.userData.id = id;
      parent.add(m);
      return m;
    }

    /** One InstancedMesh from a list of {x,y,z,rx,ry,rz,sx,sy,sz}. */
    function instanced(geo, mat, items, id = "CAMPUS", parent = scene) {
      const im = new T.InstancedMesh(geo, mat, items.length);
      const o = new T.Object3D();
      items.forEach((it, i) => {
        o.position.set(it.x || 0, it.y || 0, it.z || 0);
        o.rotation.set(it.rx || 0, it.ry || 0, it.rz || 0);
        o.scale.set(it.sx || 1, it.sy || 1, it.sz || 1);
        o.updateMatrix();
        im.setMatrixAt(i, o.matrix);
      });
      im.castShadow = true;
      im.receiveShadow = true;
      im.userData.id = id;
      parent.add(im);
      return im;
    }

    // ---------------- ground, roads, plaza ------------------------------

    function buildGround() {
      ground = mesh(new T.PlaneGeometry(2400, 2400), new T.MeshStandardMaterial({ color: 0x23262b, roughness: 1 }), null, { cast: false });
      ground.rotation.x = -Math.PI / 2;

      flat(HALF_W * 2, HALF_D * 2, M.grass, 0, 0, 0.04);
      // lawn stripes, the kind a mower leaves
      for (let i = -HALF_W + 10; i < HALF_W; i += 20) flat(10, HALF_D * 2, M.grassDark, i, 0, 0.045);

      groundGlow = flat(HALF_W * 2, HALF_D * 2, new T.MeshBasicMaterial({ color: COLORS.problem, transparent: true, opacity: 0, depthWrite: false }), 0, 0, 0.3);

      // low perimeter wall + coloured status line on top
      const wallMat = M.plinth;
      [[0, -HALF_D, HALF_W * 2, 0.8], [0, HALF_D, HALF_W * 2, 0.8], [-HALF_W, 0, 0.8, HALF_D * 2], [HALF_W, 0, 0.8, HALF_D * 2]].forEach(([x, z, w, d]) => {
        mesh(new T.BoxGeometry(w, 1.1, d), wallMat, "CAMPUS", { x, y: 0.55, z });
      });
      const pts = [[-HALF_W, -HALF_D], [HALF_W, -HALF_D], [HALF_W, HALF_D], [-HALF_W, HALF_D]].map(([x, z]) => new T.Vector3(x, 1.25, z));
      perimeter = new T.LineLoop(new T.BufferGeometry().setFromPoints(pts), new T.LineBasicMaterial({ color: 0x8a8f98 }));
      scene.add(perimeter);
    }

    function buildRoads() {
      // public road along the south edge, outside the wall
      flat(520, 12, M.asphalt, 0, HALF_D + 10, 0.05, null);
      for (let x = -250; x < 250; x += 9) flat(4.5, 0.35, M.paint, x, HALF_D + 10, 0.07, null);
      // campus entrance road to the EV hub
      flat(9, 22, M.asphalt, -84, HALF_D - 4, 0.07);
      // pedestrian spine and branches
      const P = M.path;
      flat(HALF_W * 2 - 6, 6, P, 0, 10, 0.08);          // east–west spine
      flat(6, HALF_D * 2 - 6, P, -30, 0, 0.08);         // north–south spine
      flat(6, 26, P, -64, -2, 0.08);                    // to Administration
      flat(6, 22, P, 22, -9, 0.08);                     // to Labs
      flat(6, 14, P, -4, 21, 0.08);                     // to Classrooms
      flat(6, 60, P, 66, -38, 0.08);                    // service path to the energy yard
    }

    function buildPlaza() {
      const g = new T.Group();
      g.position.set(-30, 0, 10);
      const disc = new T.Mesh(new T.CircleGeometry(13, 48), M.plaza);
      disc.rotation.x = -Math.PI / 2;
      disc.position.y = 0.1;
      disc.receiveShadow = true;
      disc.userData.id = "CAMPUS";
      g.add(disc);
      mesh(new T.CylinderGeometry(5, 5.4, 1, 32), M.concrete, "CAMPUS", { y: 0.5, parent: g });
      mesh(new T.CylinderGeometry(4.4, 4.4, 0.2, 32), M.water, "CAMPUS", { y: 1.0, parent: g, cast: false });
      mesh(new T.CylinderGeometry(0.5, 0.8, 3, 12), M.concrete, "CAMPUS", { y: 1.6, parent: g });
      scene.add(g);
    }

    // ---------------- trees and lamps -----------------------------------

    function tree(x, z, s = 1, k = 0) {
      const g = new T.Group();
      g.position.set(x, 0, z);
      mesh(new T.CylinderGeometry(0.35 * s, 0.5 * s, 3.2 * s, 6), M.trunk, "CAMPUS", { y: 1.6 * s, parent: g });
      const leaf = M.leaves[k % M.leaves.length];
      mesh(new T.IcosahedronGeometry(2.8 * s, 0), leaf, "CAMPUS", { y: 4.6 * s, parent: g });
      mesh(new T.IcosahedronGeometry(2.0 * s, 0), leaf, "CAMPUS", { x: 0.9 * s, y: 6.2 * s, z: -0.5 * s, parent: g });
      scene.add(g);
    }

    function buildTrees() {
      const spots = [
        [-120, -85, 1.2], [-104, -86, 1], [-120, -60, 1.1], [-120, -10, 1], [-120, 15, 1.2], [-100, 10, 0.9],
        [-45, -55, 1], [-45, -78, 1.2], [-10, -80, 1], [0, -62, 0.9], [50, -84, 1.1], [44, -6, 0.9],
        [-20, 84, 1], [28, 62, 1.2], [36, 26, 1], [40, 46, 0.9], [-48, 35, 1], [-48, 70, 1.1],
        [-14, 26, 0.8], [8, 26, 0.8], [-40, 0, 0.8], [-20, 20, 0.8], [56, 84, 1], [20, 84, 1.1],
        [-30, 85, 1], [120, 82, 1.1], [62, 10, 0.9], [-90, -40, 1], [-40, -30, 0.9]
      ];
      spots.forEach(([x, z, s], i) => tree(x, z, s, i));
    }

    function buildLamps() {
      const posts = [], heads = [];
      const spots = [[-110, 13], [-90, 13], [-70, 13], [-50, 13], [-10, 13], [10, 13], [30, 13], [50, 13], [70, 13], [90, 13],
        [-33, -60], [-33, -35], [-33, 35], [-33, 60], [69, -20], [69, -50]];
      spots.forEach(([x, z]) => {
        posts.push({ x, y: 3, z });
        heads.push({ x, y: 6.2, z });
      });
      instanced(new T.CylinderGeometry(0.15, 0.2, 6, 6), M.darkMetal, posts);
      const h = instanced(new T.SphereGeometry(0.55, 10, 8), M.lampHead, heads);
      h.castShadow = false;
    }

    // ---------------- solar farm ----------------------------------------

    function buildSolarFarm() {
      const x0 = 76, x1 = 122, z0 = 0, z1 = 72;
      flat(x1 - x0 + 6, z1 - z0 + 6, M.gravel, (x0 + x1) / 2, (z0 + z1) / 2, 0.07, "CAMPUS");
      const panels = [], frames = [], legs = [];
      for (let z = z0 + 4; z <= z1 - 4; z += 9) {
        for (let x = x0 + 1.4; x <= x1 - 1.4; x += 2.3) {
          panels.push({ x, y: 2.1, z, rx: -0.5 });
          frames.push({ x, y: 2.0, z, rx: -0.5 });
          if (Math.round((x - x0) / 2.3) % 3 === 0) {
            legs.push({ x, y: 0.9, z: z - 1.2, sy: 1 });
            legs.push({ x, y: 1.4, z: z + 1.2, sy: 1.6 });
          }
        }
      }
      instanced(new T.BoxGeometry(2.15, 0.12, 4.4), M.pv, panels);
      instanced(new T.BoxGeometry(2.25, 0.08, 4.55), M.pvFrame, frames);
      instanced(new T.CylinderGeometry(0.1, 0.1, 1.8, 5), M.metal, legs);
      // inverter skid
      mesh(new T.BoxGeometry(5, 2.6, 2.8), M.concrete, "CAMPUS", { x: x0 - 1, y: 1.3, z: -6 });
      mesh(new T.BoxGeometry(5.1, 0.4, 2.9), M.battStripe, "CAMPUS", { x: x0 - 1, y: 2.2, z: -6 });
      fence(x0 - 4, x1 + 4, z0 - 4, z1 + 4);

      const label = makeLabel("CAMPUS", "is-asset is-solar");
      label.anchor = new T.Vector3((x0 + x1) / 2, 10, (z0 + z1) / 2);
      assets.solar = { label };
    }

    function fence(x0, x1, z0, z1) {
      const posts = [];
      const add = (x, z) => posts.push({ x, y: 1.1, z });
      for (let x = x0; x <= x1; x += 4) { add(x, z0); add(x, z1); }
      for (let z = z0; z <= z1; z += 4) { add(x0, z); add(x1, z); }
      instanced(new T.BoxGeometry(0.15, 2.2, 0.15), M.metal, posts);
      const pts = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
      [1.0, 2.0].forEach(y => {
        const loop = new T.LineLoop(new T.BufferGeometry().setFromPoints(pts.map(([x, z]) => new T.Vector3(x, y, z))), new T.LineBasicMaterial({ color: 0x9aa0a6 }));
        scene.add(loop);
      });
    }

    // ---------------- battery storage -----------------------------------

    function buildBatteryYard() {
      const cx = 86, cz = -66;
      flat(40, 22, M.pad, cx, cz, 0.08);
      const socBars = [];
      for (let i = 0; i < 4; i++) {
        const x = cx - 14.5 + i * 9.6;
        const g = new T.Group();
        g.position.set(x, 0, cz);
        mesh(new T.BoxGeometry(8, 0.4, 13), M.plinth, "CAMPUS", { y: 0.2, parent: g });
        mesh(new T.BoxGeometry(7.4, 4.4, 12.2), M.batt, "CAMPUS", { y: 2.6, parent: g });
        mesh(new T.BoxGeometry(7.5, 0.55, 12.3), M.battStripe, "CAMPUS", { y: 3.9, parent: g, cast: false });
        // door seams
        for (let k = -1; k <= 1; k++) mesh(new T.BoxGeometry(0.06, 3.6, 0.05), M.trim, null, { x: k * 1.8, y: 2.4, z: 6.13, parent: g, cast: false });
        // rooftop cooling
        mesh(new T.BoxGeometry(3, 0.9, 2.6), M.metal, "CAMPUS", { y: 5.25, z: -3.5, parent: g });
        mesh(new T.CylinderGeometry(0.9, 0.9, 0.15, 16), M.fan, null, { y: 5.75, z: -3.5, parent: g, cast: false });
        // state-of-charge bar on the front face
        mesh(new T.BoxGeometry(5.4, 0.7, 0.05), M.socBack, null, { y: 1.3, z: 6.14, parent: g, cast: false });
        const fill = mesh(new T.BoxGeometry(5.2, 0.5, 0.06), M.socFill, null, { y: 1.3, z: 6.17, parent: g, cast: false });
        socBars.push(fill);
        scene.add(g);
      }
      fence(cx - 21, cx + 21, cz - 12, cz + 12);
      const label = makeLabel("CAMPUS", "is-asset is-battery");
      label.anchor = new T.Vector3(cx, 11, cz);
      assets.battery = { label, socBars, soc: null };
    }

    // ---------------- substation ---------------------------------------

    function buildSubstation() {
      const cx = 120, cz = -66;
      flat(20, 22, M.gravel, cx, cz, 0.09);
      for (let i = 0; i < 2; i++) {
        const g = new T.Group();
        g.position.set(cx, 0, cz - 5 + i * 10);
        mesh(new T.BoxGeometry(6, 4.5, 4.5), M.transformer, "CAMPUS", { y: 2.25, parent: g });
        for (let f = -2; f <= 2; f++) mesh(new T.BoxGeometry(0.25, 3.4, 5.2), M.transformer, "CAMPUS", { x: f * 1.1, y: 2.2, parent: g });
        for (let k = -1; k <= 1; k++) mesh(new T.CylinderGeometry(0.25, 0.35, 2.2, 8), M.insulator, "CAMPUS", { x: k * 1.6, y: 5.6, parent: g });
        scene.add(g);
      }
      // gantry carrying the grid feed off campus
      [-8, 8].forEach(dz => mesh(new T.BoxGeometry(0.6, 12, 0.6), M.metal, "CAMPUS", { x: cx + 7, y: 6, z: cz + dz }));
      mesh(new T.BoxGeometry(0.6, 0.6, 17), M.metal, "CAMPUS", { x: cx + 7, y: 11.7, z: cz });
      [-5, 0, 5].forEach(dz => {
        const pts = [new T.Vector3(cx + 7, 11.4, cz + dz), new T.Vector3(cx + 40, 9, cz + dz), new T.Vector3(cx + 90, 11.4, cz + dz)];
        scene.add(new T.Line(new T.BufferGeometry().setFromPoints(new T.QuadraticBezierCurve3(...pts).getPoints(20)), new T.LineBasicMaterial({ color: 0x5c6168 })));
      });
      fence(cx - 10, cx + 10, cz - 11, cz + 11);

      campusMarker = makeMarker();
      campusMarker.position.set(cx, 20, cz);
      campusMarker.userData.baseY = 20;
      scene.add(campusMarker);
      campusLabel = makeLabel("CAMPUS");
      campusLabel.anchor = new T.Vector3(cx, 14, cz);
    }

    // ---------------- EV charging hub -----------------------------------

    function car(color, x, z, ry) {
      const g = new T.Group();
      g.position.set(x, 0, z);
      g.rotation.y = ry;
      const paint = new T.MeshStandardMaterial({ color, roughness: 0.3, metalness: 0.6 });
      mesh(new T.BoxGeometry(2.1, 1.0, 4.5), paint, "CAMPUS", { y: 0.85, parent: g });
      mesh(new T.BoxGeometry(1.85, 0.8, 2.4), M.carGlass, "CAMPUS", { y: 1.7, z: -0.2, parent: g });
      const wheel = new T.CylinderGeometry(0.45, 0.45, 0.35, 12);
      [[-1, 1.4], [1, 1.4], [-1, -1.4], [1, -1.4]].forEach(([sx, sz]) => {
        const w = mesh(wheel, M.tyre, "CAMPUS", { x: sx * 1.0, y: 0.45, z: sz, parent: g });
        w.rotation.z = Math.PI / 2;
      });
      scene.add(g);
    }

    function buildEvHub() {
      const cx = -84, cz = 62, W = 52, D = 28;
      flat(W, D, M.asphalt, cx, cz, 0.08);
      const bays = 10, bw = W / bays;
      const screens = [], rings = [];
      for (let i = 0; i <= bays; i++) flat(0.25, 9, M.paint, cx - W / 2 + i * bw, cz - D / 2 + 5, 0.1);
      flat(W, 0.25, M.paint, cx, cz - D / 2 + 9.6, 0.1);
      for (let i = 0; i < bays; i++) {
        const x = cx - W / 2 + bw * (i + 0.5);
        const z = cz - D / 2 + 0.9;
        mesh(new T.BoxGeometry(0.9, 0.25, 0.7), M.plinth, "CAMPUS", { x, y: 0.12, z });
        mesh(new T.BoxGeometry(0.75, 2.0, 0.5), M.charger, "CAMPUS", { x, y: 1.2, z });
        screens.push(mesh(new T.PlaneGeometry(0.5, 0.45), M.evScreen, "CAMPUS", { x, y: 1.75, z: z + 0.26, cast: false }));
        const ring = mesh(new T.TorusGeometry(0.28, 0.05, 6, 20), M.evRing, "CAMPUS", { x, y: 1.15, z: z + 0.27, cast: false });
        rings.push(ring);
        // painted EV logo in the bay
        flat(1.6, 1.6, M.paintYellow, x, cz - D / 2 + 6, 0.11);
      }
      // solar carport over the bays
      for (let s = 0; s < 2; s++) {
        const x = cx - W / 4 + s * (W / 2);
        [-11, 11].forEach(dx => mesh(new T.BoxGeometry(0.5, 4.6, 0.5), M.metal, "CAMPUS", { x: x + dx, y: 2.3, z: cz - D / 2 + 9.2 }));
        const roof = mesh(new T.BoxGeometry(W / 2 - 1, 0.3, 10), M.pvFrame, "CAMPUS", { x, y: 4.9, z: cz - D / 2 + 5 });
        roof.rotation.x = 0.08;
        const pv = mesh(new T.BoxGeometry(W / 2 - 1.6, 0.12, 9.4), M.pv, "CAMPUS", { x, y: 5.1, z: cz - D / 2 + 5 });
        pv.rotation.x = 0.08;
      }
      const colors = [0xf2f2f2, 0x1f4e9c, 0xc0392b, 0x2d2d2d, 0x8fa3b0, 0xe6b422, 0x3c8d5a];
      [0, 1, 3, 4, 6, 7, 9].forEach((bay, k) => car(colors[k], cx - W / 2 + bw * (bay + 0.5), cz - D / 2 + 4.6, 0));
      // two cars in the open lot
      car(0x6b7a8f, cx - 12, cz + 8, Math.PI / 2);
      car(0xd9d9d9, cx + 14, cz + 8, Math.PI / 2);

      const label = makeLabel("CAMPUS", "is-asset is-ev");
      label.anchor = new T.Vector3(cx, 10, cz);
      assets.ev = { label, screens, rings, bays };
    }

    // ---------------- energy flows -------------------------------------

    function flow(name, points, color, n = 10, speed = 0.12) {
      const curve = new T.CatmullRomCurve3(points.map(([x, z, y = 0.7]) => new T.Vector3(x, y, z)), false, "centripetal");
      const line = new T.Line(new T.BufferGeometry().setFromPoints(curve.getPoints(120)), new T.LineBasicMaterial({ color, transparent: true, opacity: 0.35 }));
      scene.add(line);
      const dotMat = new T.MeshBasicMaterial({ color, transparent: true, opacity: 1 });
      const geo = new T.SphereGeometry(0.55, 10, 8);
      const dots = [];
      for (let i = 0; i < n; i++) {
        const d = new T.Mesh(geo, dotMat);
        d.userData.u = i / n;
        scene.add(d);
        dots.push(d);
      }
      flows[name] = { curve, line, dots, dotMat, speed, base: speed, on: true, color };
    }

    function buildFlows() {
      const SUB = [109, -62];
      flow("solar", [[76, -6], [70, -30], [86, -52]], 0xffc845, 10, 0.1);
      flow("battery", [[100, -66], [104, -64], [109, -62]], 0x5ce08a, 4, 0.25);
      flow("gridB002", [SUB, [70, -54], [52, -40]], 0x40c4ff, 10, 0.12);
      flow("gridB001", [SUB, [66, -54], [66, 10], [-30, 10], [-64, 10], [-64, -8]], 0x40c4ff, 26, 0.05);
      flow("gridB003", [SUB, [66, -54], [66, 10], [-4, 10], [-4, 28]], 0x40c4ff, 20, 0.06);
      flow("gridEV", [SUB, [66, -54], [66, 10], [-84, 10], [-84, 44]], 0x7aa8ff, 26, 0.05);
      flows.battery.on = false;
    }

    // ---------------- buildings ----------------------------------------

    function facadeTexture(seed) {
      // 4 bays × 2 floors, tiled across each facade.
      const c = document.createElement("canvas");
      c.width = 512; c.height = 256;
      const g = c.getContext("2d");
      let s = seed * 9301 + 49297;
      const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
      for (let f = 0; f < 2; f++) {
        const y0 = f * 128;
        g.fillStyle = "#ece8e1";                       // spandrel / slab band
        g.fillRect(0, y0, 512, 128);
        for (let b = 0; b < 4; b++) {
          const x0 = b * 128;
          const grad = g.createLinearGradient(x0, y0 + 20, x0 + 128, y0 + 118);
          grad.addColorStop(0, "#7d9bb8");
          grad.addColorStop(0.55, "#3e5770");
          grad.addColorStop(1, "#2a3b4f");
          g.fillStyle = grad;
          g.fillRect(x0 + 6, y0 + 22, 116, 96);
          if (rnd() < 0.3) {                           // a lit office
            g.fillStyle = "rgba(255,226,160,.55)";
            g.fillRect(x0 + 6, y0 + 22, 116, 96);
          }
          g.fillStyle = "rgba(255,255,255,.16)";       // sky reflection
          g.beginPath();
          g.moveTo(x0 + 20, y0 + 118); g.lineTo(x0 + 70, y0 + 22); g.lineTo(x0 + 92, y0 + 22); g.lineTo(x0 + 42, y0 + 118);
          g.fill();
          g.fillStyle = "#c9ced4";                     // mullions
          g.fillRect(x0 + 62, y0 + 22, 4, 96);
          g.fillRect(x0 + 6, y0 + 66, 116, 3);
        }
      }
      const tex = new T.CanvasTexture(c);
      tex.wrapS = tex.wrapT = T.RepeatWrapping;
      if ("colorSpace" in tex) tex.colorSpace = T.SRGBColorSpace;
      tex.anisotropy = 4;
      return tex;
    }

    /** A glazed block with slabs, plinth, parapet. Returns its facade + roof materials. */
    function block(group, id, w, h, d, x, z, floors, seed) {
      const make = bays => {
        const t = facadeTexture(seed);
        t.repeat.set(Math.max(1, bays) / 4, floors / 2);
        return new T.MeshStandardMaterial({ map: t, color: 0xffffff, roughness: 0.32, metalness: 0.25, emissive: 0x000000 });
      };
      const mx = make(Math.round(d / 4.5)), mz = make(Math.round(w / 4.5));
      const roof = new T.MeshStandardMaterial({ color: 0xbfc3c8, roughness: 0.9, emissive: 0x000000 });
      const body = mesh(new T.BoxGeometry(w, h, d), [mx, mx, roof, roof, mz, mz], id, { x, y: h / 2 + 0.8, z, parent: group });
      body.userData.body = true;
      mesh(new T.BoxGeometry(w + 1.2, 0.8, d + 1.2), M.plinth, id, { x, y: 0.4, z, parent: group });
      for (let f = 1; f <= floors; f++) {
        mesh(new T.BoxGeometry(w + 0.7, 0.45, d + 0.7), M.concrete, id, { x, y: 0.8 + f * FLOOR_H - 0.2, z, parent: group });
      }
      mesh(new T.BoxGeometry(w + 0.9, 1.0, d + 0.9), M.concrete, id, { x, y: h + 1.3, z, parent: group });
      mesh(new T.BoxGeometry(w - 0.6, 0.2, d - 0.6), roof, id, { x, y: h + 1.75, z, parent: group, cast: false });
      return { facade: [mx, mz], roof, top: h + 1.85 };
    }

    function roofSolar(group, id, x, z, w, d, y) {
      const panels = [];
      for (let px = x - w / 2 + 1.5; px <= x + w / 2 - 1.5; px += 2.2) {
        for (let pz = z - d / 2 + 2; pz <= z + d / 2 - 2; pz += 4.2) panels.push({ x: px, y: y + 0.7, z: pz, rx: -0.4 });
      }
      if (!panels.length) return;
      instanced(new T.BoxGeometry(2.0, 0.12, 3.2), M.pv, panels, id, group);
      instanced(new T.BoxGeometry(0.12, 0.7, 0.12), M.metal, panels.map(p => ({ x: p.x, y: y + 0.3, z: p.z + 1.1 })), id, group);
    }

    function hvacUnit(group, id, x, y, z) {
      mesh(new T.BoxGeometry(3.2, 1.8, 3.2), M.hvac, id, { x, y: y + 0.9, z, parent: group });
      mesh(new T.CylinderGeometry(1.1, 1.1, 0.12, 18), M.fan, id, { x, y: y + 1.86, z, parent: group, cast: false });
    }

    function footprint(b, layout) {
      const area = num(b.floor_area_m2) || 4000;
      const fp = area / layout.floors / 1.6;
      const w = Math.sqrt(fp * layout.aspect);
      return { w, d: fp / w };
    }

    function buildBuilding(b, index) {
      const id = b.building_id;
      const layout = LAYOUT[id] || { x: -60 + index * 45, z: 70, floors: 3, aspect: 1.5, style: "generic" };
      const { w, d } = footprint(b, layout);
      const floors = layout.floors;
      const h = floors * FLOOR_H;
      const group = new T.Group();
      group.position.set(layout.x, 0, layout.z);
      const facade = [], roofs = [];
      const main = block(group, id, w, h, d, 0, 0, floors, index + 1);
      facade.push(...main.facade); roofs.push(main.roof);
      let solarArea = { x: 0, z: 0, w: w - 4, d: d - 4 };

      if (layout.style === "admin") {
        // glass entrance atrium + flags
        const atr = mesh(new T.CylinderGeometry(6, 6, h + 3, 32, 1, true), M.glass, id, { x: 0, y: (h + 3) / 2 + 0.8, z: d / 2 + 2, parent: group });
        atr.castShadow = false;
        mesh(new T.CylinderGeometry(6.6, 6.6, 0.6, 32), M.concrete, id, { x: 0, y: h + 4.1, z: d / 2 + 2, parent: group });
        for (let k = 0; k < 8; k++) {
          const a = (k / 8) * Math.PI * 2;
          mesh(new T.BoxGeometry(0.25, h + 3, 0.25), M.trim, id, { x: Math.cos(a) * 6, y: (h + 3) / 2 + 0.8, z: d / 2 + 2 + Math.sin(a) * 6, parent: group });
        }
        [-1, 0, 1].forEach((k, i) => {
          mesh(new T.CylinderGeometry(0.12, 0.12, 12, 6), M.metal, id, { x: 12 + k * 3, y: 6, z: d / 2 + 12, parent: group });
          const flag = mesh(new T.PlaneGeometry(2.6, 1.6), [M.flag1, M.concrete, M.flag2][i], id, { x: 13.3 + k * 3, y: 11, z: d / 2 + 12, parent: group, cast: false });
          flag.userData.flag = true;
        });
        hvacUnit(group, id, w / 2 - 3, main.top, -d / 2 + 3);
        hvacUnit(group, id, w / 2 - 7.5, main.top, -d / 2 + 3);
        solarArea = { x: -2.5, z: 1, w: w - 10, d: d - 6 };
      } else if (layout.style === "labs") {
        // mechanical penthouse, fume stacks, chillers
        const pw = w * 0.32, pd = d * 0.4;
        const pent = mesh(new T.BoxGeometry(pw, 4, pd), M.concrete, id, { x: w / 2 - pw / 2 - 2, y: main.top + 2, z: -d / 2 + pd / 2 + 2, parent: group });
        pent.userData.body = true;
        [0, 1, 2].forEach(k => mesh(new T.CylinderGeometry(0.7, 0.8, 7, 12), M.metal, id, { x: w / 2 - 4 - k * 3.2, y: main.top + 7.5, z: -d / 2 + 4, parent: group }));
        for (let k = 0; k < 4; k++) hvacUnit(group, id, -w / 2 + 4 + k * 4.4, main.top, -d / 2 + 4);
        solarArea = { x: -3, z: 5, w: w - 12, d: d - 16 };
        // entrance canopy
        mesh(new T.BoxGeometry(12, 0.5, 5), M.trim, id, { x: 0, y: 4.6, z: d / 2 + 2.6, parent: group });
      } else if (layout.style === "classrooms") {
        // L-shaped: lower wing at the west end
        const ww = 16, wd = 22, wf = floors - 1, wh = wf * FLOOR_H;
        const wing = block(group, id, ww, wh, wd, -w / 2 + ww / 2, d / 2 + wd / 2 - 0.5, wf, index + 7);
        facade.push(...wing.facade); roofs.push(wing.roof);
        roofSolar(group, id, -w / 2 + ww / 2, d / 2 + wd / 2, ww - 4, wd - 4, wing.top);
        hvacUnit(group, id, w / 2 - 4, main.top, 0);
        hvacUnit(group, id, w / 2 - 8.5, main.top, 0);
        solarArea = { x: -4, z: 0, w: w - 14, d: d - 4 };
        // covered walkway
        mesh(new T.BoxGeometry(w * 0.6, 0.4, 3.5), M.trim, id, { x: 4, y: 4.6, z: -d / 2 - 1.9, parent: group });
      }
      if (b.has_solar) roofSolar(group, id, solarArea.x, solarArea.z, solarArea.w, solarArea.d, main.top);

      scene.add(group);
      group.updateMatrixWorld(true);
      const bodies = [];
      group.traverse(o => { if (o.userData.body) bodies.push(o); });
      const box = new T.Box3();
      bodies.forEach(o => box.expandByObject(o));
      const size = box.getSize(new T.Vector3()), center = box.getCenter(new T.Vector3());
      const edges = new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry(size.x + 1.4, size.y + 1.4, size.z + 1.4)), new T.LineBasicMaterial({ color: COLORS.selected, transparent: true, opacity: 0 }));
      edges.position.copy(center);
      scene.add(edges);

      const marker = makeMarker();
      marker.userData.baseY = box.max.y + 10;
      marker.position.set(center.x, marker.userData.baseY, center.z);
      scene.add(marker);

      const label = makeLabel(id);
      label.anchor = new T.Vector3(center.x, box.max.y + 4, center.z);
      B[id] = { group, mats: facade, roofMats: roofs, edges, marker, label, center, status: "normal" };
    }

    function makeMarker() {
      const g = new T.Group();
      const mat = new T.MeshBasicMaterial({ color: COLORS.problem });
      const cone = new T.Mesh(new T.ConeGeometry(2.4, 5, 4), mat);
      cone.rotation.x = Math.PI;
      const dot = new T.Mesh(new T.SphereGeometry(1.5, 12, 10), mat);
      dot.position.y = 4.6;
      g.add(cone, dot);
      g.visible = false;
      return g;
    }

    function makeLabel(id, extra = "") {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `twin3d-label ${extra}`;
      el.dataset.id = id;
      el.dataset.extra = extra;
      ui.labels.appendChild(el);
      return { el, anchor: null };
    }

    // ---------------- status → colours, assets → action ----------------

    /** What the agent is doing with which assets, for the hour on screen. */
    function actionState() {
      const a = model.agent;
      const ev = a?.event;
      if (!a || !ev || !model.map || ev.timestamp !== model.map.focus_timestamp) return { assets: [], phase: null };
      const act = a.recommendation?.action;
      const list = ACTION_ASSETS[act] || [];
      let phase = null;
      if (model.executing) phase = "executing";
      else if (a.state === "WAITING_FOR_APPROVAL") phase = "proposed";
      else if (a.state === "COMPLETED" && a.verification && a.last_decision?.decision !== "REJECTED") phase = "applied";
      return { assets: phase ? list : [], phase, action: act, rec: a.recommendation };
    }

    function batterySoc() {
      const list = Array.isArray(model.agent?.candidate_actions) ? model.agent.candidate_actions : [];
      for (const c of list) if (num(c.battery_soc_percent) !== null) return num(c.battery_soc_percent);
      return null;
    }

    function applyStatus() {
      const m = model.map;
      if (!m) return;
      if (!ok) { renderLabelsOnly(); return; }
      m.buildings.forEach((b, i) => { if (!B[b.building_id]) buildBuilding(b, i); });

      m.buildings.forEach(b => {
        const o = B[b.building_id];
        const st = paintedStatus(b.building_id);
        o.status = st;
        const tint = new T.Color(COLORS.tint[st] || COLORS.tint.normal);
        o.mats.forEach(mt => mt.color.copy(tint));
        o.roofMats.forEach(mt => mt.color.set(st === "normal" ? 0xbfc3c8 : st === "problem" ? 0xd98a8a : 0x9fd3b2));
        o.marker.visible = b.status === "problem";
        setLabel(o.label, b.building_id, `${b.building_id} · ${b.name}`, st, b.live_load_kw);
      });
      const cst = m.campus.status;
      perimeter.material.color.set(cst === "problem" ? COLORS.problem : cst === "resolved" ? COLORS.resolved : (model.selected === "CAMPUS" ? COLORS.selected : 0x8a8f98));
      groundGlow.material.color.set(cst === "resolved" ? COLORS.resolved : COLORS.problem);
      campusMarker.visible = cst === "problem";
      setLabel(campusLabel, "CAMPUS", "Campus", cst, m.buildings.reduce((s, b) => s + (num(b.live_load_kw) || 0), 0));
      applyAssets();
    }

    function applyAssets() {
      if (!ok || !model.map) return;
      const st = actionState();
      const on = k => st.assets.includes(k);
      const applied = st.phase === "applied" || st.phase === "executing";

      const solarKw = model.map.buildings.reduce((s, b) => s + (num(b.live_solar_kw) || 0), 0);
      assetLabel(assets.solar, "Solar farm", `${fmt(solarKw)} kW`, false);

      const soc = batterySoc();
      assets.battery.soc = soc;
      const battText = on("battery") ? (applied ? "Discharging" : "Proposed: discharge") : soc !== null ? `SOC ${fmt(soc, 0)}%` : "Standby";
      assetLabel(assets.battery, "Battery storage", battText, on("battery"));
      const frac = Math.max(0.05, Math.min(1, (soc ?? 70) / 100 - (on("battery") && applied ? 0.12 : 0)));
      assets.battery.socBars.forEach(bar => { bar.scale.x = frac; bar.position.x = -2.6 * (1 - frac); });
      M.socFill.color.set(frac < 0.3 ? 0xe0464e : frac < 0.55 ? 0xf0c53c : 0x3ee07f);

      const evText = on("ev") ? (applied ? "Charging shifted" : "Proposed: shift charging") : `${assets.ev.bays} chargers`;
      assetLabel(assets.ev, "EV charging hub", evText, on("ev"));
      M.evScreen.color.set(on("ev") && applied ? 0xf0a03c : 0x35d07f);

      // energy flows follow the action
      flows.battery.on = on("battery") && applied;
      flows.gridEV.on = !(on("ev") && applied);
      ["gridB001", "gridB002", "gridB003"].forEach(k => { flows[k].speed = flows[k].base * (on("hvac") && applied ? 0.6 : 1); });
    }

    function assetLabel(asset, name, value, acting) {
      const el = asset.label.el;
      el.className = `twin3d-label ${asset.label.el.dataset.extra} ${acting ? "is-acting" : ""}`;
      el.innerHTML = `<i class="twin3d-sq"></i><b>${esc(name)}</b><span>${esc(value)}</span>`;
    }

    function setLabel(lbl, id, name, status, load) {
      lbl.el.className = `twin3d-label is-${status} ${model.selected === id ? "is-active" : ""}`;
      lbl.el.innerHTML = `<i class="twin3d-dot is-${esc(status)}"></i><b>${esc(name)}</b><span>${esc(fmt(load))} kW</span>`;
    }

    function renderLabelsOnly() {
      ui.labels.classList.add("is-static");
      ui.labels.innerHTML = "";
      const m = model.map;
      [m.campus, ...m.buildings].forEach(b => {
        const l = makeLabel(b.building_id);
        setLabel(l, b.building_id, b.building_id === "CAMPUS" ? "Campus" : `${b.building_id} · ${b.name}`, b.building_id === "CAMPUS" ? b.status : paintedStatus(b.building_id), b.live_load_kw);
      });
    }

    function focus(id) {
      if (!ok) return;
      if (id === "CAMPUS" || !B[id]) {
        orbit.goal.set(0, 4, 0);
        orbit.goalDist = HOME.dist;
      } else {
        orbit.goal.copy(B[id].center);
        orbit.goalDist = 125;
      }
      orbit.auto = false;
    }

    function resetView() {
      if (!ok) return;
      orbit.goal.set(0, 4, 0);
      orbit.goalDist = HOME.dist;
      orbit.theta = HOME.theta; orbit.phi = HOME.phi;
      orbit.auto = true;
    }

    function pulseAt(id) {
      const center = id === "CAMPUS" || !B[id] ? new T.Vector3(0, 0, 0) : B[id].center;
      const ring = new T.Mesh(new T.RingGeometry(1, 2.2, 48), new T.MeshBasicMaterial({ color: 0x40c4ff, transparent: true, opacity: 0.9, side: T.DoubleSide, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(center.x, 0.5, center.z);
      scene.add(ring);
      pulses.push({ mesh: ring, t: 0, max: id === "CAMPUS" ? 140 : 50 });
    }

    // ---------------- input --------------------------------------------

    function bindInput() {
      const el = ui.canvas;
      el.addEventListener("pointerdown", e => {
        dragging = true; dragMoved = false;
        last = { x: e.clientX, y: e.clientY };
        el.setPointerCapture(e.pointerId);
      });
      el.addEventListener("pointermove", e => {
        if (dragging) {
          const dx = e.clientX - last.x, dy = e.clientY - last.y;
          if (Math.abs(dx) + Math.abs(dy) > 3) dragMoved = true;
          orbit.theta -= dx * 0.006;
          orbit.phi = Math.min(1.42, Math.max(0.25, orbit.phi - dy * 0.005));
          orbit.auto = false;
          last = { x: e.clientX, y: e.clientY };
        } else {
          hoverId = pick(e);
          el.style.cursor = hoverId ? "pointer" : "grab";
        }
      });
      el.addEventListener("pointerleave", () => { hoverId = null; });
      el.addEventListener("pointerup", e => {
        dragging = false;
        if (!dragMoved) {
          const id = pick(e);
          if (id) select(id);
        }
      });
      el.addEventListener("wheel", e => {
        e.preventDefault();
        orbit.goalDist = Math.min(520, Math.max(50, orbit.goalDist * (1 + Math.sign(e.deltaY) * 0.1)));
        orbit.auto = false;
      }, { passive: false });
    }

    function pick(e) {
      const r = ui.canvas.getBoundingClientRect();
      pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      pointer.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(scene.children, true);
      for (const h of hits) {
        let o = h.object;
        while (o && !o.userData.id) o = o.parent;
        if (!o) continue;
        const id = o.userData.id;
        if (id === "CAMPUS") return Math.abs(h.point.x) <= HALF_W && Math.abs(h.point.z) <= HALF_D ? "CAMPUS" : null;
        return id;
      }
      return null;
    }

    function resize() {
      const w = ui.stage.clientWidth, h = ui.stage.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // pull back on narrow screens so the whole campus fits
      HOME.dist = w < 560 ? 420 : 300;
      if (orbit.auto) orbit.goalDist = HOME.dist;
      camera.updateProjectionMatrix();
    }

    // ---------------- loop ---------------------------------------------

    let lastPulse = 0;
    function loop() {
      requestAnimationFrame(loop);
      if (!visible || document.hidden || ui.body.hidden) return;
      const dt = Math.min(clock.getDelta(), 0.05);
      const t = clock.elapsedTime;

      if (orbit.auto) orbit.theta += dt * 0.05;
      orbit.target.lerp(orbit.goal, 0.08);
      orbit.dist += (orbit.goalDist - orbit.dist) * 0.08;
      camera.position.set(
        orbit.target.x + orbit.dist * Math.sin(orbit.phi) * Math.sin(orbit.theta),
        orbit.target.y + orbit.dist * Math.cos(orbit.phi),
        orbit.target.z + orbit.dist * Math.sin(orbit.phi) * Math.cos(orbit.theta)
      );
      camera.lookAt(orbit.target);

      const beat = 0.5 + 0.5 * Math.sin(t * 4);
      Object.entries(B).forEach(([id, o]) => {
        const em = o.status === "problem" ? 0.12 + 0.28 * beat : o.status === "resolved" ? 0.1 : 0;
        const emCol = o.status === "resolved" ? COLORS.resolved : COLORS.problem;
        o.mats.forEach(mt => { mt.emissive.setHex(emCol); mt.emissiveIntensity = em; });
        if (o.marker.visible) {
          o.marker.position.y = o.marker.userData.baseY + Math.sin(t * 3) * 1.2;
          o.marker.rotation.y += dt * 1.5;
        }
        o.edges.material.opacity = model.selected === id ? 0.55 + 0.45 * beat : hoverId === id ? 0.5 : 0;
      });
      if (campusMarker.visible) {
        campusMarker.position.y = campusMarker.userData.baseY + Math.sin(t * 3) * 1.2;
        campusMarker.rotation.y += dt * 1.5;
      }
      const cst = model.map?.campus?.status;
      groundGlow.material.opacity = cst === "problem" ? 0.06 + 0.1 * beat : cst === "resolved" ? 0.06 : 0;

      // assets the agent's solution uses
      const st = actionState();
      const strong = st.phase === "executing" ? 1 : st.phase === "applied" ? 0.55 : 0.35;
      const glow = k => st.assets.includes(k) ? strong * (0.45 + 0.55 * beat) : 0;
      M.hvac.emissiveIntensity = glow("hvac") * 1.2;
      M.batt.emissiveIntensity = glow("battery") * 0.6;
      M.battStripe.emissiveIntensity = 0.35 + glow("battery") * 1.5;
      M.evRing.color.setHSL(st.assets.includes("ev") ? 0.09 : 0.55, 0.9, 0.5 + 0.15 * Math.sin(t * 3));
      M.pv.emissiveIntensity = 1 + 0.6 * (0.5 + 0.5 * Math.sin(t * 1.3));

      Object.values(flows).forEach(f => {
        const target = f.on ? 1 : 0;
        f.dotMat.opacity += (target - f.dotMat.opacity) * 0.08;
        f.line.material.opacity = 0.1 + 0.3 * f.dotMat.opacity;
        const fast = f === flows.battery && st.phase === "executing" ? 2 : 1;
        f.dots.forEach(d => {
          d.visible = f.dotMat.opacity > 0.02;
          d.userData.u = (d.userData.u + dt * f.speed * fast) % 1;
          d.position.copy(f.curve.getPointAt(d.userData.u));
        });
      });

      // flags flutter
      Object.values(B).forEach(o => o.group.children.forEach(c => { if (c.userData.flag) c.rotation.y = Math.sin(t * 2 + c.position.x) * 0.25; }));

      if (model.executing && t - lastPulse > 0.45) {
        lastPulse = t;
        pulseAt(model.selected);
      }
      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i];
        p.t += dt;
        const s = 1 + p.t * p.max;
        p.mesh.scale.set(s, s, s);
        p.mesh.material.opacity = Math.max(0, 0.9 - p.t * 0.9);
        if (p.t > 1) { scene.remove(p.mesh); p.mesh.geometry.dispose(); p.mesh.material.dispose(); pulses.splice(i, 1); }
      }

      renderer.render(scene, camera);
      placeLabels();
    }

    function placeLabels() {
      const w = ui.stage.clientWidth, h = ui.stage.clientHeight;
      const all = [...Object.values(B).map(o => o.label), campusLabel, ...Object.values(assets).map(a => a.label)].filter(l => l && l.anchor);
      all.forEach(l => {
        const p = l.anchor.clone().project(camera);
        const hidden = p.z > 1 || p.x < -1.1 || p.x > 1.1 || p.y < -1.1 || p.y > 1.1;
        l.el.style.display = hidden ? "none" : "";
        if (!hidden) l.el.style.transform = `translate(-50%, -100%) translate(${((p.x + 1) / 2) * w}px, ${((1 - p.y) / 2) * h}px)`;
      });
    }

    return {
      start() { ok = init(); if (!ok) ui.fallback.hidden = false; return ok; },
      applyStatus, applyAssets, focus, resetView,
      ACTION_ASSETS,
      get ok() { return ok; }
    };
  })();

  // ======================================================================
  // WIRING
  // ======================================================================

  ui.chips.addEventListener("click", e => {
    const b = e.target.closest("[data-id]");
    if (b) select(b.dataset.id);
  });
  ui.labels.addEventListener("click", e => {
    const b = e.target.closest("[data-id]");
    if (b) select(b.dataset.id);
  });
  ui.side.addEventListener("click", e => {
    const link = e.target.closest(".twin3d-link[data-id]");
    if (link) return select(link.dataset.id);
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "analyze") analyze();
    else if (act === "approve") decide("approve");
    else if (act === "reject") decide("reject");
  });
  ui.hour.addEventListener("change", async () => {
    try { await loadMap(ui.hour.value); } catch (err) { toast(`3D map: ${err.message}`); }
  });
  ui.reset.addEventListener("click", () => {
    model.selected = null;
    renderChips();
    scene3d.applyStatus();
    scene3d.resetView();
    renderSide();
  });

  const PREF = "smart_energy_twin3d_open";
  function setOpen(open) {
    ui.body.hidden = !open;
    ui.toggle.textContent = open ? "Hide 3D map" : "Show 3D map";
    ui.toggle.setAttribute("aria-expanded", String(open));
    try { localStorage.setItem(PREF, open ? "1" : "0"); } catch (_) { /* storage blocked */ }
  }
  ui.toggle.addEventListener("click", () => setOpen(ui.body.hidden));
  let startOpen = true;
  try { startOpen = localStorage.getItem(PREF) !== "0"; } catch (_) { /* storage blocked */ }
  setOpen(startOpen);

  // Analyses started from elsewhere on the page keep the map current.
  document.addEventListener("twin3d:refresh", () => loadMap(model.map?.focus_timestamp).catch(() => {}));

  (async () => {
    scene3d.start();
    try {
      await loadAgent();
      await loadMap();
      // Open on the problem the agent is already working on, if any.
      const ev = model.agent?.event;
      if (ev && ev.timestamp === model.map.focus_timestamp) select(ev.building_id || "CAMPUS");
    } catch (err) {
      ui.side.innerHTML = `<div class="empty-state">${esc(err.message)}</div>`;
    }
  })();
})();
