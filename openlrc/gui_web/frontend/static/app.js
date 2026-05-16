const state = {
  config: {},
  scan: null,
  jobs: [],
  providers: [],
  activeJobId: null,
  eventSource: null,
  dashboardEventSource: null,
  activePanel: localStorage.getItem("openlrc.activePanel") || "#entryPanel",
  recentRoots: JSON.parse(localStorage.getItem("openlrc.recentRoots") || "[]"),
  autoScanTimer: null,
  configSaveTimer: null,
  configSaveInFlight: false,
  configSavePending: false,
  lastScannedRoot: "",
  lastSavedConfigKey: "",
  snapshotReady: false,
};

const SRC_LANG_OPTIONS = [
  "自动检测",
  "ca",
  "zh",
  "hr",
  "da",
  "nl",
  "en",
  "fi",
  "fr",
  "de",
  "el",
  "it",
  "ja",
  "ko",
  "lt",
  "mk",
  "nb",
  "pl",
  "pt",
  "ro",
  "ru",
  "sl",
  "es",
  "sv",
  "uk",
];

const LIST_FIELD_IDS = [
  "asr_model",
  "device",
  "compute_type",
  "proxy",
  "scan_root_dir",
  "translation_backend",
  "endpoint_mode",
  "relay_provider",
  "relay_base_url",
  "relay_model_name",
  "relay_api_key",
  "openai_api_key",
  "anthropic_api_key",
  "google_api_key",
  "openrouter_api_key",
  "local_mt_model_id",
  "local_mt_host",
  "local_mt_tokenizer_dir",
  "local_mt_gguf_path",
  "local_mt_max_new_tokens",
  "local_mt_batch_size",
  "local_mt_temperature",
  "local_mt_top_p",
  "local_mt_top_k",
  "local_mt_repetition_penalty",
  "fee_limit",
  "consumer_thread",
  "chatbot_model",
  "batch_size_s",
  "merge_length_s",
  "max_single_segment_time",
  "atten_lim_db",
  "src_lang",
  "target_lang",
  "skip_trans",
  "noise_suppress",
  "bilingual_sub",
  "output_timestamp",
  "use_itn",
];

const CHECKBOX_FIELD_IDS = ["skip_trans", "noise_suppress", "bilingual_sub", "output_timestamp", "use_itn"];
const NUMBER_FIELDS = new Set([
  "local_mt_max_new_tokens",
  "local_mt_batch_size",
  "local_mt_temperature",
  "local_mt_top_p",
  "local_mt_top_k",
  "local_mt_repetition_penalty",
  "fee_limit",
  "consumer_thread",
  "batch_size_s",
  "merge_length_s",
  "max_single_segment_time",
  "atten_lim_db",
]);

const BOOLEAN_FIELDS = new Set(CHECKBOX_FIELD_IDS);
const LOCAL_MT_FIELDS = new Set([
  "local_mt_model_id",
  "local_mt_host",
  "local_mt_tokenizer_dir",
  "local_mt_gguf_path",
  "local_mt_max_new_tokens",
  "local_mt_batch_size",
  "local_mt_temperature",
  "local_mt_top_p",
  "local_mt_top_k",
  "local_mt_repetition_penalty",
]);
const RELAY_FIELDS = new Set(["endpoint_mode", "relay_provider", "relay_base_url", "relay_model_name", "relay_api_key"]);
const OFFICIAL_KEY_FIELDS = new Set(["openai_api_key", "anthropic_api_key", "google_api_key", "openrouter_api_key"]);

function $(id) {
  return document.getElementById(id);
}

function setServerStatus(text, live = false) {
  const el = $("serverStatus");
  el.textContent = text;
  el.classList.toggle("status-live", live);
  el.classList.toggle("status-idle", !live);
}

