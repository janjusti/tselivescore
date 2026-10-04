const STORAGE_KEY = "tselivescore-dashboard";
const SESSION_KEY = "tselivescore-session-id";

const dashboardEl = document.getElementById("dashboard");
const statusEl = document.getElementById("status-banner");
const liveIndicator = document.getElementById("live-indicator");
const toolbarMetrics = document.getElementById("toolbar-metrics");
const waitInput = document.getElementById("wait-input");
const addDialog = document.getElementById("add-dialog");
const addForm = document.getElementById("add-form");
const categorySelect = document.getElementById("category-select");
const ufField = document.getElementById("uf-field");
const ufSelect = document.getElementById("uf-select");
const printablesInput = document.getElementById("printables-input");
const panelTemplate = document.getElementById("panel-template");

let meta = {
  default_wait: 5,
  min_wait: 5,
  session_ttl_seconds: 30,
  ufs: [],
  categories: [],
};
let panels = [];
let heartbeatTimer = null;
let freshnessTimer = null;
let columnFitObserver = null;
let sessionId = null;
const prevDeltas = new Map();
const prevPanelTseUpdate = new Map();
let audioCtx = null;
let audioUnlocked = false;

const UPDATE_FRESHNESS_WINDOW_S = 30;
const UPDATE_LIVE_THRESHOLD_S = 15;

function apiUrl(path) {
  return new URL(path, window.location.href).href;
}

function unlockAudio() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    try {
      audioCtx = new Ctx();
    } catch (_) {
      return;
    }
  }
  audioUnlocked = true;
  if (audioCtx.state === "suspended") {
    audioCtx.resume().catch(() => {});
  }
}

function setupAudioUnlock() {
  const unlock = () => unlockAudio();
  document.addEventListener("click", unlock);
  document.addEventListener("keydown", unlock);
  document.addEventListener("touchstart", unlock, { passive: true });
}

function playBeep(freq, duration, type, repeat, interval) {
  if (!audioUnlocked || !audioCtx) return;
  type = type || "square";
  repeat = repeat || 1;
  interval = interval || 0.15;
  for (let i = 0; i < repeat; i++) {
    const delay = i * interval;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.value = 0;
    gain.gain.setValueAtTime(0.15, audioCtx.currentTime + delay);
    gain.gain.exponentialRampToValueAtTime(
      0.001,
      audioCtx.currentTime + delay + duration,
    );
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(audioCtx.currentTime + delay);
    osc.stop(audioCtx.currentTime + delay + duration + 0.05);
  }
}

function playUpdateBeep() {
  playBeep(880, 0.08, "square", 1);
}

function syncPanelUpdateTracking() {
  const active = new Set(panels.map((panel) => panel.key));
  for (const key of prevPanelTseUpdate.keys()) {
    if (!active.has(key)) prevPanelTseUpdate.delete(key);
  }
}

function detectPanelUpdates(panelsData) {
  if (!panelsData) return;
  syncPanelUpdateTracking();
  let anyUpdated = false;
  for (const panel of panels) {
    const data = panelsData[panel.key];
    if (!data || data.error) continue;
    const ts = data.latest_update_tse;
    if (!ts) continue;
    const prev = prevPanelTseUpdate.get(panel.key);
    if (prev && prev !== ts) anyUpdated = true;
    prevPanelTseUpdate.set(panel.key, ts);
  }
  if (anyUpdated) playUpdateBeep();
}

function uid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function setStatus(message, isError = false) {
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
  statusEl.hidden = !message;
}

function getSessionId() {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = uid();
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function migratePanel(panel) {
  if (panel.key) return panel;
  if (panel.cod === "br") return { ...panel, key: "br:1" };
  if (panel.cod) return { ...panel, key: `${panel.cod}:3` };
  return { ...panel, key: "br:1" };
}

function loadState() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    panels = [{ id: uid(), key: "br:1", printables: 5 }];
    return;
  }
  try {
    const data = JSON.parse(raw);
    panels = (data.panels?.length ? data.panels : [{ id: uid(), key: "br:1", printables: 5 }]).map(
      migratePanel
    );
    waitInput.value = Math.max(data.wait ?? meta.default_wait, meta.min_wait);
  } catch {
    panels = [{ id: uid(), key: "br:1", printables: 5 }];
  }
}

