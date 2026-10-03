const STORAGE_KEY = "tselivescore-dashboard";
const SESSION_KEY = "tselivescore-session-id";

const dashboardEl = document.getElementById("dashboard");
const statusEl = document.getElementById("status-banner");
const liveIndicator = document.getElementById("live-indicator");
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
let sessionId = null;
const prevDeltas = new Map();

function apiUrl(path) {
  return new URL(path, window.location.href).href;
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

function renderPanels() {
  dashboardEl.innerHTML = "";
  if (!panels.length) {
    dashboardEl.innerHTML =
      '<div class="empty-state">Nenhum painel. Clique em "+ Painel" para começar.</div>';
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
}

function formatNumber(value) {
  return new Intl.NumberFormat("pt-BR").format(value ?? 0);
}

const compactFormatter = new Intl.NumberFormat("pt-BR", {
  notation: "compact",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

function formatCompact(value) {
  if (value == null) return "";
  return compactFormatter.format(value);
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

function formatCandSubtitle(cand) {
  if (!cand.partido_sg || cand.posicao_partido == null) return "";
  const pos = `${cand.posicao_partido}º`;
  const cadeiras = cand.cadeiras_proj > 0 ? `/${cand.cadeiras_proj}` : "";
  return `<div class="cand-subtitle">${cand.partido_sg} · ${pos}${cadeiras}</div>`;
}

function formatLegendasResumo(legendas) {
  if (!legendas?.length) return "";
  return legendas.map((l) => `${l.sigla} ${l.cadeiras}`).join(" · ");
}

function formatBadges(cand) {
  const badges = [];
  if (cand.sf_e === "s") {
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
    updatedEl.textContent = "";
    alertEl.textContent = "";
    errorEl.textContent = "";
    tbody.innerHTML = "";
    return;
  }

  if (data.error) {
    apuracaoLabel.textContent = "";
    progressFill.style.width = "0%";
    statsEl.textContent = "";
    updatedEl.textContent = "";
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

  if (data.apuracao_iniciada) {
    let stats = `Comparecimento: ${data.perc_comparecimento}%`;
    const restantes = Number(data.aprox_votos_restantes) || 0;
    if (pct < 100 && restantes > 0) {
      stats += ` · Restantes: ~${formatCompact(restantes)}`;
    }
    if (isProporcional && data.legendas_resumo?.length) {
      stats += ` · ${formatLegendasResumo(data.legendas_resumo)}`;
    }
    statsEl.textContent = stats;
  } else {
    statsEl.textContent = "Apuração ainda não iniciada.";
  }

  if (data.latest_update_tse) {
    const delay = data.tse_delay_human || `${data.tse_delay_seconds}s`;
    updatedEl.textContent = `Atualizado: ${formatTseTimestamp(data.latest_update_tse)} (há ${delay})`;
  } else {
    updatedEl.textContent = "";
  }

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
    if (cand.sf_e === "s") tr.classList.add("turno");
    if (cand.garantido || (cand.sf_e !== "n" && cand.sf_e !== "s")) tr.classList.add("elected");
    if (isMajoritario && idx === qtdVagas) tr.classList.add("cutoff");
    const belowCutoff = idx >= qtdVagas;
    const eliminado =
      (isMajoritario && belowCutoff && cand.viavel === false) ||
      (isProporcional && cand.sf_e === "n" && cand.eliminado_mat === true);
    if (eliminado) tr.classList.add("eliminated");

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
    if (isProporcional && cand.margem_corte != null) {
      const restLeg = formatNumber(cand.restantes_legenda);
      const tipo = cand.margem_folga ? "Folga" : "Déficit";
      margemTitle = `${tipo}: ${formatNumber(cand.margem_corte)} · Restantes legenda: ~${restLeg}`;
      const cls = cand.margem_folga ? "margem-folga" : "margem-deficit";
      const prefix = cand.margem_folga ? "+" : "";
      margemCell = `<span class="margem-value ${cls}">${prefix}${formatCompact(cand.margem_corte)}</span>`;
    }

    tr.innerHTML = `
      <td class="col-name">
        <div class="cand-name">
          <span>${cand.nome}</span>
          ${formatCandSubtitle(cand)}
          ${formatBadges(cand)}
        </div>
      </td>
      <td class="col-num" title="${formatNumber(cand.qtd_votos)}">${formatCompact(cand.qtd_votos)}</td>
      <td class="col-pct">${formatPerc(cand.perc_votos)}</td>
      <td class="col-delta">${deltaCell}</td>
      <td class="col-dist dist-cell" title="${distTitle}">${distCell}</td>
      <td class="col-margem margem-cell" title="${margemTitle}">${margemCell}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderDashboardData(data) {
  if (!data) return;
  for (const panel of panels) {
    const panelEl = dashboardEl.querySelector(`[data-id="${panel.id}"]`);
    if (!panelEl) continue;
    renderPanelData(panelEl, data.panels?.[panel.key]);
  }
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
  renderPanels();
  if (meta.mock) {
    setStatus("Modo simulação — dados fictícios com apuração progressiva");
    statusEl?.classList.add("mock");
  }
  await sendHeartbeat();
  scheduleHeartbeat();
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