function toast(message, kind = "ok") {
  const host = $("toastHost");
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  host.appendChild(node);
  setTimeout(() => node.remove(), 3400);
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let current = value / 1024;
  let unitIndex = 0;
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024;
    unitIndex += 1;
  }
  return `${current.toFixed(1)} ${units[unitIndex]}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "string" ? payload : payload.detail || JSON.stringify(payload);
    throw new Error(detail);
  }
  return payload;
}

function populateSelect(id, values, selected) {
  const el = $(id);
  el.innerHTML = "";
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    el.appendChild(option);
  }
  if (selected !== undefined && selected !== null) {
    el.value = selected;
  }
}

function initStaticSelects() {
  populateSelect("src_lang", SRC_LANG_OPTIONS, "自动检测");
  populateSelect("translation_backend", ["官方 API", "中转 API", "本地 HY-MT"], "中转 API");
  populateSelect("endpoint_mode", ["中转平台", "官方 API"], "中转平台");
  populateSelect("relay_provider", ["OpenAI 兼容", "Anthropic 兼容"], "OpenAI 兼容");
  populateSelect("device", ["cuda", "cpu"], "cuda");
  populateSelect("compute_type", ["int8", "int8_float16", "int16", "float16", "float32"], "float16");
}

function initInputs(config) {
  for (const id of LIST_FIELD_IDS) {
    const el = $(id);
    if (!el) continue;
    const value = config?.[id];
    if (value === undefined || value === null) continue;
    if (BOOLEAN_FIELDS.has(id)) {
      el.checked = Boolean(value);
    } else if (NUMBER_FIELDS.has(id)) {
      el.value = value === "" ? "" : String(value);
    } else if (id === "translation_backend" || id === "endpoint_mode" || id === "relay_provider" || id === "device" || id === "compute_type") {
      el.value = String(value);
    } else {
      el.value = String(value);
    }
  }
  setRootDir(config?.scan_root_dir || "", "manual", { autoScan: false, autoSave: false });
}

function collectConfig() {
  const payload = {};
  for (const id of LIST_FIELD_IDS) {
    const el = $(id);
    if (!el) continue;
    if (BOOLEAN_FIELDS.has(id)) {
      payload[id] = el.checked;
    } else if (NUMBER_FIELDS.has(id)) {
      payload[id] = el.value === "" ? null : Number(el.value);
    } else {
      payload[id] = el.value;
    }
  }
  return payload;
}

function configSignature(payload = collectConfig()) {
  return JSON.stringify(LIST_FIELD_IDS.map((id) => [id, payload[id] ?? null]));
}

function updateProviderFieldState(config = collectConfig()) {
  const backend = config.translation_backend || "中转 API";
  const localEnabled = backend === "本地 HY-MT";
  const relayEnabled = backend === "中转 API";
  const officialEnabled = backend === "官方 API";

  for (const id of LOCAL_MT_FIELDS) {
    const el = $(id);
    if (el) el.disabled = !localEnabled;
  }
  for (const id of RELAY_FIELDS) {
    const el = $(id);
    if (el) el.disabled = !relayEnabled;
  }
  for (const id of OFFICIAL_KEY_FIELDS) {
    const el = $(id);
    if (el) el.disabled = !(officialEnabled || relayEnabled);
  }
  const chatbotModel = $("chatbot_model");
  if (chatbotModel) chatbotModel.disabled = localEnabled;
}

function syncConfigForm(config) {
  if (!config) return;
  state.config = config;
  initInputs(config);
  updateProviderFieldState(config);
  state.lastSavedConfigKey = configSignature(config);
}

function setRootDir(pathText, source = "manual", options = {}) {
  const autoScan = options.autoScan !== false;
  const autoSave = options.autoSave !== false;
  const normalized = String(pathText || "").trim().replace(/^file:\/\/\/?/i, "").replace(/\//g, "\\");
  const input = $("scan_root_dir");
  if (!input) return;
  input.value = normalized;
  state.scan = state.scan || null;
  if (!normalized) {
    return;
  }
  if (autoSave) {
    scheduleAutoSave();
  }
  if (autoScan) {
    scheduleAutoScan();
  }
}

function extractDroppedPath(event) {
  const dataTransfer = event.dataTransfer;
  if (!dataTransfer) return "";

  const plainText = dataTransfer.getData("text/plain").trim();
  if (plainText) return plainText.split(/\r?\n/)[0].trim();

  const uriText = dataTransfer.getData("text/uri-list").trim();
  if (uriText) return decodeURIComponent(uriText.split(/\r?\n/).find((line) => line && !line.startsWith("#")) || "");

  for (const file of dataTransfer.files || []) {
    if (file.path) return file.path;
  }
  return "";
}

async function chooseRootFolder() {
  try {
    const data = await fetchJson("/api/dialogs/folder", {
      method: "POST",
      body: JSON.stringify({ initial_dir: $("scan_root_dir")?.value || "" }),
    });
    if (data.selected && data.path) {
      setRootDir(data.path, "dialog");
      toast("已选择根目录", "ok");
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

function scheduleAutoScan() {
  if (state.autoScanTimer) {
    clearTimeout(state.autoScanTimer);
  }
  state.autoScanTimer = setTimeout(() => {
    state.autoScanTimer = null;
    void autoScanRoot();
  }, 450);
}

function scheduleAutoSave() {
  if (state.configSaveTimer) {
    clearTimeout(state.configSaveTimer);
  }
  state.configSaveTimer = setTimeout(() => {
    state.configSaveTimer = null;
    void autoSaveConfig();
  }, 400);
}

async function autoScanRoot(options = {}) {
  const force = options.force === true;
  const payload = collectConfig();
  const rootDir = String(payload.scan_root_dir || "").trim();
  if (!rootDir) return;
  if (!force && state.lastScannedRoot === rootDir && state.snapshotReady) {
    return;
  }
  try {
    setServerStatus("扫描中", true);
    const data = await fetchJson("/api/scan", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.scan = data;
    state.lastScannedRoot = rootDir;
    renderSummary(data.summary || []);
    renderTasks(data.tasks || []);
    localStorage.setItem("openlrc.recentRoots", JSON.stringify([payload.scan_root_dir, ...state.recentRoots.filter((item) => item !== payload.scan_root_dir)].slice(0, 6)));
    state.recentRoots = JSON.parse(localStorage.getItem("openlrc.recentRoots") || "[]");
    toast(`已自动扫描：${data.audio_count} 个文件`, "ok");
    activateWorkspacePanel("#workPanel");
    await refreshOutputs();
  } catch (error) {
    toast(error.message, "error");
    setServerStatus("在线", true);
  }
}

async function autoSaveConfig() {
  const payload = collectConfig();
  const signature = configSignature(payload);
  if (signature === state.lastSavedConfigKey && !state.configSavePending) {
    return;
  }
  if (state.configSaveInFlight) {
    state.configSavePending = true;
    return;
  }
  state.configSaveInFlight = true;
  state.configSavePending = false;
  try {
    const data = await fetchJson("/api/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    syncConfigForm(data);
    setServerStatus("在线", true);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.configSaveInFlight = false;
    if (state.configSavePending) {
      state.configSavePending = false;
      if (configSignature(collectConfig()) !== state.lastSavedConfigKey) {
        scheduleAutoSave();
      }
    }
  }
}

function rootFontSize() {
  return Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
}

function normalizeNavWidthToRem(width) {
  const raw = String(width || "").trim();
  if (!raw) return 16.25;
  if (raw.endsWith("rem")) return Number.parseFloat(raw) || 16.25;
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) return 16.25;
  return numeric > 80 ? numeric / rootFontSize() : numeric;
}

function setNavWidth(width) {
  const widthRem = normalizeNavWidthToRem(width);
  const clamped = Math.max(5.25, Math.min(26.25, widthRem));
  document.documentElement.style.setProperty("--nav-width", `${clamped}rem`);
  $("navRail")?.classList.toggle("collapsed", clamped < 10.625);
  localStorage.setItem("openlrc.navWidth", `${clamped}rem`);
}

function setSettingsOpen(open) {
  $("settingsDrawer")?.classList.toggle("closed", !open);
  localStorage.setItem("openlrc.settingsOpen", open ? "1" : "0");
}

function activateWorkspacePanel(selector) {
  if (selector === "#settingsDrawer") {
    setSettingsOpen(true);
    return;
  }

  const target = document.querySelector(selector);
  if (!target?.classList.contains("stage-view")) {
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  document.querySelectorAll(".stage-view").forEach((panel) => {
    panel.classList.toggle("active", `#${panel.id}` === selector);
  });
  document.querySelectorAll("[data-jump]").forEach((button) => {
    const jump = button.getAttribute("data-jump");
    button.classList.toggle("active", jump === selector);
  });
  state.activePanel = selector;
  localStorage.setItem("openlrc.activePanel", selector);
}