function clampWait(value) {
  const wait = Number(value) || meta.min_wait;
  return Math.max(wait, meta.min_wait);
}

function saveState() {
  waitInput.value = clampWait(waitInput.value);
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ panels, wait: Number(waitInput.value) })
  );
}

function scopeFromKey(key) {
  return key.split(":")[0].toLowerCase();
}

function scopeLabel(uf) {
  if (uf === "br") return "Brasil";
  return uf.toUpperCase();
}

function panelLabel(key) {
  for (const category of meta.categories) {
    if (!category.requires_uf) {
      const opt = category.options?.find((o) => o.key === key);
      if (opt) return opt.label;
    }
    const [uf, cargo] = key.split(":");
    if (category.cargo === cargo) {
      if (category.uf_labels?.[uf]) {
        return `${category.uf_labels[uf]} ${uf.toUpperCase()}`;
      }
      return `${category.singular} ${uf.toUpperCase()}`;
    }
  }
  return key;
}

function fillCategorySelect() {
  categorySelect.innerHTML = "";
  for (const category of meta.categories) {
    const el = document.createElement("option");
    el.value = category.id;
    el.textContent = category.label;
    categorySelect.appendChild(el);
  }
  fillUfSelect();
  updateUfVisibility();
}

function fillUfSelect() {
  ufSelect.innerHTML = "";
  for (const uf of meta.ufs) {
    const el = document.createElement("option");
    el.value = uf;
    el.textContent = uf.toUpperCase();
    ufSelect.appendChild(el);
  }
}

function getSelectedCategory() {
  return meta.categories.find((c) => c.id === categorySelect.value);
}

function updateUfVisibility() {
  const category = getSelectedCategory();
  ufField.classList.toggle("hidden", !category?.requires_uf);
}

function buildPanelKey() {
  const category = getSelectedCategory();
  if (!category) return null;
  if (!category.requires_uf) {
    return category.options[0].key;
  }
  const uf = ufSelect.value;
  if (category.uf_labels?.[uf]) {
    return `${uf}:7`;
  }
  return `${uf}:${category.cargo}`;
}

function namesOverflow(panelEl) {
  const names = panelEl.querySelectorAll(".cand-name > span:first-child");
  for (const el of names) {
    if (el.scrollWidth > el.clientWidth + 1) return true;
  }
  return false;
}

function fitCandidateColumns(panelEl) {
  const table = panelEl?.querySelector(".candidates");
  if (!table || !table.querySelector("tbody tr")) return;

  table.classList.remove("compact-delta", "compact-dist", "compact-margem");

  const steps = [];
  if (!table.classList.contains("no-delta")) steps.push("compact-delta");
  if (!table.classList.contains("no-dist")) steps.push("compact-dist");
  if (!table.classList.contains("no-margem")) steps.push("compact-margem");

  for (const cls of steps) {
    if (!namesOverflow(panelEl)) break;
    table.classList.add(cls);
  }
}

function fitAllCandidateColumns() {
  for (const panel of panels) {
    const panelEl = dashboardEl.querySelector(`[data-id="${panel.id}"]`);
    if (panelEl) fitCandidateColumns(panelEl);
  }
}

function scheduleFitCandidateColumns(panelEl) {
  requestAnimationFrame(() => {
    if (panelEl) fitCandidateColumns(panelEl);
    else fitAllCandidateColumns();
  });
}

function observeColumnFitting() {
  if (columnFitObserver) columnFitObserver.disconnect();
  if (!dashboardEl) return;
  columnFitObserver = new ResizeObserver(() => scheduleFitCandidateColumns());
  columnFitObserver.observe(dashboardEl);
}

function renderPanels() {
  dashboardEl.innerHTML = "";
  if (!panels.length) {
    dashboardEl.innerHTML =
      '<div class="empty-state">Nenhum painel. Clique em "+ Painel" para começar.</div>';
    observeColumnFitting();
    return;
  }

  for (const panel of panels) {
    const node = panelTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.id = panel.id;
    node.querySelector(".panel-title").textContent = panelLabel(panel.key);
    node.querySelector(".panel-printables").value = panel.printables;
    node.querySelector(".panel-remove").addEventListener("click", () => {
      panels = panels.filter((p) => p.id !== panel.id);
      saveState();
      renderPanels();
      sendHeartbeat();
    });
    node.querySelector(".panel-printables").addEventListener("change", (e) => {
      panel.printables = Number(e.target.value) || 5;
      saveState();
      sendHeartbeat();
    });
    dashboardEl.appendChild(node);
  }
  observeColumnFitting();
}

