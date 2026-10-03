const STORAGE_KEY = "tselivescore-dashboard";
const SESSION_KEY = "tselivescore-session-id";

const dashboardEl = document.getElementById("dashboard");
const statusEl = document.getElementById("status-banner");
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

function renderPanelData(panelEl, data) {
  const metaEl = panelEl.querySelector(".panel-meta");
  const alertEl = panelEl.querySelector(".panel-alert");
  const tbody = panelEl.querySelector("tbody");

  let errorEl = panelEl.querySelector(".panel-error");
  if (!errorEl) {
    errorEl = document.createElement("div");
    errorEl.className = "panel-error";
    alertEl.insertAdjacentElement("afterend", errorEl);
  }

  if (!data) {
    metaEl.textContent = "Aguardando primeira leitura...";
    alertEl.textContent = "";
    errorEl.textContent = "";
    tbody.innerHTML = "";
    return;
  }

  if (data.error) {
    metaEl.textContent = "";
    alertEl.textContent = "";
    errorEl.textContent = data.error;
    tbody.innerHTML = "";
    return;
  }

  errorEl.textContent = "";
  panelEl.querySelector(".panel-title").textContent = data.title || panelLabel(data.key);

  const lines = [`${data.perc_sec_totalizadas}% apurado`];
  if (data.apuracao_iniciada) {
    lines.push(
      `Comparecimento: ${data.perc_comparecimento}% | Votos restantes: ~${formatNumber(data.aprox_votos_restantes)}`
    );
  } else {
    lines.push("Apuração ainda não iniciada.");
  }
  if (data.latest_update_tse) {
    const delay = data.tse_delay_human || `${data.tse_delay_seconds}s`;
    lines.push(
      `Atualizado: ${new Date(data.latest_update_tse).toLocaleString("pt-BR")} (há ${delay})`
    );
  }
  metaEl.textContent = lines.join("\n");
  alertEl.textContent = data.mat_def_label
    ? `Matematicamente definido: ${data.mat_def_label}`
    : "";

  tbody.innerHTML = "";
  const qtdVagas = Number(data.qtd_vagas) || 1;
  data.candidatos?.forEach((cand, idx) => {
    const tr = document.createElement("tr");
    if (cand.sf_e === "s") tr.classList.add("turno");
    if (cand.sf_e !== "n" && cand.sf_e !== "s") tr.classList.add("elected");
    if (idx === qtdVagas) tr.classList.add("cutoff");

    const deltaCell =
      cand.delta_perc == null
        ? ""
        : `<span class="${cand.delta_perc > 0 ? "delta-pos" : "delta-neg"}">${cand.delta_perc > 0 ? "+" : ""}${cand.delta_perc.toFixed(2)}%</span>`;

    const flags = [];
    if (cand.sf_e !== "n") flags.push(`E:${cand.sf_e}`);
    if (cand.sf_st) flags.push(`ST:${cand.sf_st}`);
    const nome = flags.length ? `${flags.join(" ")} ${cand.nome}` : cand.nome;

    tr.innerHTML = `
      <td>${nome}</td>
      <td>${formatNumber(cand.qtd_votos)}</td>
      <td>${cand.perc_votos}%</td>
      <td>${deltaCell}</td>
      <td>${cand.hp != null && cand.hp >= 0 ? formatNumber(cand.hp) : ""}</td>
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
    if (!res.ok) return;
    renderDashboardData(await res.json());
  } catch (err) {
    console.error(err);
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