function initShellState() {
  setNavWidth(localStorage.getItem("openlrc.navWidth") || "16.25rem");
  setSettingsOpen(localStorage.getItem("openlrc.settingsOpen") === "1");
  const selector = document.querySelector(state.activePanel)?.classList.contains("stage-view")
    ? state.activePanel
    : "#entryPanel";
  activateWorkspacePanel(selector);
}

function bindShellEvents() {
  $("toggleSettingsBtn")?.addEventListener("click", () => setSettingsOpen(Boolean($("settingsDrawer")?.classList.contains("closed"))));
  $("closeSettingsBtn")?.addEventListener("click", () => setSettingsOpen(false));

  const resizeHandle = $("navResizeHandle");
  if (!resizeHandle) return;
  let resizing = false;
  resizeHandle.addEventListener("mousedown", (event) => {
    resizing = true;
    event.preventDefault();
    document.body.classList.add("is-resizing");
  });
  window.addEventListener("mousemove", (event) => {
    if (!resizing) return;
    setNavWidth(event.clientX / rootFontSize());
  });
  window.addEventListener("mouseup", () => {
    if (!resizing) return;
    resizing = false;
    document.body.classList.remove("is-resizing");
  });
}

function bindRootDropZone() {
  const dropZone = $("rootDropZone");
  if (!dropZone) return;

  dropZone.addEventListener("click", chooseRootFolder);
  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      chooseRootFolder();
    }
  });

  for (const eventName of ["dragenter", "dragover"]) {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("drag-over");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    dropZone.addEventListener(eventName, () => {
      dropZone.classList.remove("drag-over");
    });
  }
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    const pathText = extractDroppedPath(event);
    if (pathText) {
      setRootDir(pathText, "drop");
      toast("已识别拖入路径", "ok");
      return;
    }
    toast("浏览器无法读取拖入文件夹的真实路径，请点击选择文件夹。", "error");
  });
  dropZone.addEventListener("paste", (event) => {
    const text = event.clipboardData?.getData("text/plain")?.trim();
    if (!text) return;
    event.preventDefault();
    setRootDir(text, "paste");
    toast("已粘贴路径", "ok");
  });
}