function formatNumber(value) {
  return new Intl.NumberFormat("pt-BR").format(value ?? 0);
}

function formatCompact(value) {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";

  if (abs >= 1_000_000) {
    const scaled = abs / 1_000_000;
    const text = scaled.toLocaleString("pt-BR", {
      minimumFractionDigits: 1,
      maximumFractionDigits: scaled >= 10 ? 1 : 2,
    });
    return `${sign}${text}M`;
  }

  if (abs >= 10_000) {
    const scaled = Math.round(abs / 1_000);
    return `${sign}${scaled.toLocaleString("pt-BR")}K`;
  }

  if (abs >= 1_000) {
    const scaled = abs / 1_000;
    const text = scaled.toLocaleString("pt-BR", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 1,
    });
    return `${sign}${text}K`;
  }

  return `${sign}${abs.toLocaleString("pt-BR")}`;
}

function formatSignedCompact(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "";
  const body = formatCompact(Math.abs(n));
  if (n > 0) return `+${body}`;
  if (n < 0) return `-${body}`;
  return body;
}

function formatPerc(value) {
  return `${Number(value).toFixed(2)}%`;
}

function formatTseTimestamp(isoString) {
  const date = new Date(isoString);
  const ageMs = Date.now() - date.getTime();
  if (ageMs >= 86400000) {
    return date.toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }
  return date.toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function isCandEleitoProporcional(cand) {
  return cand.sf_e === "s" || cand.garantido;
}

function legendaSubtitleClass(cand) {
  const classes = ["cand-subtitle"];
  if (cand.eliminado_mat) {
    classes.push("cand-subtitle-muted");
  } else if (isCandEleitoProporcional(cand)) {
    classes.push("cand-subtitle-in", "cand-subtitle-safe");
  } else if (cand.em_perigo) {
    classes.push("cand-subtitle-edge");
  } else if (cand.dentro_proj) {
    classes.push("cand-subtitle-in");
  } else if (cand.dentro_proj === false) {
    classes.push("cand-subtitle-out");
  }
  return classes.join(" ");
}

function legendaSubtitleTitle(cand) {
  if (isCandEleitoProporcional(cand)) {
    return cand.garantido ? "Eleito matematicamente" : "Eleito";
  }
  if (cand.em_perigo) {
    return "Na beira do corte: última vaga projetada com folga apertada";
  }
  if (cand.dentro_proj) {
    return "Dentro da projeção de vagas da legenda";
  }
  if (cand.dentro_proj === false && !cand.eliminado_mat) {
    return "Fora da projeção de vagas da legenda";
  }
  if (cand.eliminado_mat) {
    return "Eliminado matematicamente na legenda";
  }
  return "";
}

function formatCandSubtitle(cand) {
  const posicao = cand.posicao_legenda ?? cand.posicao_partido;
  if (!cand.partido_sg || posicao == null) return "";
  const pos = `${posicao}º`;
  const cadeiras = cand.cadeiras_proj > 0 ? `/${cand.cadeiras_proj}` : "";
  const title = legendaSubtitleTitle(cand);
  const titleAttr = title ? ` title="${title}"` : "";
  return `<div class="${legendaSubtitleClass(cand)}"${titleAttr}>${cand.partido_sg} · ${pos}${cadeiras}</div>`;
}

// Mesma lógica de escala do em_perigo no backend (proporcional.py).
const RISCO_FOLGA_RATIO = 0.1;
const MARGEM_HEAT_SAFE_RATIO = 0.3;

function margemHeat(cand) {
  if (cand.margem_corte == null || isCandEleitoProporcional(cand)) return null;
  const margem = Math.max(0, Number(cand.margem_corte) || 0);
  const rest = Number(cand.restantes_legenda) || 0;
  if (!rest) return 0;
  const ratio = margem / rest;
  if (ratio >= MARGEM_HEAT_SAFE_RATIO) return 0;
  if (ratio >= RISCO_FOLGA_RATIO) {
    const t = (ratio - RISCO_FOLGA_RATIO) / (MARGEM_HEAT_SAFE_RATIO - RISCO_FOLGA_RATIO);
    return 0.2 * (1 - t);
  }
  return 0.2 + 0.8 * (1 - ratio / RISCO_FOLGA_RATIO);
}

function formatUpdateDelay(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  return `${days}d${remHours}h`;
}

function panelFromUpdatedEl(updatedEl) {
  return updatedEl?.closest(".panel");
}

function clearUpdateFreshness(updatedEl) {
  if (!updatedEl) return;
  updatedEl.classList.remove("updated-live");
  updatedEl.style.removeProperty("--freshness");
  const panelEl = panelFromUpdatedEl(updatedEl);
  if (!panelEl) return;
  panelEl.classList.remove("panel-fresh", "panel-live");
  panelEl.style.removeProperty("--freshness");
}

function applyUpdateFreshness(updatedEl, delaySeconds) {
  if (!updatedEl || delaySeconds == null) return;

  const freshness = Math.max(0, 1 - delaySeconds / UPDATE_FRESHNESS_WINDOW_S);
  const isLive = delaySeconds <= UPDATE_LIVE_THRESHOLD_S;
  const freshnessValue = freshness.toFixed(3);

  updatedEl.style.setProperty("--freshness", freshnessValue);
  updatedEl.classList.toggle("updated-live", isLive);

  const panelEl = panelFromUpdatedEl(updatedEl);
  if (!panelEl) return;
  panelEl.style.setProperty("--freshness", freshnessValue);
  panelEl.classList.toggle("panel-fresh", freshness > 0);
  panelEl.classList.toggle("panel-live", isLive);
}

function renderPanelUpdated(updatedEl, data) {
  if (!updatedEl) return;

  if (!data.latest_update_tse) {
    updatedEl.textContent = "";
    updatedEl.removeAttribute("data-updated-at");
    clearUpdateFreshness(updatedEl);
    return;
  }

  const delaySeconds = Number(data.tse_delay_seconds) || 0;
  const delayLabel = formatUpdateDelay(delaySeconds);
  updatedEl.dataset.updatedAt = data.latest_update_tse;
  updatedEl.innerHTML =
    `Atualizado: <span class="panel-updated-time">${formatTseTimestamp(data.latest_update_tse)}</span> ` +
    `<span class="panel-updated-pill"><span class="panel-updated-delay">há ${delayLabel}</span></span>`;
  applyUpdateFreshness(updatedEl, delaySeconds);
}

function refreshUpdateFreshness() {
  for (const panel of panels) {
    const panelEl = dashboardEl.querySelector(`[data-id="${panel.id}"]`);
    const updatedEl = panelEl?.querySelector(".panel-updated");
    const iso = updatedEl?.dataset.updatedAt;
    if (!updatedEl || !iso) continue;

    const delaySeconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
    const delayEl = updatedEl.querySelector(".panel-updated-delay");
    if (delayEl) {
      delayEl.textContent = `há ${formatUpdateDelay(delaySeconds)}`;
    }
    applyUpdateFreshness(updatedEl, delaySeconds);
  }
}

function scheduleFreshnessRefresh() {
  if (freshnessTimer) clearInterval(freshnessTimer);
  freshnessTimer = setInterval(refreshUpdateFreshness, 1000);
}

function formatLegendasResumo(legendas) {
  if (!legendas?.length) return "";
  return legendas.map((l) => `${l.sigla} ${l.cadeiras}`).join(" · ");
}

function formatBadges(cand, isProporcional = false) {
  const badges = [];
  if (isProporcional && cand.sf_e === "s") {
    badges.push('<span class="badge badge-elected">Eleito</span>');
  } else if (cand.sf_e === "s") {
    badges.push('<span class="badge badge-turno">2º turno</span>');
  } else if (cand.garantido) {
    badges.push('<span class="badge badge-elected-mat">Eleito (mat.)</span>');
  } else if (cand.sf_e !== "n" && cand.sf_e) {
    badges.push('<span class="badge badge-elected">Eleito</span>');
  }
  if (cand.sf_st) {
    badges.push(`<span class="badge badge-st">${cand.sf_st}</span>`);
  }
  return badges.length ? `<div class="cand-badges">${badges.join("")}</div>` : "";
}

function setLiveIndicator(ok) {
  if (!liveIndicator) return;
  liveIndicator.hidden = false;
  liveIndicator.classList.toggle("stale", !ok);
}

function renderPanelStats(statsEl, data, pct, isProporcional) {
  if (!statsEl) return;

  if (!data.apuracao_iniciada) {
    statsEl.textContent = "Apuração ainda não iniciada.";
    return;
  }

  const lines = [];
  const restantes = Number(data.aprox_votos_restantes) || 0;
  if (pct < 100 && restantes > 0) {
    lines.push(`Restantes: ~${formatCompact(restantes)}`);
  }
  if (isProporcional && data.legendas_resumo?.length) {
    lines.push(formatLegendasResumo(data.legendas_resumo));
  }

  statsEl.textContent = "";
  for (const line of lines) {
    const row = document.createElement("div");
    row.className = "panel-stat-line";
    row.textContent = line;
    statsEl.appendChild(row);
  }
}

function collectScopeComparecimento(panelsData) {
  const scopes = new Map();
  for (const panel of panels) {
    const data = panelsData?.[panel.key];
    if (!data || data.error || !data.apuracao_iniciada) continue;
    const uf = scopeFromKey(panel.key);
    if (!scopes.has(uf)) {
      scopes.set(uf, data.perc_comparecimento);
    }
  }
  return scopes;
}

function formatScopeComparecimento(scopes) {
  return [...scopes.entries()]
    .sort(([a], [b]) => {
      if (a === "br") return -1;
      if (b === "br") return 1;
      return a.localeCompare(b);
    })
    .map(([uf, pct]) => `${scopeLabel(uf)} ${Number(pct).toFixed(1)}%`)
    .join(" · ");
}

function buildComparecimentoMetric(panelsData) {
  const scopes = collectScopeComparecimento(panelsData);
  if (!scopes.size) return null;
  return {
    id: "comparecimento",
    label: "Comparecimento",
    value: formatScopeComparecimento(scopes),
  };
}

const toolbarMetricBuilders = [buildComparecimentoMetric];

function renderToolbarMetric(row, metric) {
  row.dataset.metric = metric.id;
  row.replaceChildren();

  const label = document.createElement("span");
  label.className = "toolbar-metric-label";
  label.textContent = `${metric.label}: `;
  row.append(label, metric.value);
}

function renderToolbarMetrics(panelsData) {
  if (!toolbarMetrics) return;

  const metrics = toolbarMetricBuilders
    .map((build) => build(panelsData))
    .filter(Boolean);

  toolbarMetrics.replaceChildren();
  if (!metrics.length) {
    toolbarMetrics.hidden = true;
    return;
  }

  for (const metric of metrics) {
    const row = document.createElement("div");
    row.className = "toolbar-metric";
    renderToolbarMetric(row, metric);
    toolbarMetrics.appendChild(row);
  }
  toolbarMetrics.hidden = false;
}

function renderPanelData(panelEl, data) {
  const alertEl = panelEl.querySelector(".panel-alert");
  const tbody = panelEl.querySelector("tbody");
  const apuracaoLabel = panelEl.querySelector(".apuracao-label");
  const progressFill = panelEl.querySelector(".progress-fill");
  const progressBar = panelEl.querySelector(".progress-bar");
  const statsEl = panelEl.querySelector(".panel-stats");
  const updatedEl = panelEl.querySelector(".panel-updated");

  let errorEl = panelEl.querySelector(".panel-error");
  if (!errorEl) {
    errorEl = document.createElement("div");
    errorEl.className = "panel-error";
    alertEl.insertAdjacentElement("afterend", errorEl);
  }

  if (!data) {
    apuracaoLabel.textContent = "Aguardando…";
    progressFill.style.width = "0%";
    progressBar.setAttribute("aria-valuenow", "0");
    statsEl.textContent = "";
    renderPanelUpdated(updatedEl, {});
    alertEl.textContent = "";
    errorEl.textContent = "";
    tbody.innerHTML = "";
    return;
  }

  if (data.error) {
    apuracaoLabel.textContent = "";
    progressFill.style.width = "0%";
    statsEl.textContent = "";
    renderPanelUpdated(updatedEl, {});
    alertEl.textContent = "";
    errorEl.textContent = data.error;
    tbody.innerHTML = "";
    return;
  }

  errorEl.textContent = "";
  panelEl.querySelector(".panel-title").textContent = data.title || panelLabel(data.key);

  const isMajoritario = Boolean(data.majoritario);
  const isProporcional = Boolean(data.proporcional);
  const pct = Number(data.perc_sec_totalizadas) || 0;
  apuracaoLabel.textContent = `${pct}% apurado`;
  progressFill.style.width = `${pct}%`;
  progressBar.setAttribute("aria-valuenow", String(pct));
  progressBar.setAttribute("aria-valuemin", "0");
  progressBar.setAttribute("aria-valuemax", "100");

  renderPanelStats(statsEl, data, pct, isProporcional);

  renderPanelUpdated(updatedEl, data);

  alertEl.textContent = data.mat_def_label
    ? `Matematicamente definido: ${data.mat_def_label}`
    : "";

  const candidatesTable = panelEl.querySelector(".candidates");
  candidatesTable?.classList.toggle("no-dist", !isMajoritario);
  candidatesTable?.classList.toggle("no-margem", !isProporcional);
  candidatesTable?.classList.toggle("no-delta", isProporcional);
  const restantesFull = formatNumber(data.aprox_votos_restantes);

  tbody.innerHTML = "";
  const qtdVagas = Number(data.qtd_vagas) || 1;
  const panelId = panelEl.dataset.id;
  data.candidatos?.forEach((cand, idx) => {
    const tr = document.createElement("tr");
    if (isProporcional) {
      if (cand.sf_e === "s" || cand.garantido) tr.classList.add("elected");
    } else {
      if (cand.sf_e === "s") tr.classList.add("turno");
      if (cand.garantido || (cand.sf_e !== "n" && cand.sf_e !== "s")) {
        tr.classList.add("elected");
      }
    }
    if (isMajoritario && idx === qtdVagas) tr.classList.add("cutoff");
    const belowCutoff = idx >= qtdVagas;
    const eliminado =
      (isMajoritario && belowCutoff && cand.viavel === false) ||
      (isProporcional && cand.sf_e === "n" && cand.eliminado_mat === true);
    if (eliminado) tr.classList.add("eliminated");
    if (isProporcional && cand.em_perigo) tr.classList.add("at-cutoff");
    if (!isProporcional) {
      const deltaKey = `${panelId}:${cand.nome}`;
      const prevDelta = prevDeltas.get(deltaKey);
      if (cand.delta_perc != null && prevDelta !== undefined && cand.delta_perc !== prevDelta) {
        tr.classList.add(cand.delta_perc > prevDelta ? "flash-pos" : "flash-neg");
      }
      if (cand.delta_perc != null) {
        prevDeltas.set(deltaKey, cand.delta_perc);
      }
    }

    const deltaCell =
      !isProporcional && cand.delta_perc != null
        ? `<span class="${cand.delta_perc > 0 ? "delta-pos" : "delta-neg"}">${cand.delta_perc > 0 ? "+" : ""}${cand.delta_perc.toFixed(2)}%</span>`
        : "";

    const distTitle =
      isMajoritario && cand.distancia_votos != null
        ? `Distância: ${formatNumber(cand.distancia_votos)} · Restantes: ~${restantesFull}${
            eliminado ? " · eliminado" : " · ainda viável"
          }`
        : "";
    const distCell =
      isMajoritario && cand.distancia_votos != null
        ? `<span class="dist-value">${formatCompact(cand.distancia_votos)}</span>`
        : "";

    let margemTitle = "";
    let margemCell = "";
    let margemStyle = "";
    if (isProporcional && cand.margem_corte != null) {
      const restLeg = formatNumber(cand.restantes_legenda);
      const tipo = cand.margem_folga ? "Folga" : "Déficit";
      margemTitle = `${tipo}: ${formatNumber(cand.margem_corte)} · Restantes legenda: ~${restLeg}`;
      const margemSigned = cand.margem_folga
        ? Number(cand.margem_corte) || 0
        : -(Number(cand.margem_corte) || 0);
      const heat = margemHeat(cand);
      const settled = heat === null;
      const valueCls = settled || heat === 0
        ? "margem-value margem-value-settled"
        : "margem-value";
      if (!settled && heat > 0) {
        margemStyle = ` style="--margem-heat: ${heat.toFixed(3)}"`;
      }
      margemCell = `<span class="${valueCls}">${formatSignedCompact(margemSigned)}</span>`;
    }

    tr.innerHTML = `
      <td class="col-name">
        <div class="cand-name">
          <span>${cand.nome}</span>
          ${formatCandSubtitle(cand)}
          ${formatBadges(cand, isProporcional)}
        </div>
      </td>
      <td class="col-num" title="${formatNumber(cand.qtd_votos)}">${formatCompact(cand.qtd_votos)}</td>
      <td class="col-pct">${formatPerc(cand.perc_votos)}</td>
      <td class="col-delta">${deltaCell}</td>
      <td class="col-dist dist-cell" title="${distTitle}">${distCell}</td>
      <td class="col-margem margem-cell"${margemStyle} title="${margemTitle}">${margemCell}</td>
    `;
    tbody.appendChild(tr);
  });
  scheduleFitCandidateColumns(panelEl);
}

function renderDashboardData(data) {
  if (!data) return;
  detectPanelUpdates(data.panels);
  for (const panel of panels) {
    const panelEl = dashboardEl.querySelector(`[data-id="${panel.id}"]`);
    if (!panelEl) continue;
    renderPanelData(panelEl, data.panels?.[panel.key]);
  }
  renderToolbarMetrics(data.panels);
}

async function sendHeartbeat() {
  if (!panels.length) return;

  const body = {
    session_id: sessionId,
    panels,
    wait: clampWait(waitInput.value),
  };

  try {
    const res = await fetch(apiUrl("/api/session"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      setLiveIndicator(false);
      return;
    }
    setLiveIndicator(true);
    renderDashboardData(await res.json());
  } catch (err) {
    console.error(err);
    setLiveIndicator(false);
  }
}

function scheduleHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  const waitMs = clampWait(waitInput.value) * 1000;
  heartbeatTimer = setInterval(sendHeartbeat, waitMs);
}

function endSession() {
  if (!sessionId) return;
  const body = JSON.stringify({ session_id: sessionId });
  if (navigator.sendBeacon) {
    navigator.sendBeacon(
      apiUrl("/api/session/end"),
      new Blob([body], { type: "application/json" })
    );
  } else {
    fetch(apiUrl("/api/session/end"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    });
  }
}

async function init() {
  sessionId = getSessionId();
  try {
    const res = await fetch(apiUrl("/api/meta"));
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} em ${apiUrl("/api/meta")}`);
    }
    meta = await res.json();
    if (!meta.categories?.length) {
      throw new Error("Resposta da API sem categorias.");
    }
  } catch (err) {
    console.error(err);
    setStatus(
      `Falha ao carregar API (${window.location.host}): ${err.message}`,
      true
    );
    return;
  }

  waitInput.min = meta.min_wait;
  waitInput.value = Math.max(meta.default_wait, meta.min_wait);
  fillCategorySelect();
  loadState();
  setupAudioUnlock();
  renderPanels();
  if (meta.mock) {
    setStatus("Modo simulação — dados fictícios com apuração progressiva");
    statusEl?.classList.add("mock");
  }
  await sendHeartbeat();
  scheduleHeartbeat();
  scheduleFreshnessRefresh();
  observeColumnFitting();
}

document.getElementById("add-panel-btn").addEventListener("click", () => {
  addDialog.showModal();
});

document.getElementById("cancel-add-btn").addEventListener("click", () => {
  addDialog.close();
});

categorySelect.addEventListener("change", updateUfVisibility);

addForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const key = buildPanelKey();
  const printables = Number(printablesInput.value) || 5;
  if (!key) return;
  if (panels.some((p) => p.key === key)) {
    alert("Esse painel já está no dashboard.");
    return;
  }
  panels.push({ id: uid(), key, printables });
  saveState();
  renderPanels();
  sendHeartbeat();
  addDialog.close();
});

waitInput.addEventListener("change", () => {
  waitInput.value = clampWait(waitInput.value);
  saveState();
  scheduleHeartbeat();
  sendHeartbeat();
});

window.addEventListener("pagehide", endSession);

init();