function renderSummary(summary) {
  const host = $("summaryGrid");
  host.innerHTML = "";
  for (const item of summary || []) {
    const card = document.createElement("div");
    card.className = "summary-card";
    card.innerHTML = `<div class="summary-label">${item.label}</div><div class="summary-value">${item.value}</div>`;
    host.appendChild(card);
  }
}

function renderTasks(tasks) {
  const body = $("taskTableBody");
  body.innerHTML = "";
  for (const task of tasks || []) {
    const row = document.createElement("tr");
    const estimate = task.meta?.translation_estimate || task.translation_estimate_path ? "已缓存" : "未估算";
    const cache = task.cache_valid ? "可复用" : "需重转写";
    row.innerHTML = `
      <td>
        <div class="output-path">${task.relative_path}</div>
        <div class="output-meta">${task.audio_path}</div>
      </td>
      <td>${task.status || "-"}</td>
      <td>${cache}</td>
      <td>${estimate}</td>
      <td>${task.lrc_path || "-"}</td>
    `;
    body.appendChild(row);
  }
  const startButton = $("startJobBtn");
  if (startButton) {
    startButton.disabled = !(tasks || []).length;
  }
}

function renderProviders(providers) {
  const host = $("providerCards");
  host.innerHTML = "";
  for (const provider of providers || []) {
    const card = document.createElement("div");
    card.className = `provider-card ${provider.active ? "active" : ""}`;
    const errorHtml = provider.validation_errors && provider.validation_errors.length
      ? `<div class="provider-errors">${provider.validation_errors.map((item) => `• ${item}`).join("<br />")}</div>`
      : "";
    card.innerHTML = `
      <div class="provider-card-header">
        <div>
          <div class="provider-name">${provider.label}</div>
          <div class="provider-meta">${provider.summary}</div>
        </div>
        <div class="status-chip ${provider.active ? "status-live" : "status-idle"}">${provider.active ? "生效" : "未启用"}</div>
      </div>
      <div class="provider-meta">模块：${provider.module_file}<br />预计：${provider.estimated_duration}</div>
      ${errorHtml}
    `;
    host.appendChild(card);
  }

  const active = (providers || []).find((item) => item.active) || providers?.[0];
  if (active) {
    const lines = [];
    if (active.replan_text) {
      $("replanText").textContent = active.replan_text;
      return;
    }
    lines.push(`当前模块：${active.label}`);
    lines.push(`模块文件：${active.module_file}`);
    lines.push(`预计时长：${active.estimated_duration}`);
    (active.replan_steps || []).forEach((step, index) => {
      lines.push(`${index + 1}. ${step.step}（${step.duration_label}）`);
    });
    $("replanText").textContent = lines.join("\n");
  }
}

function renderJobs(jobs) {
  const host = $("jobStrip");
  host.innerHTML = "";
  const sorted = [...(jobs || [])].sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  state.jobs = sorted;
  for (const job of sorted) {
    const card = document.createElement("div");
    const active = state.activeJobId === job.id;
    card.className = `job-card ${active ? "active" : ""}`;
    card.innerHTML = `
      <div class="job-title">
        <span>${job.id}</span>
        <span class="status-chip ${job.status === "completed" ? "status-live" : "status-idle"}">${job.status}</span>
      </div>
      <div class="job-meta">
        根目录：${job.root_dir}<br />
        进度：${job.progress || 0}%<br />
        阶段：${job.stage || "-"}<br />
        当前：${job.current_file || "-"}
      </div>
      <div class="hero-actions job-card-actions">
        <button class="ghost-btn" data-action="focus-job" data-job="${job.id}">查看</button>
        <button class="ghost-btn" data-action="retry-job" data-job="${job.id}" ${["failed", "cancelled"].includes(job.status) ? "" : "disabled"}>重试</button>
        <button class="ghost-btn danger" data-action="cancel-job" data-job="${job.id}" ${["completed", "failed", "cancelled"].includes(job.status) ? "disabled" : ""}>取消</button>
      </div>
    `;
    host.appendChild(card);
  }
}

function appendLog(message) {
  if (!message) return;
  const consoleEl = $("logConsole");
  consoleEl.textContent += `${message}\n`;
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

function resetLog(text = "") {
  $("logConsole").textContent = text;
}

function renderOutputs(files) {
  const host = $("outputList");
  host.innerHTML = "";
  for (const file of files || []) {
    const item = document.createElement("div");
    item.className = "output-item";
    item.innerHTML = `
      <div>
        <div class="output-path">${file.relative_path}</div>
        <div class="output-meta">${file.path}</div>
      </div>
      <div class="output-meta">${formatBytes(file.size)}</div>
    `;
    host.appendChild(item);
  }
}

function applyScan(scan) {
  state.scan = scan || null;
  state.lastScannedRoot = state.scan?.root_dir || state.lastScannedRoot;
  renderSummary(state.scan?.summary || []);
  renderTasks(state.scan?.tasks || []);
}

function applyProviders(providers) {
  state.providers = providers || [];
  renderProviders(state.providers);
}

function applyJobs(jobs) {
  state.jobs = jobs || [];
  renderJobs(state.jobs);
  const active = state.jobs.find((job) => !["completed", "failed", "cancelled"].includes(job.status)) || state.jobs[0];
  if (active?.confirmation_state && active.status === "waiting_confirmation") {
    showConfirmation(active.confirmation_state);
  }
  return active;
}

async function applyDashboardSnapshot(snapshot) {
  if (!snapshot) return;
  syncConfigForm(snapshot.config || state.config || {});
  applyScan(snapshot.scan || null);
  applyProviders(snapshot.providers || []);
  const active = applyJobs(snapshot.jobs || []);
  if (active && active.id && state.activeJobId !== active.id && !["completed", "failed", "cancelled"].includes(active.status)) {
    openJobStream(active.id);
  }
  if (state.scan?.root_dir) {
    await refreshOutputs();
  }
  state.snapshotReady = true;
  setServerStatus("在线", true);
}

function setJobStatus(job) {
  if (!job) return;
  state.activeJobId = job.id;
  setServerStatus(job.status === "completed" ? "已完成" : `任务 ${job.status}`, job.status === "completed");
  renderJobs(state.jobs);
}

function parseEventPayload(event) {
  if (!event?.data) return {};
  try {
    return JSON.parse(event.data);
  } catch {
    return {};
  }
}

function connectDashboardEvents() {
  if (state.dashboardEventSource) {
    state.dashboardEventSource.close();
  }

  const source = new EventSource("/api/events/dashboard");
  state.dashboardEventSource = source;

  source.addEventListener("dashboard_snapshot", async (event) => {
    const payload = parseEventPayload(event);
    await applyDashboardSnapshot(payload.payload || payload);
  });
  source.addEventListener("scan_changed", async (event) => {
    const payload = parseEventPayload(event).payload || {};
    applyScan(payload.scan || null);
    if (payload.scan?.root_dir) {
      await refreshOutputs();
    }
    setServerStatus("在线", true);
  });
  source.addEventListener("config_changed", (event) => {
    const payload = parseEventPayload(event).payload || {};
    if (payload.config) {
      syncConfigForm(payload.config);
    }
    if (payload.providers) {
      applyProviders(payload.providers);
    }
  });
  const handleJobsChanged = async (event) => {
    const payload = parseEventPayload(event).payload || {};
    const active = applyJobs(payload.jobs || state.jobs);
    if (active && active.id && state.activeJobId !== active.id && !["completed", "failed", "cancelled"].includes(active.status)) {
      openJobStream(active.id);
    }
    if (payload.outputs_changed && state.scan?.root_dir) {
      await refreshOutputs();
    }
    setServerStatus("在线", true);
  };
  source.addEventListener("job_event", handleJobsChanged);
  source.addEventListener("job_changed", handleJobsChanged);
  source.addEventListener("cache_changed", async (event) => {
    const payload = parseEventPayload(event).payload || {};
    if (payload.root_dir) {
      setRootDir(payload.root_dir, "event", { autoScan: false });
      await autoScanRoot({ force: true });
    }
    if (payload.outputs_changed) {
      await refreshOutputs();
    }
  });
  source.addEventListener("ping", () => {
    setServerStatus("在线", true);
  });
  source.onerror = () => {
    setServerStatus("连接中断", false);
  };
}

async function refreshProviderPreview() {
  const payload = collectConfig();
  updateProviderFieldState(payload);
  const data = await fetchJson("/api/providers/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.providers = data.providers || [];
  renderProviders(state.providers);
}

function openJobStream(jobId) {
  if (!jobId) return;
  if (state.eventSource) {
    state.eventSource.close();
  }
  state.activeJobId = jobId;
  renderJobs(state.jobs);
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  state.eventSource = source;
  source.addEventListener("hello", () => {});
  source.addEventListener("ping", () => {});
  source.addEventListener("log", (event) => {
    const payload = JSON.parse(event.data);
    appendLog(payload.payload?.message || payload.message || "");
  });
  source.addEventListener("stage", (event) => {
    const payload = JSON.parse(event.data);
    appendLog(payload.payload?.message || payload.message || "");
    refreshJob(jobId);
  });
  source.addEventListener("current_file", (event) => {
    const payload = JSON.parse(event.data);
    appendLog(payload.payload?.message || payload.message || "");
    refreshJob(jobId);
  });
  source.addEventListener("estimate", (event) => {
    const payload = JSON.parse(event.data);
    appendLog(payload.payload?.message || payload.message || "");
  });
  source.addEventListener("progress", (event) => {
    const payload = JSON.parse(event.data);
    appendLog(payload.payload?.message ? `进度 ${payload.payload.progress || 0}%：${payload.payload.message}` : "");
    refreshJob(jobId);
  });
  source.addEventListener("confirmation_required", (event) => {
    const payload = JSON.parse(event.data);
    state.activeJobId = jobId;
    refreshJob(jobId);
    showConfirmation(payload.payload?.state || payload.state || null);
  });
  source.addEventListener("completed", async (event) => {
    const payload = JSON.parse(event.data);
    appendLog("任务完成");
    hideConfirmation();
    await refreshJob(jobId);
    await refreshOutputs();
    if (payload.payload?.generated_files || payload.generated_files) {
      toast("处理完成", "ok");
    }
  });
  source.addEventListener("failed", async (event) => {
    const payload = JSON.parse(event.data);
    appendLog(`失败：${payload.payload?.message || payload.message || "unknown"}`);
    hideConfirmation();
    await refreshJob(jobId);
    toast("任务失败", "error");
  });
  source.addEventListener("cancelled", async () => {
    appendLog("任务已取消");
    hideConfirmation();
    await refreshJob(jobId);
  });
  source.onerror = () => {
    setServerStatus("连接中断", false);
  };
}

async function refreshJob(jobId) {
  const job = await fetchJson(`/api/jobs/${jobId}`);
  const index = state.jobs.findIndex((item) => item.id === jobId);
  if (index >= 0) {
    state.jobs[index] = job;
  } else {
    state.jobs.unshift(job);
  }
  renderJobs(state.jobs);
  if (job.confirmation_state && job.status === "waiting_confirmation") {
    showConfirmation(job.confirmation_state);
  }
}

function renderConfirmation(stateObj) {
  const dialog = $("confirmationDialog");
  const hint = $("confirmationHint");
  const meta = $("confirmationMeta");
  const list = $("confirmationList");
  if (!stateObj) return;

  hint.textContent = `root=${stateObj.root_dir || "-"} / target=${stateObj.target_lang || "-"}`;
  meta.innerHTML = "";
  const pills = [
    `文件数 ${stateObj.entries?.length || 0}`,
    `保底 ${Number(stateObj.total_floor_fee || 0).toFixed(4)}`,
    `建议 ${Number(stateObj.total_likely_fee || 0).toFixed(4)}`,
  ];
  for (const text of pills) {
    const pill = document.createElement("div");
    pill.className = "confirmation-pill";
    pill.textContent = text;
    meta.appendChild(pill);
  }

  list.innerHTML = "";
  for (const entry of stateObj.entries || []) {
    const item = document.createElement("label");
    item.className = "confirmation-item";
    item.innerHTML = `
      <input type="checkbox" data-confirm-item="${entry.relative_path}" checked />
      <div>
        <strong>${entry.relative_path}</strong>
        <div class="provider-meta">保底 ${Number(entry.estimate?.total_floor_fee || 0).toFixed(4)} / 建议 ${Number(entry.estimate?.total_likely_fee || 0).toFixed(4)}</div>
      </div>
    `;
    list.appendChild(item);
  }
  if (!dialog.open) {
    dialog.showModal();
  }
}

function showConfirmation(stateObj) {
  renderConfirmation(stateObj);
}

function hideConfirmation() {
  const dialog = $("confirmationDialog");
  if (dialog.open) {
    dialog.close();
  }
}

async function refreshOutputs() {
  const rootDir = $("scan_root_dir").value.trim();
  if (!rootDir) return;
  const data = await fetchJson(`/api/files/outputs?root_dir=${encodeURIComponent(rootDir)}`);
  renderOutputs(data.files || []);
}

async function startJob() {
  const payload = collectConfig();
  if (!payload.scan_root_dir) {
    toast("请先填写根目录", "error");
    return;
  }
  const data = await fetchJson("/api/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const job = data.job;
  state.jobs.unshift(job);
  renderJobs(state.jobs);
  openJobStream(job.id);
  appendLog(`创建任务：${job.id}`);
  activateWorkspacePanel("#logPanel");
}

async function confirmSelection() {
  if (!state.activeJobId) {
    toast("没有可确认的任务", "error");
    return;
  }
  const selected = [...document.querySelectorAll("[data-confirm-item]:checked")].map((el) => el.getAttribute("data-confirm-item"));
  const data = await fetchJson(`/api/jobs/${state.activeJobId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ selected_relative_paths: selected }),
  });
  renderJobs(state.jobs);
  if (data.job?.status) {
    openJobStream(data.job.id || state.activeJobId);
  }
  toast("已提交确认", "ok");
}

async function cancelJob(jobId) {
  await fetchJson(`/api/jobs/${jobId}/cancel`, { method: "POST", body: JSON.stringify({}) });
  toast("已取消", "ok");
}

async function retryJob(jobId) {
  const data = await fetchJson(`/api/jobs/${jobId}/retry`, { method: "POST", body: JSON.stringify({}) });
  const job = data.job;
  state.jobs.unshift(job);
  renderJobs(state.jobs);
  openJobStream(job.id);
  toast("已重试", "ok");
}

async function testLocalMt() {
  const payload = collectConfig();
  const text = prompt("测试样例文本", "Hello, this is a test.");
  if (!text) return;
  try {
    const data = await fetchJson("/api/providers/local-hymt/test", {
      method: "POST",
      body: JSON.stringify({ ...payload, sample_text: text }),
    });
    toast(`本地模型返回：${data.translated_text}`, "ok");
    appendLog(`HY-MT 测试：${data.translated_text}`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function openOutputRoot() {
  const root = $("scan_root_dir").value.trim();
  if (!root) {
    toast("请先输入根目录", "error");
    return;
  }
  await fetchJson("/api/files/open-folder", {
    method: "POST",
    body: JSON.stringify({ path: root }),
  });
}

async function clearCurrentCache() {
  const root = $("scan_root_dir").value.trim();
  if (!root) {
    toast("请先输入根目录", "error");
    return;
  }
  await fetchJson("/api/files/clear-cache", {
    method: "POST",
    body: JSON.stringify({ root_dir: root }),
  });
  toast("缓存已清理", "ok");
}

async function copyLog() {
  const text = $("logConsole").textContent;
  await navigator.clipboard.writeText(text);
  toast("日志已复制", "ok");
}

function bindEvents() {
  $("startJobBtn").addEventListener("click", startJob);
  $("openOutputRootBtn").addEventListener("click", openOutputRoot);
  $("clearCacheBtn").addEventListener("click", clearCurrentCache);
  $("copyLogBtn").addEventListener("click", copyLog);
  $("testLocalMtBtn").addEventListener("click", testLocalMt);
  $("closeConfirmationBtn").addEventListener("click", hideConfirmation);
  $("confirmSelectionBtn").addEventListener("click", confirmSelection);

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const jobId = button.getAttribute("data-job");
    const action = button.getAttribute("data-action");
    if (action === "focus-job") {
      openJobStream(jobId);
      await refreshJob(jobId);
      return;
    }
    if (action === "cancel-job") {
      await cancelJob(jobId);
      await refreshJob(jobId);
      return;
    }
    if (action === "retry-job") {
      await retryJob(jobId);
      return;
    }
  });

  document.querySelectorAll("[data-jump]").forEach((button) => {
    button.addEventListener("click", () => {
      activateWorkspacePanel(button.getAttribute("data-jump"));
    });
  });

  for (const id of LIST_FIELD_IDS) {
    const el = $(id);
    if (!el) continue;
    const onConfigEdit = async () => {
      scheduleAutoSave();
      if (id === "translation_backend" || id === "endpoint_mode" || id === "relay_provider") {
        try {
          await refreshProviderPreview();
        } catch (error) {
          toast(error.message, "error");
        }
      }
    };
    el.addEventListener("input", onConfigEdit);
    el.addEventListener("change", onConfigEdit);
  }
}

async function main() {
  initStaticSelects();
  initShellState();
  bindShellEvents();
  bindRootDropZone();
  bindEvents();
  resetLog("OpenLRC Web 已启动。\n");
  setServerStatus("等待初始快照", false);
  try {
    connectDashboardEvents();
  } catch (error) {
    setServerStatus("离线", false);
    toast(error.message, "error");
    appendLog(error.stack || error.message);
  }
}

main();
