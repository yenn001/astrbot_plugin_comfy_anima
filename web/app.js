"use strict";

let csrfToken = "";
let bootstrapData = null;
let currentPanel = "overview";
let toastTimer = null;
let loraItems = [];
let loraFilter = "all";
let loraArchiveFilter = "all";
let loraArchiveStatus = null;
let archiveRunInFlight = false;
let profileItems = [];
let workflowItems = [];
let toolWorkflowItems = [];
let consoleEntries = [];
let consoleCursor = 0;
let consoleMeta = null;
let consolePollTimer = null;
let consoleLoading = false;
let consolePaused = false;
let consoleClearMarker = null;
let consoleStreamId = "";
let taskItems = [];
let selectedTaskId = "";
let selectedTask = null;
let taskEvents = [];
let taskEventCursor = 0;
let taskEventOrder = "desc";
let taskEventPageSize = 20;
let taskEventPage = 1;
let taskPollTimer = null;
let taskLoading = false;
let taskDetailLoading = false;
let activeTaskRestoreChecked = false;
let currentLoraDetailName = "";
let currentUiTheme = "workshop";
const taskLatestEvents = new Map();
const volatilePreferences = new Map();
const volatileSessionPreferences = new Map();

const selectedLoras = new Set();

const panelTitles = {
  overview: "运行概览",
  settings: "插件设置",
  loras: "LoRA 管理",
  presets: "风格与角色串",
  models: "UNET 模型",
  tasks: "任务中心",
  console: "运行控制台",
};

const consoleCategoryLabels = {
  generation: "绘图",
  lora: "LoRA",
  llm: "LLM",
  web: "WebUI",
  plugin: "插件",
};

const themeMetaColors = {
  workshop: "#25211d",
  editorial: "#34322e",
  night: "#151311",
};

const loraCategoryLabels = {
  character: "角色",
  artist_style: "画师 / 风格",
  speed_sampling: "加速 / 采样",
  quality_enhancement: "画质增强",
  detail_restoration: "细节修复",
  composition_pose: "构图 / 姿势",
  lighting_color: "光影 / 色彩",
  background_environment: "背景 / 环境",
  clothing_concept: "服装 / 概念",
  mixed: "混合",
  unclassified: "未分类",
  unknown: "未分类",
};

const filterCountIds = {
  all: "filter-count-all",
  character: "filter-count-character",
  artist_style: "filter-count-artist-style",
  speed_sampling: "filter-count-speed-sampling",
  quality_enhancement: "filter-count-quality-enhancement",
  detail_restoration: "filter-count-detail-restoration",
  composition_pose: "filter-count-composition-pose",
  lighting_color: "filter-count-lighting-color",
  background_environment: "filter-count-background-environment",
  clothing_concept: "filter-count-clothing-concept",
  mixed: "filter-count-mixed",
  unclassified: "filter-count-unclassified",
};

const archiveStateLabels = {
  searchable: "✓ AI 档案可搜索",
  analyzing: "◌ AI 正在建档",
  review_needed: "△ 需要人工确认",
  stale: "↻ 资料变化，需更新",
  metadata_ready: "◇ 元数据已就绪",
  failed: "! 建档失败",
  unarchived: "— 尚未建档",
};

const archiveFilterCountIds = {
  all: "archive-filter-count-all",
  searchable: "archive-filter-count-searchable",
  analyzing: "archive-filter-count-analyzing",
  review_needed: "archive-filter-count-review-needed",
  stale: "archive-filter-count-stale",
  metadata_ready: "archive-filter-count-metadata-ready",
  failed: "archive-filter-count-failed",
  unarchived: "archive-filter-count-unarchived",
};

const taskStatusLabels = {
  queued: "排队中",
  running: "运行中",
  succeeded: "成功",
  partial: "部分完成",
  failed: "失败",
  cancelled: "已取消",
  timed_out: "超时",
  interrupted: "已中断",
};

const taskTypeLabels = {
  lora_semantic_analysis: "LoRA 语义建档",
  lora_archive: "LoRA AI 建档",
  lora_metadata: "LoRA 元数据",
  lora_metadata_fetch: "LoRA 元数据",
  lora_download: "LoRA 下载",
  lora_refresh: "LoRA 刷新",
  asset_delete: "资产删除",
  reverse_prompt: "图片反推",
  reverse_draw: "反推画图",
  semantic_redraw: "整图语义重绘",
  rtx_upscale: "RTX 放大",
  inpaint: "遮罩局部重绘",
};

const activeTaskStatuses = new Set(["queued", "running"]);

const numberFields = new Set([
  "default_width",
  "default_height",
  "max_concurrent_jobs",
  "user_cooldown",
  "rtx_scale",
  "iterative_scale",
  "iterative_steps",
  "iterative_denoise",
  "prompt_llm_temperature",
  "prompt_llm_max_tokens",
  "character_swap_timeout",
  "reverse_prompt_timeout",
  "reverse_prompt_temperature",
  "reverse_prompt_max_tokens",
  "max_input_image_size_mb",
  "max_input_image_pixels",
  "max_total_dynamic_loras",
  "max_preset_loras",
  "max_dynamic_loras",
  "lora_embedding_top_k",
  "lora_rerank_top_n",
  "lora_retrieval_timeout",
  "sampler_steps_override",
  "web_ui_port",
  "web_ui_session_ttl",
]);

const booleanFields = new Set([
  "enable_upscale",
  "enable_inpaint",
  "send_generation_notice",
  "enable_prompt_llm",
  "enable_natural_draw",
  "enable_llm_pic_trigger",
  "enable_reverse_prompt",
  "enable_reverse_json_formatter",
  "enable_reverse_json_repair_retry",
  "enable_lora_tool",
  "enable_lora_download",
  "enable_lora_hybrid_search",
  "strict_lora_validation",
  "global_lock",
  "whitelist_only",
  "admin_ignore_cooldown",
  "admin_ignore_whitelist",
  "admin_ignore_blocklist",
  "enable_web_ui",
]);

function pluginPageBridge() {
  const bridge = window.AstrBotPluginPage;
  return bridge && typeof bridge.apiPost === "function" ? bridge : null;
}

function readPreference(key, fallback = null) {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value;
  } catch (_error) {
    return volatilePreferences.has(key) ? volatilePreferences.get(key) : fallback;
  }
}

function writePreference(key, value) {
  volatilePreferences.set(key, String(value));
  try {
    window.localStorage.setItem(key, String(value));
  } catch (_error) {
    // Sandboxed AstrBot plugin pages can reject persistent storage.
  }
}

function readSessionPreference(key, fallback = null) {
  try {
    const value = window.sessionStorage.getItem(key);
    return value === null ? fallback : value;
  } catch (_error) {
    return volatileSessionPreferences.has(key)
      ? volatileSessionPreferences.get(key)
      : fallback;
  }
}

function writeSessionPreference(key, value) {
  volatileSessionPreferences.set(key, String(value));
  try {
    window.sessionStorage.setItem(key, String(value));
  } catch (_error) {
    // Sandboxed AstrBot plugin pages can reject session storage.
  }
}

function wait(delay) {
  return new Promise((resolve) => setTimeout(resolve, delay));
}

async function reloadAfterPluginChange(delay = 2600) {
  await wait(delay);
  if (!pluginPageBridge()) {
    window.location.replace("/login");
    return;
  }

  let lastError = null;
  for (let attempt = 1; attempt <= 12; attempt += 1) {
    try {
      await loadBootstrap();
      if (!new Set(["overview", "settings"]).has(currentPanel)) {
        await loadCurrentPanel();
      }
      showToast("插件已重载，当前面板已重新连接。", false);
      return;
    } catch (error) {
      lastError = error;
      if (attempt < 12) await wait(Math.min(750 + attempt * 250, 2500));
    }
  }
  showToast(`插件重载后尚未恢复：${lastError?.message || "连接超时"}`, true);
}

function confirmAction(message, {
  title = "请确认",
  confirmLabel = "确认操作",
  expectedValue = "",
  inputLabel = "输入完整名称以确认",
  danger = true,
} = {}) {
  const dialog = document.querySelector("#confirm-dialog");
  if (!dialog || typeof dialog.showModal !== "function") {
    return Promise.resolve(false);
  }
  if (dialog.open) dialog.close("cancel");

  const titleNode = document.querySelector("#confirm-dialog-title");
  const messageNode = document.querySelector("#confirm-dialog-message");
  const inputWrap = document.querySelector("#confirm-dialog-input-wrap");
  const inputLabelNode = document.querySelector("#confirm-dialog-input-label");
  const input = document.querySelector("#confirm-dialog-input");
  const confirmButton = document.querySelector("#confirm-dialog-confirm");
  titleNode.textContent = title;
  messageNode.textContent = message;
  inputLabelNode.textContent = inputLabel;
  inputWrap.hidden = !expectedValue;
  input.value = "";
  input.required = Boolean(expectedValue);
  input.autocomplete = "off";
  confirmButton.textContent = confirmLabel;
  confirmButton.className = danger ? "danger" : "primary";
  confirmButton.disabled = Boolean(expectedValue);
  dialog.returnValue = "cancel";

  return new Promise((resolve) => {
    const syncConfirmation = () => {
      confirmButton.disabled = Boolean(expectedValue) && input.value !== expectedValue;
    };
    const finish = () => {
      input.removeEventListener("input", syncConfirmation);
      resolve(
        dialog.returnValue === "confirm"
        && (!expectedValue || input.value === expectedValue)
      );
    };
    input.addEventListener("input", syncConfirmation);
    dialog.addEventListener("close", finish, {once: true});
    dialog.showModal();
    if (expectedValue) input.focus();
    else confirmButton.focus();
  });
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const bridge = pluginPageBridge();
  if (bridge) {
    await bridge.ready();
    const target = new URL(path, "https://plugin-page.invalid");
    const query = {};
    for (const [key, value] of target.searchParams.entries()) query[key] = value;
    let body = {};
    if (typeof options.body === "string" && options.body) {
      try {
        body = JSON.parse(options.body);
      } catch (_error) {
        throw new Error("插件页面请求体不是有效 JSON");
      }
    } else if (options.body && typeof options.body === "object") {
      body = options.body;
    }
    return bridge.apiPost("api/gateway", {
      method,
      path: target.pathname,
      query,
      body,
    });
  }

  const headers = new Headers(options.headers || {});
  if (method !== "GET" && method !== "HEAD") {
    headers.set("X-CSRF-Token", csrfToken);
  }
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {...options, method, headers});
  if (response.status === 401) {
    window.location.replace("/login");
    throw new Error("登录已失效");
  }
  let payload;
  try {
    payload = await response.json();
  } catch (_error) {
    throw new Error(`服务器返回异常（HTTP ${response.status}）`);
  }
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `操作失败（HTTP ${response.status}）`);
  }
  return payload.data;
}

function applyTheme(name, {persist = true} = {}) {
  const theme = Object.prototype.hasOwnProperty.call(themeMetaColors, name)
    ? name
    : "workshop";
  currentUiTheme = theme;
  document.documentElement.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = themeMetaColors[theme];
  const select = document.querySelector("#theme-select");
  if (select && select.value !== theme) select.value = theme;
  if (persist) {
    writePreference("comfy-anima-theme", theme);
  }
}

function initializeThemePicker() {
  applyTheme(
    readPreference(
      "comfy-anima-theme",
      document.documentElement.dataset.theme || "workshop",
    ),
    {persist: false},
  );
  document.querySelector("#theme-select").addEventListener("change", (event) => {
    applyTheme(event.target.value);
    showToast(`已切换为“${event.target.selectedOptions[0].textContent}”。`);
  });
  window.addEventListener("storage", (event) => {
    if (event.key === "comfy-anima-theme" && event.newValue) {
      applyTheme(event.newValue, {persist: false});
    }
  });
  const bridge = pluginPageBridge();
  if (bridge) {
    bridge.onContext(() => applyTheme(currentUiTheme, {persist: false}));
  }
}

function showToast(message, isError = false) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 4200);
}

function setBusy(button, busy, busyText = "处理中…") {
  if (!button) return;
  if (busy) {
    button.dataset.idleText = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.idleText || button.textContent;
    button.disabled = false;
  }
}

function textCell(text, className = "", label = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  if (label) cell.dataset.label = label;
  cell.textContent = text || "—";
  return cell;
}

function chip(text, kind = "") {
  const element = document.createElement("span");
  element.className = `chip ${kind}`.trim();
  element.textContent = text;
  return element;
}

function normalizeCategory(value) {
  if (!value || value === "unknown") return "unclassified";
  return Object.prototype.hasOwnProperty.call(loraCategoryLabels, value)
    ? value
    : "unclassified";
}

function normalizeArchiveState(item) {
  const value = String(item?.archive_state || "");
  if (Object.prototype.hasOwnProperty.call(archiveStateLabels, value)) return value;
  if (value === "archived" || item?.archived) return "searchable";
  if (value === "metadata_only") return "metadata_ready";
  if (item?.from_civitai || item?.civitai_metadata_present) return "metadata_ready";
  return "unarchived";
}

function hasManualOverride(value) {
  if (value === true) return true;
  return Boolean(value && typeof value === "object" && Object.keys(value).length);
}

function valueList(value) {
  if (Array.isArray(value)) return value.filter(Boolean).map(String);
  if (typeof value === "string" && value.trim()) {
    return value.split(/[,，\n]+/).map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function canonicalLoraKey(value) {
  return String(value || "")
    .trim()
    .replaceAll("\\", "/")
    .replace(/\.(?:safetensors|ckpt|pt|pth|bin)$/i, "")
    .replace(/^[ /.]+|[ /.]+$/g, "")
    .toLocaleLowerCase();
}

function loraArchiveCell(item) {
  const cell = document.createElement("td");
  cell.dataset.label = "AI 建档";
  const category = normalizeCategory(item.category);
  const archiveState = normalizeArchiveState(item);
  const stateKind = archiveState === "searchable"
    ? "good"
    : ["stale", "review_needed", "analyzing"].includes(archiveState)
      ? "warning"
      : archiveState === "metadata_ready"
        ? "neutral"
        : "bad";
  const stateChip = chip(archiveStateLabels[archiveState], stateKind);
  stateChip.classList.add("archive-state-chip", `archive-${archiveState}`);
  cell.append(stateChip, document.createElement("br"));
  cell.append(chip(`分类：${loraCategoryLabels[category]}`, category === "unclassified" ? "bad" : "good"));
  if (item.from_civitai || item.civitai_metadata_present) {
    cell.append(document.createTextNode(" "), chip("Civitai", "metadata"));
  }
  if (hasManualOverride(item.manual_override)) {
    cell.append(document.createTextNode(" "), chip("人工修订", "neutral"));
  }
  if (item.classified_at) {
    const time = document.createElement("small");
    time.className = "archive-classified-time";
    const parsed = new Date(item.classified_at);
    time.textContent = Number.isNaN(parsed.getTime())
      ? `归档时间：${item.classified_at}`
      : `归档于 ${parsed.toLocaleString("zh-CN", {hour12: false})}`;
    cell.append(time);
  }
  return cell;
}

function renderLoraArchive(archive) {
  const card = document.querySelector("#lora-archive-card");
  const metrics = document.querySelector("#lora-archive-metrics");
  const works = document.querySelector("#lora-work-list");
  metrics.replaceChildren();
  works.replaceChildren();
  if (!archive) {
    card.hidden = true;
    return;
  }
  const categories = archive.categories || {};
  const functionalCount = [
    "speed_sampling",
    "quality_enhancement",
    "detail_restoration",
    "composition_pose",
    "lighting_color",
    "background_environment",
    "clothing_concept",
  ].reduce((total, category) => total + Number(categories[category] || 0), 0);
  const values = [
    ["角色", categories.character || 0],
    ["画师 / 风格", categories.artist_style || 0],
    ["功能型", functionalCount],
    ["混合", categories.mixed || 0],
    ["未分类", categories.unclassified ?? categories.unknown ?? 0],
    ["Civitai 元信息", archive.civitai_enriched || 0],
    ["已识别角色", archive.identified_characters || 0],
  ];
  for (const [label, value] of values) {
    const metric = document.createElement("div");
    metric.className = "archive-metric";
    const name = document.createElement("span");
    name.textContent = label;
    const count = document.createElement("strong");
    count.textContent = value;
    metric.append(name, count);
    metrics.append(metric);
  }
  for (const work of (archive.works || []).slice(0, 24)) {
    works.append(chip(`${work.name} · ${work.count}`));
  }
  if (!works.childElementCount) works.append(chip("暂无可识别作品", "neutral"));
  const fallbackDigestion = {
    searchable: 0,
    analyzing: 0,
    review_needed: 0,
    stale: 0,
    metadata_ready: 0,
    failed: 0,
    unarchived: 0,
  };
  for (const item of loraItems) fallbackDigestion[normalizeArchiveState(item)] += 1;
  const digestion = archive.analysis || archive.digestion || {
    ...fallbackDigestion,
    total: loraItems.length,
    pending: loraItems.length - fallbackDigestion.searchable,
    percent: fallbackDigestion.searchable * 100 / Math.max(1, loraItems.length),
  };
  const total = Number(digestion.total || 0);
  const searchable = Number(digestion.searchable ?? digestion.archived ?? fallbackDigestion.searchable);
  const reviewNeeded = Number(digestion.review_needed ?? fallbackDigestion.review_needed);
  const metadataReady = Number(digestion.metadata_ready ?? digestion.metadata_only ?? fallbackDigestion.metadata_ready);
  const failedOrMissing = Number(digestion.failed ?? fallbackDigestion.failed)
    + Number(digestion.unarchived ?? fallbackDigestion.unarchived);
  const percent = Math.max(0, Math.min(100, Number(
    digestion.percent ?? searchable * 100 / Math.max(1, total)
  )));
  document.querySelector("#digestion-progress-text").textContent = `${searchable} / ${total}`;
  document.querySelector("#digestion-progress-percent").textContent = `${percent.toFixed(percent % 1 ? 1 : 0)}%`;
  document.querySelector("#digestion-count-archived").textContent = searchable;
  document.querySelector("#digestion-count-review").textContent = reviewNeeded;
  document.querySelector("#digestion-count-metadata").textContent = metadataReady;
  document.querySelector("#digestion-count-unarchived").textContent = failedOrMissing;
  const progress = document.querySelector("#digestion-progress-track");
  progress.value = percent;
  progress.setAttribute("aria-valuenow", String(percent));
  progress.setAttribute("aria-valuetext", `已有 ${searchable} 个可搜索 AI 档案，共 ${total} 个`);
  card.hidden = false;
}

async function loadBootstrap() {
  const data = await api("/api/bootstrap");
  csrfToken = data.csrf_token;
  bootstrapData = data;
  document.querySelector("#service-state").textContent = "在线";
  document.querySelector("#service-state").classList.add("online");
  document.querySelector("#version-label").textContent = `v${data.version}`;
  document.querySelector("#metric-version").textContent = `v${data.version}`;
  document.querySelector("#metric-jobs").textContent = data.active_jobs;
  document.querySelector("#metric-style").textContent =
    data.settings.default_style_preset || "工作流原始风格";
  document.querySelector("#metric-unet").textContent =
    data.settings.unet_model_name || "工作流内置";
  document.querySelector("#detail-comfy").textContent = data.settings.comfyui_url;
  document.querySelector("#detail-lora-manager").textContent =
    data.settings.lora_manager_url || "跟随 ComfyUI 自动发现";
  document.querySelector("#detail-workflow").textContent =
    data.workflow_runtime?.workflow_file || data.settings.workflow_file;
  document.querySelector("#detail-resolution").textContent =
    `${data.settings.default_width} × ${data.settings.default_height}`;
  populateSettings(data.settings);
  renderWorkflowSamplers(data.workflow_runtime || {}, data.settings || {});
  await Promise.all([
    loadProviders(data.settings.prompt_llm_provider_id),
    loadConfigProfiles({quiet: true}),
    loadWorkflows({quiet: true}),
  ]);
}

function formatSamplerValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function renderWorkflowSamplers(runtime, settings) {
  const profileId = String(runtime.profile_id || "").trim();
  const displayName = String(runtime.display_name || runtime.profile_name || "").trim();
  const workflowFile = String(runtime.workflow_file || settings.workflow_file || "").trim();
  const samplers = Array.isArray(runtime.samplers) ? runtime.samplers : [];
  const profileBadge = document.querySelector("#workflow-profile-id");
  const profileName = document.querySelector("#workflow-profile-name");
  const profileFile = document.querySelector("#workflow-profile-file");
  const samplerList = document.querySelector("#workflow-sampler-list");
  const status = document.querySelector("#workflow-sampler-status");
  const override = document.querySelector("#sampler-steps-override");
  if (!profileBadge || !profileName || !profileFile || !samplerList || !status || !override) return;

  profileBadge.textContent = profileId || "LEGACY / 未登记";
  profileName.textContent = displayName || "未提供工作流显示名称";
  profileFile.textContent = workflowFile || "—";
  const configuredOverride = runtime.sampler_steps_override
    ?? settings.sampler_steps_override
    ?? 0;
  override.value = String(Math.min(100, Math.max(0, Number(configuredOverride) || 0)));

  samplerList.replaceChildren();
  if (!samplers.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "当前 bootstrap 尚未提供采样器模板信息。";
    samplerList.append(empty);
    status.textContent = "需要 workflow_runtime.samplers 后才能展示节点参数；保存步数覆盖不受影响。";
    return;
  }

  for (const sampler of samplers) {
    const card = document.createElement("article");
    card.className = "sampler-template-card";
    const head = document.createElement("div");
    head.className = "sampler-template-head";
    const title = document.createElement("strong");
    title.textContent = sampler.label || sampler.title || sampler.name || "Sampler";
    const node = document.createElement("code");
    node.textContent = `NODE ${formatSamplerValue(sampler.node_id)}`;
    head.append(title, node);

    const values = document.createElement("dl");
    for (const [label, value] of [
      ["Steps", sampler.steps],
      ["CFG", sampler.cfg],
      ["Denoise", sampler.denoise],
    ]) {
      const item = document.createElement("div");
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = label;
      description.textContent = formatSamplerValue(value);
      item.append(term, description);
      values.append(item);
    }
    card.append(head, values);
    samplerList.append(card);
  }
  const activeOverride = Number(override.value) || 0;
  status.textContent = activeOverride
    ? `已设置 ${activeOverride} 步覆盖；保存并自动重载后应用到 ${samplers.length} 个采样器。`
    : `当前跟随工作流模板，共读取 ${samplers.length} 个采样器。`;
}

function renderWorkflowSelector(activeWorkflow = "") {
  const select = document.querySelector("#workflow-select");
  const status = document.querySelector("#workflow-select-status");
  const activate = document.querySelector("#workflow-activate");
  if (!select || !status || !activate) return;
  const previous = select.value;
  select.replaceChildren();
  if (!workflowItems.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "没有可选择的 Anima 生图管线";
    select.append(option);
    activate.disabled = true;
    status.textContent = "请检查 base / rtx / iterative 三个专用工作流及其 manifest。";
    return;
  }
  for (const item of workflowItems) {
    const option = document.createElement("option");
    option.value = item.filename;
    option.disabled = !item.selectable;
    option.dataset.reason = item.reason || "";
    const marker = item.current ? "● " : "";
    const profile = item.display_name && item.display_name !== item.filename
      ? ` · ${item.display_name}`
      : "";
    option.textContent = `${marker}${item.filename} · ${item.task_label || item.task_type}${profile}`;
    select.append(option);
  }
  const active = workflowItems.find((item) => item.current)?.filename
    || activeWorkflow
    || previous;
  const selected = workflowItems.find(
    (item) => item.filename === active && item.selectable
  ) || workflowItems.find((item) => item.selectable);
  select.value = selected?.filename || "";
  updateWorkflowSelectionStatus();
}

function renderWorkflowTools() {
  const host = document.querySelector("#workflow-tool-list");
  if (!host) return;
  host.replaceChildren();
  const definitions = {
    standalone_rtx: {
      title: "RTX 独立放大",
      command: "/放大",
      summary: "放大用户提供的图片，不经过 Anima 生图。",
    },
    semantic_redraw: {
      title: "无蒙版整图改图",
      command: "/改图 <要求> --mode preserve|balanced|free",
      summary: "先反推原图并应用语义修改，再通过当前 Anima 管线重新生成整张图。",
    },
    quick: {
      title: "Quick Inpaint",
      command: "/重绘 <要求> --mode quick",
      summary: "适合边界清晰的小范围遮罩修改。",
    },
    lanpaint: {
      title: "LanPaint",
      command: "/重绘 <要求> --mode lanpaint",
      summary: "适合复杂结构、大区域与精细多轮重绘。",
    },
  };
  const profileCapabilities = {
    rtx_upscale: "standalone_rtx",
    anima_inpaint_crop: "quick",
    anima_lanpaint: "lanpaint",
  };
  for (const item of toolWorkflowItems) {
    const capabilityId = item.capability_id
      || profileCapabilities[item.profile_id]
      || item.profile_id
      || item.filename;
    const definition = definitions[capabilityId] || {};
    const card = document.createElement("article");
    card.className = "workflow-tool-card";
    card.dataset.state = item.status || "unavailable";

    const head = document.createElement("div");
    head.className = "workflow-tool-card-head";
    const title = document.createElement("strong");
    title.textContent = definition.title || item.display_name || item.filename;
    const badge = document.createElement("span");
    badge.className = "ticket-tag";
    badge.textContent = item.status === "ready"
      ? "AVAILABLE"
      : (item.status === "disabled" ? "DISABLED" : "UNAVAILABLE");
    head.append(title, badge);

    const summary = document.createElement("p");
    summary.className = "muted";
    summary.textContent = item.summary || definition.summary || "独立图片工具。";
    const metadata = document.createElement("div");
    metadata.className = "workflow-tool-meta";
    const filename = document.createElement("code");
    filename.textContent = item.filename || "—";
    const command = document.createElement("code");
    command.textContent = item.command || definition.command || "—";
    metadata.append(filename, command);

    const note = document.createElement("small");
    note.textContent = item.status === "disabled"
      ? "该能力已在插件设置中关闭；它不会进入普通生图管线。"
      : (item.status === "ready"
        ? "使用右侧指令调用；它不会进入普通生图管线。"
        : "本地工作流未就绪，请查看依赖检查结果；不可切换为普通生图。");
    card.append(head, summary, metadata, note);
    host.append(card);
  }
  if (!toolWorkflowItems.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "未发现整图改图、RTX 独立放大、Quick Inpaint 或 LanPaint 能力。";
    host.append(empty);
  }
}

function updateWorkflowSelectionStatus() {
  const select = document.querySelector("#workflow-select");
  const status = document.querySelector("#workflow-select-status");
  const activate = document.querySelector("#workflow-activate");
  const item = workflowItems.find((entry) => entry.filename === select.value);
  if (!item) {
    activate.disabled = true;
    status.textContent = "请选择一个可用的生图工作流。";
    return;
  }
  activate.disabled = !item.selectable || item.current;
  if (item.current) {
    status.textContent = `当前正在使用 ${item.filename}；清单每次刷新都会重新读取工作流目录。`;
  } else if (!item.selectable) {
    status.textContent = item.reason || "该文件不是可切换的生图工作流。";
  } else {
    status.textContent = `可热切换到 ${item.filename}；只影响之后提交的生图任务。`;
  }
}

async function loadWorkflows({quiet = false} = {}) {
  const status = document.querySelector("#workflow-select-status");
  if (!quiet && status) status.textContent = "正在重新扫描工作流目录…";
  try {
    const data = await api("/api/workflows");
    const allItems = Array.isArray(data.items) ? data.items : [];
    workflowItems = Array.isArray(data.generation_items)
      ? data.generation_items
      : allItems.filter((item) => item.selectable && item.task_type === "text_to_image");
    toolWorkflowItems = Array.isArray(data.tool_items)
      ? data.tool_items
      : allItems.filter((item) => item.task_type === "upscale" || item.task_type === "inpaint");
    renderWorkflowSelector(data.active || "");
    renderWorkflowTools();
  } catch (error) {
    if (status) status.textContent = error.message;
    if (!quiet) showToast(error.message, true);
  }
}

function renderPipelineHealth(data) {
  const host = document.querySelector("#pipeline-health-list");
  if (!host) return;
  host.replaceChildren();
  const labels = {
    base: "Anima 原图",
    rtx: "Anima + RTX",
    iterative: "Anima + 迭代放大",
    standalone_rtx: "RTX 独立放大",
    quick: "Quick 遮罩重绘",
    lanpaint: "LanPaint 精细重绘",
  };
  for (const item of data.items || []) {
    const card = document.createElement("article");
    card.className = "workflow-sampler-card";
    const title = document.createElement("strong");
    title.textContent = labels[item.id] || item.id;
    const status = document.createElement("span");
    status.className = "ticket-tag";
    status.textContent = item.status === "ready" ? "READY" : (item.status === "disabled" ? "DISABLED" : "MISSING");
    const detail = document.createElement("p");
    detail.className = "muted";
    const problems = [
      item.local_error,
      ...(item.missing_node_types || []).map((value) => `缺节点 ${value}`),
      ...(item.missing_models || []).map((value) => `缺模型 ${value}`),
    ].filter(Boolean);
    detail.textContent = item.status === "disabled"
      ? `${item.filename} · 已由配置关闭`
      : (problems.length ? problems.join("；") : `${item.filename} · 节点与模型可用`);
    card.append(title, status, detail);
    host.append(card);
  }
  if (!(data.items || []).length) {
    host.textContent = "没有收到管线检查结果。";
  }
}

async function checkWorkflowDependencies() {
  const button = document.querySelector("#workflow-check");
  setBusy(button, true, "检查中…");
  try {
    const data = await api("/api/workflows/check");
    renderPipelineHealth(data);
    const enabledCount = data.enabled_count ?? data.total_count;
    showToast(`管线检查完成：${data.ready_count}/${enabledCount} 个已启用管线可用`, (data.unavailable_count ?? 0) > 0);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function activateWorkflow() {
  const select = document.querySelector("#workflow-select");
  const button = document.querySelector("#workflow-activate");
  const item = workflowItems.find((entry) => entry.filename === select.value);
  if (!item || !item.selectable || item.current) return;
  if (!(await confirmAction(
    `将当前生图工作流热切换为 ${item.filename}。独立 RTX 放大工作流不会被改动。`,
    {title: "切换生图工作流", confirmLabel: "确认切换"},
  ))) return;
  setBusy(button, true, "正在切换…");
  try {
    const data = await api("/api/workflows/select", {
      method: "POST",
      body: JSON.stringify({identifier: item.filename}),
    });
    showToast(data.message || `已切换到 ${item.filename}`);
    await loadBootstrap();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function loadProviders(selectedOverride = null) {
  const controls = [
    {
      key: "prompt", group: "chat", select: "#provider-select", manual: "#provider-manual",
      note: "#provider-note", empty: "跟随当前会话模型", selected: "selected_prompt",
    },
    {
      key: "reverse", group: "chat", select: "#reverse-provider-select", manual: "#reverse-provider-manual",
      note: "#reverse-provider-note", empty: "自动复用导演/当前会话模型", selected: "selected_reverse", vision: true,
    },
    {
      key: "embedding", group: "embedding", select: "#embedding-provider-select", manual: "#embedding-provider-manual",
      note: "#embedding-provider-note", empty: "停用向量召回", selected: "selected_embedding",
    },
    {
      key: "rerank", group: "rerank", select: "#rerank-provider-select", manual: "#rerank-provider-manual",
      note: "#rerank-provider-note", empty: "停用精排", selected: "selected_rerank",
    },
  ];
  for (const control of controls) {
    document.querySelector(control.note).textContent = "正在读取 AstrBot 已保存模型…";
  }
  try {
    const data = await api("/api/providers");
    const overrides = typeof selectedOverride === "string"
      ? {prompt: selectedOverride}
      : (selectedOverride || {});
    for (const control of controls) {
      const select = document.querySelector(control.select);
      const manual = document.querySelector(control.manual);
      const note = document.querySelector(control.note);
      const group = data[control.group] || {};
      const items = group.items || (control.group === "chat" ? data.items || [] : []);
      const selected = overrides[control.key] ?? data[control.selected] ?? group.selected ?? "";
      select.replaceChildren();
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = control.empty;
      select.append(empty);
      for (const item of items) {
        const option = document.createElement("option");
        option.value = item.id;
        const model = item.model ? ` · ${item.model}` : "";
        const type = item.type ? ` · ${item.type}` : "";
        const state = item.available ? "已加载" : item.enabled ? "未加载" : "已停用";
        const vision = control.vision
          ? item.supports_image === true ? " · 视觉" : item.supports_image === false ? " · 纯文本" : " · 视觉未知"
          : "";
        option.textContent = `${item.name}${model}${type}${vision} · ${state} [${item.id}]`;
        option.disabled = !item.available || (control.vision && item.supports_image === false);
        select.append(option);
      }
      const manualOption = document.createElement("option");
      manualOption.value = "__manual__";
      manualOption.textContent = "手动填写 Provider ID…";
      select.append(manualOption);
      const selectedItem = items.find((item) => item.id === selected);
      const selectedAllowed = selectedItem
        && selectedItem.available
        && (!control.vision || selectedItem.supports_image !== false);
      if (selectedAllowed) {
        select.value = selected;
        manual.hidden = true;
      } else if (selected) {
        select.value = "__manual__";
        manual.value = selected;
        manual.hidden = false;
      } else {
        select.value = "";
        manual.hidden = true;
      }
      const available = items.filter((item) => item.available).length;
      note.textContent = items.length
        ? `已读取 ${items.length} 个已保存 ${control.group} Provider，其中 ${available} 个当前可用`
        : `AstrBot 当前没有可用的 ${control.group} Provider，可手动填写 ID`;
    }
  } catch (error) {
    for (const control of controls) document.querySelector(control.note).textContent = error.message;
    showToast(error.message, true);
  }
}

function populateSettings(settings) {
  const form = document.querySelector("#settings-form");
  for (const [name, value] of Object.entries(settings || {})) {
    const field = form.elements.namedItem(name);
    if (!field) continue;
    if (field.type === "checkbox") {
      field.checked = Boolean(value);
    } else if (Array.isArray(value)) {
      field.value = value.join("\n");
    } else {
      field.value = value ?? "";
    }
  }
  const password = form.elements.namedItem("web_ui_password");
  password.placeholder = settings.web_ui_password_set
    ? "已设置；留空保持不变"
    : "尚未设置；启用前至少填写 8 位";
}

function collectSettings(form) {
  const result = {};
  for (const field of form.elements) {
    if (!field.name || field.type === "submit") continue;
    const providerManual = {
      prompt_llm_provider_id: "#provider-manual",
      reverse_prompt_provider_id: "#reverse-provider-manual",
      lora_embedding_provider_id: "#embedding-provider-manual",
      lora_rerank_provider_id: "#rerank-provider-manual",
    };
    if (providerManual[field.name]) {
      result[field.name] = field.value === "__manual__"
        ? document.querySelector(providerManual[field.name]).value.trim()
        : field.value;
    } else if (booleanFields.has(field.name)) {
      result[field.name] = field.checked;
    } else if (numberFields.has(field.name)) {
      result[field.name] = Number(field.value);
    } else if (field.name === "group_whitelist") {
      result[field.name] = field.value
        .split(/[\n,]+/)
        .map((value) => value.trim())
        .filter(Boolean);
    } else if (field.name === "lora_alias_rules") {
      result[field.name] = field.value
        .split(/\n+/)
        .map((value) => value.trim())
        .filter(Boolean);
    } else if (field.name === "web_ui_password") {
      if (field.value) result[field.name] = field.value;
    } else {
      result[field.name] = field.value;
    }
  }
  return result;
}

async function saveSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const samplerOverride = Number(form.elements.namedItem("sampler_steps_override")?.value ?? 0);
  if (!Number.isInteger(samplerOverride) || samplerOverride < 0 || samplerOverride > 100) {
    showToast("采样步数覆盖必须是 0–100 的整数", true);
    form.elements.namedItem("sampler_steps_override")?.focus();
    return;
  }
  setBusy(button, true, "正在保存…");
  try {
    const data = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(collectSettings(form)),
    });
    document.querySelector("#settings-note").textContent = data.message;
    showToast(data.message);
    if (data.reload_scheduled) {
      await reloadAfterPluginChange();
    }
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function renderConfigProfiles(activeProfile = "") {
  const select = document.querySelector("#config-profile-select");
  const badge = document.querySelector("#profile-active-badge");
  const previous = select.value;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = profileItems.length ? "选择环境档案…" : "尚未保存档案";
  select.append(placeholder);
  for (const item of profileItems) {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = `${item.active ? "● " : ""}${item.name}`;
    select.append(option);
  }
  const resolvedActive = activeProfile || profileItems.find((item) => item.active)?.name || "";
  select.value = profileItems.some((item) => item.name === previous) ? previous : resolvedActive;
  badge.textContent = resolvedActive ? `当前 · ${resolvedActive}` : "未激活档案";
}

async function loadConfigProfiles({quiet = false} = {}) {
  const status = document.querySelector("#profile-status");
  if (!quiet) status.textContent = "正在读取配置档案…";
  try {
    const data = await api("/api/config-profiles");
    profileItems = data.items || [];
    renderConfigProfiles(data.active_profile || "");
    status.textContent = profileItems.length
      ? `已读取 ${profileItems.length} 个环境档案。档案不包含密码、Token、Provider 与提示词。`
      : "尚未保存环境档案。";
  } catch (error) {
    profileItems = [];
    renderConfigProfiles();
    status.textContent = `配置档案接口不可用：${error.message}`;
    if (!quiet) showToast(error.message, true);
  }
}

async function saveConfigProfile() {
  const button = document.querySelector("#profile-save");
  const input = document.querySelector("#config-profile-name");
  const selected = document.querySelector("#config-profile-select").value;
  const name = input.value.trim() || selected;
  if (!name) {
    showToast("请填写新档案名称，或选择一个已有档案进行覆盖。", true);
    input.focus();
    return;
  }
  const exists = profileItems.some((item) => item.name === name);
  if (exists && !(await confirmAction(
    `配置档案“${name}”已存在，确定用当前设置覆盖吗？`,
    {title: "覆盖配置档案", confirmLabel: "确认覆盖"},
  ))) return;
  setBusy(button, true, "正在保存…");
  try {
    const data = await api("/api/config-profiles", {
      method: "POST",
      body: JSON.stringify({name, overwrite: exists, activate: true}),
    });
    input.value = "";
    document.querySelector("#profile-status").textContent = data.message || `已保存档案“${name}”。`;
    showToast(data.message || `已保存档案“${name}”。`);
    await loadConfigProfiles({quiet: true});
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function activateConfigProfile() {
  const select = document.querySelector("#config-profile-select");
  const button = document.querySelector("#profile-activate");
  const name = select.value;
  if (!name) {
    showToast("请先选择要切换的配置档案。", true);
    select.focus();
    return;
  }
  setBusy(button, true, "正在切换…");
  try {
    const data = await api("/api/config-profiles/switch", {
      method: "POST",
      body: JSON.stringify({identifier: name}),
    });
    if (data.settings) populateSettings(data.settings);
    document.querySelector("#profile-status").textContent = data.message || `已切换到“${name}”。`;
    showToast(data.message || `已切换到“${name}”。`);
    if (data.reload_scheduled) {
      await reloadAfterPluginChange();
    } else {
      await loadBootstrap();
    }
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function deleteConfigProfile() {
  const select = document.querySelector("#config-profile-select");
  const button = document.querySelector("#profile-delete");
  const name = select.value;
  if (!name) {
    showToast("请先选择要删除的配置档案。", true);
    return;
  }
  if (!(await confirmAction(
    `确定删除配置档案“${name}”吗？当前插件设置不会被删除。`,
    {title: "删除配置档案", confirmLabel: "确认删除"},
  ))) return;
  setBusy(button, true, "正在删除…");
  try {
    const data = await api(`/api/config-profiles/${encodeURIComponent(name)}`, {method: "DELETE"});
    showToast(data.message || `已删除“${name}”。`);
    await loadConfigProfiles({quiet: true});
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function mergeArchiveIndex(entries) {
  const byName = new Map((entries || []).map((entry) => [canonicalLoraKey(entry.name), entry]));
  loraItems = loraItems.map((item) => {
    const entry = byName.get(canonicalLoraKey(item.name));
    if (!entry) return item;
    const source = entry.source || {};
    const effective = entry.effective || entry.classification || {};
    const semanticState = entry.analysis_status
      || entry.archive_state
      || (effective.category === "unclassified" ? "review_needed" : "searchable");
    return {
      ...item,
      archive_entry: entry,
      category: effective.category || item.category,
      character_name: effective.character_name || effective.character || source.character_name || item.character_name,
      source_work: effective.source_work || effective.work || source.source_work || item.source_work,
      aliases: unique([
        ...valueList(item.aliases),
        ...valueList(source.existing_aliases),
        ...valueList(effective.aliases),
      ]),
      trigger_words: unique([
        ...valueList(item.trigger_words),
        ...valueList(source.trigger_words),
        ...valueList(effective.trigger_words),
      ]),
      tags: unique([...valueList(item.tags), ...valueList(source.tags)]),
      model_name: source.civitai_model_name || item.model_name,
      model_description: source.civitai_model_or_version_description || item.model_description || item.description,
      civitai_metadata_present: Boolean(source.civitai_metadata_present || item.from_civitai),
      manual_override: entry.manual_override,
      archived: semanticState === "searchable",
      archive_state: semanticState,
      classified_at: entry.classified_at || "",
    };
  });
}

function hydrateEmbeddedArchive(item) {
  const effective = item.archive && typeof item.archive === "object" ? item.archive : {};
  return {
    ...item,
    category: effective.category || item.category,
    character_name: effective.character_name || effective.character || item.character_name,
    source_work: effective.source_work || effective.work || item.source_work,
    aliases: unique([...valueList(item.aliases), ...valueList(effective.aliases)]),
    trigger_words: unique([
      ...valueList(item.trigger_words),
      ...valueList(effective.trigger_words),
    ]),
    model_description: item.model_description || item.description,
    manual_override: effective.manual_override || item.manual_override,
    archive_state: normalizeArchiveState(item),
  };
}

async function loadLoraArchiveIndex() {
  try {
    const data = await api("/api/loras/archive");
    mergeArchiveIndex(data.items || data.entries || []);
    return data;
  } catch (_error) {
    // v1.8 catalog fields remain usable while the richer LLM archive endpoint is unavailable.
    return null;
  }
}

function visibleLoras() {
  return loraItems.filter((item) => (
    (loraFilter === "all" || normalizeCategory(item.category) === loraFilter)
    && (loraArchiveFilter === "all" || normalizeArchiveState(item) === loraArchiveFilter)
  ));
}

function updateFilterCounts() {
  const counts = Object.fromEntries(
    Object.keys(filterCountIds).map((category) => [category, 0])
  );
  const archiveCounts = {
    all: 0,
    searchable: 0,
    analyzing: 0,
    review_needed: 0,
    stale: 0,
    metadata_ready: 0,
    failed: 0,
    unarchived: 0,
  };
  for (const item of loraItems) {
    const category = normalizeCategory(item.category);
    const state = normalizeArchiveState(item);
    if (loraArchiveFilter === "all" || state === loraArchiveFilter) {
      counts.all += 1;
      counts[category] += 1;
    }
    if (loraFilter === "all" || category === loraFilter) {
      archiveCounts.all += 1;
      archiveCounts[state] += 1;
    }
  }
  for (const [category, id] of Object.entries(filterCountIds)) {
    document.querySelector(`#${id}`).textContent = counts[category] || 0;
  }
  for (const [state, id] of Object.entries(archiveFilterCountIds)) {
    document.querySelector(`#${id}`).textContent = archiveCounts[state] || 0;
  }
}

function updateSelectionUI() {
  const currentNames = new Set(loraItems.map((item) => item.name));
  for (const name of [...selectedLoras]) {
    if (!currentNames.has(name)) selectedLoras.delete(name);
  }
  const visible = visibleLoras();
  const selectedVisible = visible.filter((item) => selectedLoras.has(item.name)).length;
  const selectedHidden = selectedLoras.size - selectedVisible;
  const allCheckbox = document.querySelector("#lora-select-all");
  allCheckbox.checked = Boolean(visible.length && selectedVisible === visible.length);
  allCheckbox.indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
  allCheckbox.disabled = visible.length === 0;
  document.querySelector("#lora-selection-count").textContent = selectedHidden > 0
    ? `已选 ${selectedLoras.size}（当前可见 ${selectedVisible}，隐藏 ${selectedHidden}）`
    : `已选 ${selectedLoras.size}（当前可见 ${selectedVisible}）`;
  document.querySelector("#lora-select-visible").textContent = `全选当前 ${visible.length} 项`;
  document.querySelector("#metadata-selected").disabled = selectedLoras.size === 0;
  document.querySelector("#archive-selected").disabled = selectedLoras.size === 0 || archiveRunInFlight;
  document.querySelector("#archive-selected-inline").disabled = selectedLoras.size === 0 || archiveRunInFlight;
}

function appendMetadataDetails(cell, item) {
  const description = item.model_description || item.description || "";
  const tags = valueList(item.tags);
  if (!description && !tags.length) return;
  const details = document.createElement("details");
  details.className = "metadata-detail";
  const summary = document.createElement("summary");
  summary.textContent = "查看完整模型说明与标签";
  const text = document.createElement("p");
  text.textContent = [description, tags.length ? `标签：${tags.join(", ")}` : ""].filter(Boolean).join("\n\n");
  details.append(summary, text);
  cell.append(details);
}

function detailBlock(title, rows, {wide = false} = {}) {
  const block = document.createElement("article");
  block.className = `lora-detail-block${wide ? " wide" : ""}`;
  const heading = document.createElement("h3");
  heading.textContent = title;
  const list = document.createElement("dl");
  for (const [label, rawValue] of rows) {
    const value = Array.isArray(rawValue)
      ? rawValue.join("、")
      : rawValue && typeof rawValue === "object"
        ? JSON.stringify(rawValue, null, 2)
        : String(rawValue ?? "");
    if (!value || value === "{}" || value === "[]") continue;
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    if (value.includes("\n") || value.length > 180) {
      const pre = document.createElement("pre");
      pre.textContent = value;
      description.append(pre);
    } else {
      description.textContent = value;
    }
    list.append(term, description);
  }
  if (!list.children.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "当前来源没有提供此部分资料。";
    block.append(heading, empty);
  } else {
    block.append(heading, list);
  }
  return block;
}

function fillLoraReviewForm(detail) {
  const form = document.querySelector("#lora-semantic-form");
  const semantic = detail.semantic || {};
  form.elements.name.value = detail.name;
  form.elements.category.value = semantic.category || detail.category || "unclassified";
  form.elements.character_names.value = valueList(semantic.character_names || detail.character_name).join("\n");
  form.elements.source_works.value = valueList(semantic.source_works || detail.source_work).join("\n");
  form.elements.artist_style_names.value = valueList(semantic.artist_style_names).join("\n");
  form.elements.aliases.value = valueList(semantic.aliases || detail.aliases).join("\n");
}

function renderLoraDetail(detail) {
  const content = document.querySelector("#lora-detail-content");
  document.querySelector("#lora-detail-title").textContent = detail.model_name || detail.file_name || "LoRA 资料档案";
  document.querySelector("#lora-detail-name").textContent = detail.name;
  const health = detail.metadata_health || {};
  document.querySelector("#lora-detail-status").textContent =
    `实时资料健康状态：${health.status || "unknown"} · AI 建档：${archiveStateLabels[detail.analysis_status] || detail.analysis_status || "未建档"}`;
  content.replaceChildren(
    detailBlock("身份与版本", [
      ["模型名", detail.model_name], ["版本名", detail.version_name], ["基础模型", detail.base_model],
      ["模型类型", detail.model_type], ["子类型", detail.sub_type], ["目录", detail.folder],
    ]),
    detailBlock("语义与触发", [
      ["当前分类", detail.semantic?.category || detail.category], ["角色名", detail.semantic?.character_names || detail.character_name],
      ["作品", detail.semantic?.source_works || detail.source_work], ["画师 / 风格", detail.semantic?.artist_style_names],
      ["别名", detail.semantic?.aliases || detail.aliases], ["完整触发词", detail.trigger_words], ["标签", detail.tags],
    ]),
    detailBlock("Civitai 作者与许可", [
      ["作者", [detail.creator?.display_name, detail.creator?.username].filter(Boolean)], ["作者主页", detail.creator?.profile_url],
      ["许可", detail.license],
    ]),
    detailBlock("文件与元数据健康", [
      ["文件状态", detail.file_status], ["可用来源", health.available_sources], ["缺失来源", health.missing_sources],
      ["错误来源", health.error_sources], ["过期来源", health.stale_sources], ["字段来源", detail.provenance],
    ]),
    detailBlock("完整模型说明", [
      ["模型说明", detail.descriptions?.model], ["版本说明", detail.descriptions?.version], ["本地备注", detail.descriptions?.local_notes],
    ], {wide: true}),
    detailBlock("使用建议与示例参数", [
      ["使用建议", detail.usage_tips], ["示例图参数", detail.example_images], ["Civitai 版本状态", detail.version_status],
    ], {wide: true}),
  );
  fillLoraReviewForm(detail);
}

async function openLoraDetail(item, button = null) {
  const dialog = document.querySelector("#lora-detail-dialog");
  currentLoraDetailName = item.name;
  document.querySelector("#lora-detail-title").textContent = "正在刷新 LoRA 资料…";
  document.querySelector("#lora-detail-name").textContent = item.name;
  document.querySelector("#lora-detail-content").replaceChildren();
  document.querySelector("#lora-detail-status").textContent = "正在强制刷新 Manager 与 ComfyUI 可加载清单，并聚合完整元数据…";
  if (!dialog.open) dialog.showModal();
  if (button) setBusy(button, true, "读取中…");
  try {
    const detail = await api(`/api/loras/detail?name=${encodeURIComponent(item.name)}`);
    if (currentLoraDetailName === item.name) renderLoraDetail(detail);
  } catch (error) {
    document.querySelector("#lora-detail-status").textContent = `详情读取失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    if (button) setBusy(button, false);
  }
}

async function saveLoraSemantic(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = document.querySelector("#lora-semantic-save");
  const payload = Object.fromEntries(new FormData(form).entries());
  setBusy(button, true, "保存中…");
  try {
    const data = await api("/api/loras/semantic", {method: "PUT", body: JSON.stringify(payload)});
    showToast(data.message || "人工审核已保存");
    document.querySelector("#lora-detail-status").textContent = data.message || "人工审核已保存，人工事实优先于 AI 推断。";
    await searchLoras(null, {skipAutoArchive: true});
    const refreshed = loraItems.find((item) => item.name === payload.name);
    if (refreshed) await openLoraDetail(refreshed);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function renderLoraTable() {
  const table = document.querySelector("#lora-table");
  const empty = document.querySelector("#lora-empty");
  const items = visibleLoras();
  table.replaceChildren();
  updateFilterCounts();

  for (const item of items) {
    const row = document.createElement("tr");
    row.classList.toggle("selected", selectedLoras.has(item.name));
    row.dataset.archiveState = normalizeArchiveState(item);

    const selectCell = document.createElement("td");
    selectCell.className = "check-column";
    selectCell.dataset.label = "选择";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selectedLoras.has(item.name);
    checkbox.setAttribute("aria-label", `选择 ${item.name}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedLoras.add(item.name);
      else selectedLoras.delete(item.name);
      row.classList.toggle("selected", checkbox.checked);
      updateSelectionUI();
    });
    selectCell.append(checkbox);

    const nameCell = textCell(item.name, "lora-name", "文件名");
    const identity = [
      item.character_name ? `角色：${item.character_name}` : "",
      item.source_work ? `作品：${item.source_work}` : "",
    ].filter(Boolean).join("\n");
    const aliases = valueList(item.aliases);
    const triggers = valueList(item.trigger_words);
    const searchable = [
      aliases.length ? `别名：${aliases.join(", ")}` : "",
      triggers.length ? `触发词：${triggers.join(", ")}` : "",
    ].filter(Boolean).join("\n");
    const metadataCell = textCell(item.model_name || item.name, "multiline", "Civitai 信息");
    appendMetadataDetails(metadataCell, item);

    const action = document.createElement("td");
    action.dataset.label = "动作";
    const actionWrap = document.createElement("div");
    actionWrap.className = "lora-actions";
    const metadataButton = document.createElement("button");
    metadataButton.className = "secondary compact";
    metadataButton.type = "button";
    metadataButton.textContent = "获取元数据";
    metadataButton.title = "立即调用 LoRA Manager 的“从 Civitai 获取元数据”";
    metadataButton.addEventListener("click", () => fetchLoraMetadata([item.name], {button: metadataButton}));
    const detailButton = document.createElement("button");
    detailButton.className = "secondary compact";
    detailButton.type = "button";
    detailButton.textContent = "完整档案";
    detailButton.title = "刷新实时清单后读取完整 Civitai / Manager 资料与语义来源";
    detailButton.addEventListener("click", () => openLoraDetail(item, detailButton));
    const archiveButton = document.createElement("button");
    archiveButton.className = "ghost compact";
    archiveButton.type = "button";
    const archiveState = normalizeArchiveState(item);
    archiveButton.textContent = {
      searchable: "重新建档",
      analyzing: "建档进行中",
      review_needed: "重新建档",
      stale: "更新档案",
      metadata_ready: "AI 建档",
      failed: "重试建档",
      unarchived: "获取资料并建档",
    }[archiveState] || "AI 建档";
    archiveButton.disabled = archiveState === "analyzing";
    archiveButton.title = archiveState === "stale"
      ? "此 LoRA 的源资料已经变化，建议重新执行 AI 建档"
      : "让绘图导演完整阅读此 LoRA 的元数据，建立带证据的可搜索档案";
    archiveButton.addEventListener("click", () => runLoraArchive("selected", {names: [item.name], button: archiveButton}));
    const deleteButton = document.createElement("button");
    deleteButton.className = "danger compact";
    deleteButton.type = "button";
    deleteButton.textContent = "删除文件";
    deleteButton.title = "从最新 LoRA Manager 清单精确解析文件后删除；不会接收浏览器路径";
    deleteButton.addEventListener("click", () => deleteLoraAsset(item.name, deleteButton));
    actionWrap.append(detailButton, metadataButton, archiveButton, deleteButton);
    action.append(actionWrap);

    row.append(
      selectCell,
      nameCell,
      loraArchiveCell(item),
      textCell(identity, "multiline", "角色 / 作品"),
      metadataCell,
      textCell(searchable, "multiline", "别名 / 触发词"),
      action,
    );
    table.append(row);
  }
  empty.hidden = items.length > 0;
  empty.textContent = items.length
    ? ""
    : loraItems.length
      ? "当前分类与 AI 建档状态组合下没有 LoRA。"
      : "最新清单中没有匹配项。";
  updateSelectionUI();
}

async function searchLoras(event, {skipAutoArchive = false} = {}) {
  if (event) event.preventDefault();
  const query = document.querySelector("#lora-query").value.trim();
  const table = document.querySelector("#lora-table");
  const empty = document.querySelector("#lora-empty");
  empty.textContent = "正在强制刷新 LoRA Manager 并读取最新目录…";
  empty.hidden = false;
  table.replaceChildren();
  try {
    const data = await api(`/api/loras?q=${encodeURIComponent(query)}&limit=200`);
    loraItems = (data.items || []).map(hydrateEmbeddedArchive);
    let archiveSnapshot = null;
    const hasEmbeddedStatus = Boolean(
      data.archive && Object.prototype.hasOwnProperty.call(data.archive, "status")
    );
    if (!hasEmbeddedStatus) {
      archiveSnapshot = await loadLoraArchiveIndex();
    }
    const searchableCount = data.archive?.analysis?.searchable
      ?? data.archive?.digestion?.archived
      ?? loraItems.filter((item) => normalizeArchiveState(item) === "searchable").length;
    document.querySelector("#lora-summary").textContent =
      `最新可加载 ${data.catalog_total} 个，匹配 ${data.total} 个，当前显示 ${loraItems.length} 个；`
      + `AI 档案可搜索 ${searchableCount} 个。`;
    renderLoraArchive(data.archive);
    renderLoraTable();
    await loadLoraArchiveStatus({
      allowAutoArchive: !skipAutoArchive,
      snapshot: archiveSnapshot,
      statusOverride: hasEmbeddedStatus ? data.archive.status : undefined,
    });
  } catch (error) {
    loraItems = [];
    renderLoraTable();
    empty.hidden = false;
    empty.textContent = error.message;
    showToast(error.message, true);
  }
}

async function refreshLoras() {
  const button = document.querySelector("#lora-refresh");
  setBusy(button, true, "正在刷新…");
  try {
    const data = await api("/api/loras/refresh", {method: "POST"});
    showToast(data.message);
    await searchLoras(null);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function changeCount(status) {
  const explicit = [status.added, status.modified, status.removed]
    .reduce((total, value) => total + (Array.isArray(value) ? value.length : Number(value) || 0), 0);
  if (explicit) return explicit;
  if (Array.isArray(status.pending)) return status.pending.length;
  return Number.isFinite(Number(status.pending)) ? Number(status.pending) : 0;
}

function archivePendingNames(status) {
  const extract = (value) => Array.isArray(value)
    ? value.map((item) => typeof item === "string" ? item : item?.name).filter(Boolean)
    : [];
  const actionable = unique([...extract(status.added), ...extract(status.modified)]);
  if (actionable.length) return actionable;
  return extract(status.pending).filter((name) => loraItems.some((item) => item.name === name));
}

function applyArchiveChangeStatus(status) {
  const names = (value) => new Set(
    (Array.isArray(value) ? value : [])
      .map((item) => typeof item === "string" ? item : item?.name)
      .filter(Boolean)
  );
  const added = names(status?.added);
  const modified = names(status?.modified);
  loraItems = loraItems.map((item) => {
    if (modified.has(item.name)) return {...item, archive_state: "stale"};
    if (added.has(item.name)) {
      return {
        ...item,
        archive_state: (item.from_civitai || item.civitai_metadata_present)
          ? "metadata_ready"
          : "unarchived",
      };
    }
    return item;
  });
}

function renderLoraChangeStatus(status) {
  const seal = document.querySelector("#lora-change-badge");
  const runStatus = document.querySelector("#lora-archive-run-status");
  const changed = Boolean(status?.changed);
  const pending = status ? changeCount(status) : 0;
  seal.classList.toggle("changed", changed);
  seal.classList.toggle("clean", !changed);
  seal.classList.remove("idle");
  seal.querySelector("strong").textContent = changed ? `有 ${pending} 项变化` : "索引已同步";
  document.querySelector("#archive-changed").disabled = !changed || archiveRunInFlight;
  if (!archiveRunInFlight) {
    runStatus.textContent = changed
      ? `检测到库变化：新增 ${Array.isArray(status.added) ? status.added.length : status.added || 0}，修改 ${Array.isArray(status.modified) ? status.modified.length : status.modified || 0}，移除 ${Array.isArray(status.removed) ? status.removed.length : status.removed || 0}。`
      : `LoRA 库与归档索引一致，共 ${status.current_count ?? loraItems.length} 项。`;
  }
}

async function loadLoraArchiveStatus({
  allowAutoArchive = false,
  snapshot = null,
  statusOverride = undefined,
} = {}) {
  const runStatus = document.querySelector("#lora-archive-run-status");
  try {
    let data = snapshot;
    let status = statusOverride;
    if (statusOverride === undefined) {
      data = data || await api("/api/loras/archive");
      status = data.status || data;
    }
    if (!status) throw new Error("服务未返回 LoRA 归档变化状态");
    loraArchiveStatus = status;
    if (data && !snapshot) {
      mergeArchiveIndex(data.items || data.entries || []);
    }
    applyArchiveChangeStatus(status);
    renderLoraTable();
    renderLoraChangeStatus(status);
    const autoToggle = document.querySelector("#archive-auto-toggle");
    const autoKey = status.fingerprint ? `comfy-anima-auto-archive:${status.fingerprint}` : "";
    if (
      allowAutoArchive &&
      status.changed &&
      autoToggle.checked &&
      autoKey &&
      readSessionPreference(autoKey) !== "started" &&
      !archiveRunInFlight
    ) {
      writeSessionPreference(autoKey, "started");
      await runLoraArchive("changed", {automatic: true});
    }
  } catch (error) {
    loraArchiveStatus = null;
    const seal = document.querySelector("#lora-change-badge");
    seal.className = "change-seal idle";
    seal.querySelector("strong").textContent = "检测不可用";
    runStatus.textContent = `AI 建档接口不可用：${error.message}`;
  }
}

async function fetchLoraMetadata(names = [], {button = null, quiet = false, refresh = true} = {}) {
  const status = document.querySelector("#lora-archive-run-status");
  const normalizedNames = unique(names);
  if (button) setBusy(button, true, "获取中…");
  status.textContent = "Starting metadata fetch... 正在从 Civitai 获取 LoRA 元数据。";
  try {
    const data = await api("/api/lora/metadata-fetch", {
      method: "POST",
      body: JSON.stringify({
        all: normalizedNames.length === 0,
        names: normalizedNames,
      }),
    });
    const message = data.message || `元数据获取完成：${data.succeeded ?? data.processed ?? normalizedNames.length} 项。`;
    status.textContent = message;
    if (!quiet) showToast(message);
    if (refresh) await searchLoras(null, {skipAutoArchive: true});
    return data;
  } catch (error) {
    status.textContent = `元数据获取失败：${error.message}`;
    if (!quiet) showToast(error.message, true);
    throw error;
  } finally {
    if (button) setBusy(button, false);
  }
}

function selectedLoraNames() {
  return [...selectedLoras];
}

function renderArchiveRunResult(data) {
  const box = document.querySelector("#lora-archive-result");
  box.replaceChildren();
  const title = document.createElement("h3");
  title.textContent = data.synced
    ? "目录删除记录已同步"
    : data.skipped
      ? "AI 档案无需更新"
      : "AI 建档完成";
  const summary = document.createElement("p");
  summary.textContent = data.synced
    ? `已确认移除 ${valueList(data.removed_names).length} 个旧索引项，本次没有调用 LLM。`
    : data.skipped
      ? "库指纹未变化，已跳过重复思考。"
      : `已为 ${data.selected_count ?? 0} 个 LoRA 执行 AI 建档，分 ${data.batch_count ?? 0} 批完成。`;
  box.append(title, summary);
  const updated = valueList(data.updated_names);
  if (updated.length) {
    const list = document.createElement("ul");
    for (const name of updated.slice(0, 30)) {
      const item = document.createElement("li");
      item.textContent = name;
      list.append(item);
    }
    if (updated.length > 30) {
      const more = document.createElement("li");
      more.textContent = `另有 ${updated.length - 30} 项…`;
      list.append(more);
    }
    box.append(list);
  }
  box.hidden = false;
}

async function runLoraArchive(mode, {names = null, button = null, automatic = false} = {}) {
  if (archiveRunInFlight) return;
  let requestedNames = names ? unique(names) : [];
  if (mode === "selected" && !requestedNames.length) requestedNames = selectedLoraNames();
  if (mode === "changed" && !requestedNames.length && loraArchiveStatus) {
    requestedNames = archivePendingNames(loraArchiveStatus);
  }
  if (mode === "selected" && !requestedNames.length) {
    showToast("请先选择至少一个 LoRA。", true);
    return;
  }

  archiveRunInFlight = true;
  if (button) setBusy(button, true, "AI 建档中…");
  for (const control of document.querySelectorAll("#archive-changed, #archive-selected, #archive-selected-inline, #archive-all")) {
    control.disabled = true;
  }
  const runStatus = document.querySelector("#lora-archive-run-status");
  runStatus.textContent = automatic
    ? "检测到库变化，正在自动准备 AI 建档…"
    : "正在准备完整触发词、模型说明与 Civitai 元信息…";

  try {
    const fetchFirst = document.querySelector("#archive-fetch-first").checked;
    const onlyRemoved = mode === "changed" && requestedNames.length === 0;
    if (fetchFirst && !onlyRemoved) {
      const coversWholeLibrary = requestedNames.length > 0 && requestedNames.length >= loraItems.length;
      await fetchLoraMetadata(mode === "all" || coversWholeLibrary ? [] : requestedNames, {quiet: true, refresh: false});
    }
    runStatus.textContent = onlyRemoved
      ? "当前仅有文件删除变化，正在同步目录索引，不调用 LLM…"
      : "绘图导演正在阅读 LoRA 资料并生成带证据的 AI 档案…";
    const requestMode = requestedNames.length ? "selected" : "all";
    const data = await api("/api/lora/archive", {
      method: "POST",
      body: JSON.stringify({
        all: requestMode === "all",
        names: requestedNames,
        skip_when_unchanged: mode === "changed",
        sync_only: onlyRemoved,
      }),
    });
    if (data.run_id) {
      const queuedMessage = data.message || `AI 建档任务已排队：${data.run_id}`;
      runStatus.textContent = queuedMessage;
      showToast(queuedMessage);
      await openTaskCenter(data.run_id);
      return;
    }
    renderArchiveRunResult(data);
    const message = data.synced
      ? data.message
      : data.skipped
      ? "LoRA 库没有需要重复建档的变化。"
      : `AI 建档完成，更新 ${valueList(data.updated_names).length || data.selected_count || 0} 项。`;
    runStatus.textContent = message;
    showToast(message);
    if (data.status) loraArchiveStatus = data.status;
    await searchLoras(null, {skipAutoArchive: true});
  } catch (error) {
    runStatus.textContent = `AI 建档失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    archiveRunInFlight = false;
    if (button) setBusy(button, false);
    updateSelectionUI();
    if (loraArchiveStatus) renderLoraChangeStatus(loraArchiveStatus);
  }
}

async function downloadLora(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  const status = document.querySelector("#download-status");
  setBusy(button, true, "正在下载…");
  status.textContent = "正在下载；完成后会获取 Civitai 元数据并再次刷新…";
  try {
    const data = await api("/api/loras/download", {
      method: "POST",
      body: JSON.stringify({url: document.querySelector("#lora-download-url").value}),
    });
    status.textContent = data.message;
    showToast(data.message);
    await searchLoras(null);
  } catch (error) {
    status.textContent = error.message;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function loadPresets() {
  const table = document.querySelector("#preset-table");
  const empty = document.querySelector("#preset-empty");
  table.replaceChildren();
  empty.hidden = false;
  empty.textContent = "正在强制刷新并校验所有组合…";
  try {
    const data = await api("/api/presets");
    for (const item of data.items || []) {
      const row = document.createElement("tr");
      const statusCell = document.createElement("td");
      statusCell.append(chip(item.available ? (item.enabled ? "可用" : "已停用") : "含失效 LoRA", item.available ? "good" : "bad"));
      if (item.error) {
        const detail = document.createElement("div");
        detail.className = "muted";
        detail.textContent = item.error;
        statusCell.append(detail);
      }
      const action = document.createElement("td");
      const deleteButton = document.createElement("button");
      deleteButton.className = "danger compact";
      deleteButton.type = "button";
      deleteButton.textContent = "删除";
      deleteButton.addEventListener("click", () => deletePreset(item.name));
      action.append(deleteButton);
      row.append(
        textCell(item.name),
        textCell(item.category_label),
        textCell((item.loras || []).join("\n"), "multiline"),
        statusCell,
        action,
      );
      table.append(row);
    }
    empty.hidden = (data.items || []).length > 0;
    empty.textContent = data.items?.length ? "" : "尚未保存任何组合。";
  } catch (error) {
    empty.textContent = error.message;
    showToast(error.message, true);
  }
}

async function savePreset(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  setBusy(button, true, "正在保存…");
  const values = new FormData(form);
  const payload = {
    name: values.get("name"),
    category: values.get("category"),
    loras: String(values.get("loras") || "").split("\n").map((item) => item.trim()).filter(Boolean),
    trigger_words: values.get("trigger_words"),
    description: values.get("description"),
    enabled: form.elements.namedItem("enabled").checked,
  };
  try {
    const data = await api("/api/presets", {method: "POST", body: JSON.stringify(payload)});
    showToast(data.message);
    await loadPresets();
    if (data.reload_scheduled) await reloadAfterPluginChange();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function deletePreset(identifier) {
  if (!(await confirmAction(
    `确定删除组合“${identifier}”吗？`,
    {title: "删除 LoRA 组合", confirmLabel: "确认删除"},
  ))) return;
  try {
    const data = await api(`/api/presets/${encodeURIComponent(identifier)}`, {method: "DELETE"});
    showToast(data.message);
    await loadPresets();
    if (data.reload_scheduled) await reloadAfterPluginChange();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function loadModels() {
  const grid = document.querySelector("#model-grid");
  const empty = document.querySelector("#model-empty");
  grid.replaceChildren();
  empty.hidden = false;
  empty.textContent = "正在读取最新 UNETLoader 清单…";
  try {
    const data = await api("/api/unet");
    for (const item of data.items || []) {
      const card = document.createElement("article");
      card.className = `model-card${item.current ? " current" : ""}`;
      const name = document.createElement("div");
      name.className = "model-name";
      name.textContent = `${item.index}. ${item.name}`;
      const state = item.current ? chip("当前模型", "good") : chip("可切换", "neutral");
      const actions = document.createElement("div");
      actions.className = "model-actions";
      const button = document.createElement("button");
      button.className = item.current ? "ghost" : "secondary";
      button.textContent = item.current ? "正在使用" : "切换到此模型";
      button.disabled = item.current;
      button.addEventListener("click", () => selectModel(item.name));
      const deleteButton = document.createElement("button");
      deleteButton.className = "danger";
      deleteButton.type = "button";
      deleteButton.textContent = item.current ? "当前模型不可删除" : "删除模型文件";
      deleteButton.disabled = item.current;
      deleteButton.addEventListener("click", () => deleteUnetAsset(item.name, deleteButton));
      actions.append(button, deleteButton);
      card.append(name, state, actions);
      grid.append(card);
    }
    empty.hidden = (data.items || []).length > 0;
    empty.textContent = data.items?.length ? "" : "最新清单为空。";
  } catch (error) {
    empty.textContent = error.message;
    showToast(error.message, true);
  }
}

async function confirmedAssetName(exactName, label) {
  const approved = await confirmAction(
    `危险操作：将永久删除 ${label} 文件。\n请在下方输入完整精确名称：\n${exactName}`,
    {
      title: `永久删除 ${label}`,
      confirmLabel: "永久删除",
      expectedValue: exactName,
      inputLabel: "完整精确名称",
    },
  );
  return approved ? exactName : "";
}

async function deleteLoraAsset(exactName, button) {
  const confirmName = await confirmedAssetName(exactName, "LoRA");
  if (!confirmName) return;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "删除中…";
  const requestDelete = (removeFromPresets) => api("/api/loras/delete", {
    method: "POST",
    body: JSON.stringify({
      exact_name: exactName,
      confirm_name: confirmName,
      remove_from_presets: removeFromPresets,
    }),
  });
  try {
    let data;
    try {
      data = await requestDelete(false);
    } catch (error) {
      if (!String(error.message || "").includes("预设引用")) throw error;
      const approved = await confirmAction(
        `${error.message}\n\n是否同时从所有 LoRA 组合中移除该文件后继续删除？空组合会一并删除。`,
        {title: "LoRA 正被组合引用", confirmLabel: "移除引用并删除"},
      );
      if (!approved) return;
      data = await requestDelete(true);
    }
    selectedLoras.delete(exactName);
    showToast(data.message || `已删除 ${exactName}`);
    await searchLoras(null, {skipAutoArchive: true});
    await loadPresets();
    if (data.reload_scheduled) await reloadAfterPluginChange();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function deleteUnetAsset(exactName, button) {
  const confirmName = await confirmedAssetName(exactName, "UNET");
  if (!confirmName) return;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "删除中…";
  try {
    const data = await api("/api/unet/delete", {
      method: "POST",
      body: JSON.stringify({exact_name: exactName, confirm_name: confirmName}),
    });
    showToast(data.message || `已删除 ${exactName}`);
    await loadModels();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function selectModel(identifier) {
  try {
    const data = await api("/api/unet/select", {
      method: "POST",
      body: JSON.stringify({identifier}),
    });
    showToast(data.message);
    if (data.reload_scheduled) await reloadAfterPluginChange();
    else await loadModels();
  } catch (error) {
    showToast(error.message, true);
  }
}

function taskTypeLabel(value) {
  return taskTypeLabels[value] || String(value || "后台任务").replaceAll("_", " ");
}

function taskStatusLabel(value) {
  return taskStatusLabels[value] || String(value || "未知状态");
}

function taskTimestamp(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number" || /^\d+(?:\.\d+)?$/.test(String(value))) {
    const date = new Date(Number(value) * 1000);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatTaskTime(value, {includeDate = true} = {}) {
  const date = taskTimestamp(value);
  if (!date) return "—";
  return includeDate
    ? date.toLocaleString("zh-CN", {hour12: false})
    : date.toLocaleTimeString("zh-CN", {hour12: false});
}

function taskDurationSeconds(task) {
  const start = taskTimestamp(task.started_at || task.created_at);
  const end = taskTimestamp(task.ended_at) || new Date();
  if (!start) return 0;
  return Math.max(0, Math.floor((end.getTime() - start.getTime()) / 1000));
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  if (hours) return `${hours}时 ${minutes}分 ${remainder}秒`;
  if (minutes) return `${minutes}分 ${remainder}秒`;
  return `${remainder}秒`;
}

function taskProgress(task) {
  const total = Math.max(0, Number(task.total_items) || 0);
  const completed = Math.max(0, Number(task.completed_items) || 0);
  const failed = Math.max(0, Number(task.failed_items) || 0);
  const processed = Math.min(total || completed + failed, completed + failed);
  if (total > 0) return Math.max(0, Math.min(100, processed * 100 / total));
  if (task.status === "succeeded") return 100;
  return 0;
}

function latestTaskPhase(task) {
  const event = taskLatestEvents.get(task.run_id);
  if (event?.phase) return String(event.phase).replaceAll("_", " ");
  if (task.status === "queued") return "等待执行";
  if (task.status === "running") return "正在运行";
  return taskStatusLabel(task.status);
}

function taskStatusClass(status) {
  if (status === "succeeded") return "succeeded";
  if (status === "running" || status === "queued") return "active";
  if (status === "partial" || status === "interrupted" || status === "cancelled") return "warning";
  return "failed";
}

function stopTaskPolling() {
  if (taskPollTimer !== null) {
    clearTimeout(taskPollTimer);
    taskPollTimer = null;
  }
}

function scheduleTaskPoll(delay = 1800) {
  stopTaskPolling();
  if (currentPanel !== "tasks") return;
  taskPollTimer = setTimeout(() => loadTasks({quiet: true}), delay);
}

function updateTaskMetrics() {
  const count = (statuses) => taskItems.filter((task) => statuses.includes(task.status)).length;
  document.querySelector("#task-count-active").textContent = count(["queued", "running"]);
  document.querySelector("#task-count-succeeded").textContent = count(["succeeded"]);
  document.querySelector("#task-count-warning").textContent = count(["partial", "cancelled", "interrupted"]);
  document.querySelector("#task-count-failed").textContent = count(["failed", "timed_out"]);
  document.querySelector("#task-visible-count").textContent = `${taskItems.length} 项`;
}

function renderTaskList() {
  const list = document.querySelector("#task-list");
  const empty = document.querySelector("#task-list-empty");
  const fragment = document.createDocumentFragment();
  for (const task of taskItems) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `task-list-item status-${taskStatusClass(task.status)}`;
    item.classList.toggle("selected", task.run_id === selectedTaskId);
    item.setAttribute("role", "listitem");
    item.addEventListener("click", () => selectTask(task.run_id));

    const heading = document.createElement("span");
    heading.className = "task-list-item-head";
    const type = document.createElement("strong");
    type.textContent = taskTypeLabel(task.task_type);
    const status = document.createElement("span");
    status.className = `task-status-badge status-${taskStatusClass(task.status)}`;
    status.textContent = taskStatusLabel(task.status);
    heading.append(type, status);

    const phase = document.createElement("span");
    phase.className = "task-list-phase";
    phase.textContent = `当前阶段 · ${latestTaskPhase(task)}`;

    const progress = document.createElement("span");
    progress.className = "task-list-progress";
    const fill = document.createElement("i");
    fill.style.width = `${taskProgress(task)}%`;
    progress.append(fill);

    const footer = document.createElement("span");
    footer.className = "task-list-item-foot";
    footer.textContent = `${formatTaskTime(task.created_at)} · 成功 ${task.completed_items || 0} / 失败 ${task.failed_items || 0}`;
    item.append(heading, phase, progress, footer);
    fragment.append(item);
  }
  list.replaceChildren(fragment);
  empty.hidden = taskItems.length > 0;
  updateTaskMetrics();
}

async function hydrateActiveTaskPhases() {
  const active = taskItems.filter((task) => activeTaskStatuses.has(task.status)).slice(0, 8);
  await Promise.all(active.map(async (task) => {
    try {
      const data = await api(`/api/tasks/${encodeURIComponent(task.run_id)}/events?after=0&limit=2000`);
      const latest = (data.entries || []).at(-1);
      if (latest) taskLatestEvents.set(task.run_id, latest);
    } catch (_error) {
      // The task list remains useful even if a single event stream was pruned.
    }
  }));
}

async function loadTasks({quiet = false, preferredRunId = ""} = {}) {
  if (taskLoading) return;
  taskLoading = true;
  const statusLine = document.querySelector("#task-list-status");
  if (!quiet) statusLine.textContent = "正在读取持久任务记录…";
  try {
    const type = document.querySelector("#task-type-filter").value;
    const status = document.querySelector("#task-status-filter").value;
    const params = new URLSearchParams({limit: "80"});
    if (type) params.set("type", type);
    if (status) params.set("status", status);
    const data = await api(`/api/tasks?${params}`);
    taskItems = data.items || [];
    await hydrateActiveTaskPhases();
    if (preferredRunId) selectedTaskId = preferredRunId;
    if (!selectedTaskId && taskItems.length) {
      selectedTaskId = (taskItems.find((task) => activeTaskStatuses.has(task.status)) || taskItems[0]).run_id;
    }
    renderTaskList();
    statusLine.textContent = `最近刷新 ${new Date().toLocaleTimeString("zh-CN", {hour12: false})} · 持久记录 ${taskItems.length} 项`;
    if (selectedTaskId) await loadTaskDetail(selectedTaskId);
  } catch (error) {
    statusLine.textContent = `任务读取失败：${error.message}`;
    if (!quiet) showToast(error.message, true);
  } finally {
    taskLoading = false;
    scheduleTaskPoll();
  }
}

async function selectTask(runId) {
  const changed = selectedTaskId !== runId;
  selectedTaskId = runId;
  if (changed) {
    selectedTask = null;
    taskEvents = [];
    taskEventCursor = 0;
    taskEventPage = 1;
  }
  renderTaskList();
  await loadTaskDetail(runId, {reset: changed});
}

function taskMetric(label, value) {
  const metric = document.createElement("div");
  const name = document.createElement("span");
  name.textContent = label;
  const content = document.createElement("strong");
  content.textContent = value;
  metric.append(name, content);
  return metric;
}

function renderTaskDetail() {
  const empty = document.querySelector("#task-detail-empty");
  const detail = document.querySelector("#task-detail");
  if (!selectedTask) {
    empty.hidden = false;
    detail.hidden = true;
    return;
  }
  empty.hidden = true;
  detail.hidden = false;
  document.querySelector("#task-detail-title").textContent = taskTypeLabel(selectedTask.task_type);
  document.querySelector("#task-detail-id").textContent = selectedTask.run_id;
  const status = document.querySelector("#task-detail-status");
  status.className = `task-status-badge status-${taskStatusClass(selectedTask.status)}`;
  status.textContent = taskStatusLabel(selectedTask.status);
  const cancel = document.querySelector("#task-cancel");
  cancel.hidden = !activeTaskStatuses.has(selectedTask.status);

  const latest = taskLatestEvents.get(selectedTask.run_id) || taskEvents.at(-1);
  const metrics = document.querySelector("#task-detail-metrics");
  metrics.replaceChildren(
    taskMetric("当前阶段", latest?.phase ? String(latest.phase).replaceAll("_", " ") : latestTaskPhase(selectedTask)),
    taskMetric("运行耗时", formatDuration(taskDurationSeconds(selectedTask))),
    taskMetric("成功项目", String(selectedTask.completed_items || 0)),
    taskMetric("失败项目", String(selectedTask.failed_items || 0)),
  );
  if (selectedTask.error_summary) {
    const error = document.createElement("p");
    error.className = "task-error-banner";
    error.textContent = selectedTask.error_summary;
    metrics.append(error);
  }

  const percent = taskProgress(selectedTask);
  const total = Number(selectedTask.total_items || 0);
  const completed = Number(selectedTask.completed_items || 0);
  const failed = Number(selectedTask.failed_items || 0);
  document.querySelector("#task-progress-label").textContent = total
    ? `已处理 ${Math.min(total, completed + failed)} / ${total}`
    : latest?.message || "等待任务上报项目进度";
  document.querySelector("#task-progress-value").textContent = `${percent.toFixed(percent % 1 ? 1 : 0)}%`;
  const progress = document.querySelector("#task-progress-track");
  progress.value = percent;
  progress.setAttribute("aria-valuetext", `任务进度 ${percent.toFixed(1)}%`);
}

function renderTaskEvents() {
  const list = document.querySelector("#task-event-list");
  const empty = document.querySelector("#task-event-empty");
  const fragment = document.createDocumentFragment();
  const ordered = [...taskEvents].sort((left, right) => (
    taskEventOrder === "asc" ? left.seq - right.seq : right.seq - left.seq
  ));
  const totalPages = Math.max(1, Math.ceil(ordered.length / taskEventPageSize));
  taskEventPage = Math.max(1, Math.min(totalPages, taskEventPage));
  const pageStart = (taskEventPage - 1) * taskEventPageSize;
  const visibleEvents = ordered.slice(pageStart, pageStart + taskEventPageSize);
  for (const event of visibleEvents) {
    const item = document.createElement("li");
    item.className = `task-event level-${String(event.level || "INFO").toLowerCase()}`;
    const rail = document.createElement("div");
    rail.className = "task-event-rail";
    const seq = document.createElement("code");
    seq.textContent = `#${event.seq}`;
    const time = document.createElement("time");
    time.textContent = formatTaskTime(event.timestamp, {includeDate: false});
    rail.append(seq, time);
    const body = document.createElement("div");
    body.className = "task-event-body";
    const heading = document.createElement("div");
    heading.className = "task-event-heading";
    const phase = document.createElement("strong");
    phase.textContent = String(event.phase || "event").replaceAll("_", " ");
    const meta = document.createElement("span");
    const bits = [];
    if (event.item_name) bits.push(event.item_name);
    if (event.batch_index !== null && event.batch_index !== undefined) bits.push(`批次 ${event.batch_index}/${event.batch_total || "?"}`);
    if (event.duration_ms !== null && event.duration_ms !== undefined) bits.push(`${event.duration_ms}ms`);
    meta.textContent = bits.join(" · ");
    heading.append(phase, meta);
    const message = document.createElement("p");
    message.textContent = event.message || event.event_code || "阶段事件";
    body.append(heading, message);
    item.append(rail, body);
    fragment.append(item);
  }
  list.replaceChildren(fragment);
  empty.hidden = taskEvents.length > 0;
  document.querySelector("#task-event-cursor").textContent = `SEQ ${taskEventCursor}`;
  document.querySelector("#task-event-page").textContent = `${taskEventPage} / ${totalPages}`;
  document.querySelector("#task-event-prev").disabled = taskEventPage <= 1;
  document.querySelector("#task-event-next").disabled = taskEventPage >= totalPages;
}

function changeTaskEventPage(direction) {
  taskEventPage = Math.max(1, taskEventPage + direction);
  renderTaskEvents();
}

async function loadTaskDetail(runId, {reset = false} = {}) {
  if (!runId || taskDetailLoading) return;
  taskDetailLoading = true;
  if (reset) {
    taskEvents = [];
    taskEventCursor = 0;
    taskEventPage = 1;
  }
  try {
    const [task, eventData] = await Promise.all([
      api(`/api/tasks/${encodeURIComponent(runId)}`),
      api(`/api/tasks/${encodeURIComponent(runId)}/events?after=${taskEventCursor}&limit=1000`),
    ]);
    if (selectedTaskId !== runId) return;
    selectedTask = task;
    const known = new Set(taskEvents.map((event) => event.seq));
    const incoming = (eventData.entries || []).filter((event) => !known.has(event.seq));
    taskEvents.push(...incoming);
    taskEvents.sort((left, right) => left.seq - right.seq);
    taskEventCursor = Number(eventData.cursor || taskEventCursor);
    const latest = taskEvents.at(-1);
    if (latest) taskLatestEvents.set(runId, latest);
    const listIndex = taskItems.findIndex((item) => item.run_id === runId);
    if (listIndex >= 0) taskItems[listIndex] = task;
    renderTaskList();
    renderTaskDetail();
    renderTaskEvents();
  } catch (error) {
    document.querySelector("#task-list-status").textContent = `任务详情读取失败：${error.message}`;
  } finally {
    taskDetailLoading = false;
  }
}

async function cancelSelectedTask() {
  if (!selectedTask || !activeTaskStatuses.has(selectedTask.status)) return;
  if (!(await confirmAction(
    `确定取消任务 ${selectedTask.run_id} 吗？`,
    {title: "取消后台任务", confirmLabel: "确认取消"},
  ))) return;
  const button = document.querySelector("#task-cancel");
  setBusy(button, true, "取消中…");
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(selectedTask.run_id)}/cancel`, {method: "POST"});
    showToast(data.message || "已请求取消任务");
    await loadTaskDetail(selectedTask.run_id);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function openTaskCenter(runId) {
  selectedTaskId = String(runId || "");
  selectedTask = null;
  taskEvents = [];
  taskEventCursor = 0;
  taskEventPage = 1;
  switchPanel("tasks");
  await loadTasks({quiet: true, preferredRunId: selectedTaskId});
}

async function restoreActiveLoraTask() {
  if (activeTaskRestoreChecked) return;
  activeTaskRestoreChecked = true;
  try {
    const data = await api("/api/tasks?limit=30");
    const active = (data.items || []).find((task) => (
      activeTaskStatuses.has(task.status)
      && String(task.task_type || "").toLocaleLowerCase().includes("lora")
    ));
    if (!active) return;
    showToast(`已恢复正在进行的 ${taskTypeLabel(active.task_type)}。`);
    await openTaskCenter(active.run_id);
  } catch (_error) {
    // Older backends without task APIs remain compatible with the existing UI.
  }
}

function stopConsolePolling() {
  if (consolePollTimer !== null) {
    clearTimeout(consolePollTimer);
    consolePollTimer = null;
  }
}

function scheduleConsolePoll(delay = 1200) {
  stopConsolePolling();
  if (currentPanel !== "console" || consolePaused) return;
  consolePollTimer = setTimeout(() => loadConsoleLogs({quiet: true}), delay);
}

function consoleLogTime(entry) {
  const date = new Date(Number(entry.timestamp || 0) * 1000);
  if (Number.isNaN(date.getTime())) return String(entry.time || "—");
  const clock = date.toLocaleTimeString("zh-CN", {hour12: false});
  return `${clock}.${String(date.getMilliseconds()).padStart(3, "0")}`;
}

function filteredConsoleEntries() {
  const query = document.querySelector("#console-query").value.trim().toLocaleLowerCase();
  const level = document.querySelector("#console-level-filter").value;
  const category = document.querySelector("#console-category-filter").value;
  return consoleEntries.filter((entry) => {
    const levelMatch = level === "all"
      || entry.level === level
      || (level === "ERROR" && entry.level === "CRITICAL");
    const categoryMatch = category === "all" || entry.category === category;
    if (!levelMatch || !categoryMatch) return false;
    if (!query) return true;
    return [
      entry.level,
      entry.category,
      consoleCategoryLabels[entry.category] || "",
      entry.source,
      entry.message,
    ].join(" ").toLocaleLowerCase().includes(query);
  });
}

function renderConsoleLogs({follow = false} = {}) {
  const list = document.querySelector("#console-list");
  const empty = document.querySelector("#console-empty");
  const viewport = document.querySelector("#console-viewport");
  const visible = filteredConsoleEntries();
  const fragment = document.createDocumentFragment();
  for (const entry of visible) {
    const item = document.createElement("li");
    item.className = `console-entry level-${String(entry.level || "INFO").toLowerCase()}`;

    const rail = document.createElement("div");
    rail.className = "console-entry-rail";
    const time = document.createElement("time");
    time.dateTime = entry.time || "";
    time.textContent = consoleLogTime(entry);
    const level = document.createElement("span");
    level.className = "console-level";
    level.textContent = entry.level || "INFO";
    const category = document.createElement("span");
    category.className = "console-category";
    category.textContent = consoleCategoryLabels[entry.category] || "插件";
    rail.append(time, level, category);

    const body = document.createElement("div");
    body.className = "console-entry-body";
    const source = document.createElement("span");
    source.className = "console-source";
    source.textContent = `${entry.source || "plugin"}:${entry.line || 0}`;
    const message = document.createElement("pre");
    message.textContent = entry.message || "";
    body.append(source, message);
    item.append(rail, body);
    fragment.append(item);
  }
  list.replaceChildren(fragment);
  empty.hidden = visible.length > 0;
  document.querySelector("#console-visible-count").textContent = `显示 ${visible.length} 条`;
  if (follow && document.querySelector("#console-follow").checked) {
    requestAnimationFrame(() => {
      viewport.scrollTop = viewport.scrollHeight;
    });
  }
}

function updateConsoleMeta(data) {
  consoleMeta = data;
  const counts = data.counts || {};
  document.querySelector("#console-count-total").textContent = data.buffer_size || 0;
  document.querySelector("#console-count-info").textContent = counts.INFO || 0;
  document.querySelector("#console-count-warning").textContent = counts.WARNING || 0;
  document.querySelector("#console-count-error").textContent =
    (counts.ERROR || 0) + (counts.CRITICAL || 0);
  document.querySelector("#console-capacity-label").textContent =
    `持久保留最近 ${data.capacity || 1000} 条`;

  const seal = document.querySelector("#console-live-seal");
  const label = document.querySelector("#console-live-label");
  seal.classList.toggle("live", !consolePaused && data.attached !== false);
  seal.classList.toggle("paused", consolePaused);
  label.textContent = consolePaused
    ? "已暂停"
    : data.attached === false
      ? "捕获器未连接"
      : "自动刷新";

  const now = new Date().toLocaleTimeString("zh-CN", {hour12: false});
  const evicted = data.evicted ? ` · 已滚动淘汰 ${data.evicted} 条` : "";
  const clipped = data.gap
    ? ` · 检测到日志缺口，约错过 ${data.missed || 0} 条`
    : data.truncated
      ? " · 本次仅取最近记录"
      : "";
  document.querySelector("#console-status").textContent = consolePaused
    ? `刷新已暂停 · 持久视图 ${data.buffer_size || 0}/${data.capacity || 1000}${evicted}`
    : `最近刷新 ${now} · 持久视图 ${data.buffer_size || 0}/${data.capacity || 1000}${evicted}${clipped}`;
}

async function loadConsoleLogs({reset = false, quiet = false} = {}) {
  if (consoleLoading) return;
  consoleLoading = true;
  if (reset) {
    consoleEntries = [];
    consoleCursor = 0;
    consoleClearMarker = null;
    consoleStreamId = "";
  }
  try {
    let data = await api(`/api/logs?after=${consoleCursor}&limit=1000`);
    const streamChanged = Boolean(
      consoleStreamId && data.stream_id && data.stream_id !== consoleStreamId
    );
    if (streamChanged) {
      consoleEntries = [];
      consoleCursor = 0;
      consoleClearMarker = null;
      if (!data.stream_reset) data = await api("/api/logs?after=0&limit=1000");
    }
    consoleStreamId = data.stream_id || consoleStreamId;
    if (consoleClearMarker !== null && data.cleared !== consoleClearMarker) {
      consoleEntries = [];
    }
    consoleClearMarker = data.cleared ?? consoleClearMarker ?? 0;
    const known = new Set(consoleEntries.map((entry) => entry.id));
    const incoming = (data.entries || []).filter((entry) => !known.has(entry.id));
    consoleEntries.push(...incoming);
    consoleEntries.sort((left, right) => left.id - right.id);
    if (consoleEntries.length > (data.capacity || 1000)) {
      consoleEntries = consoleEntries.slice(-(data.capacity || 1000));
    }
    consoleCursor = Number(data.cursor || consoleCursor);
    updateConsoleMeta(data);
    renderConsoleLogs({follow: incoming.length > 0});
  } catch (error) {
    document.querySelector("#console-status").textContent = `日志读取失败：${error.message}`;
    if (!quiet) showToast(error.message, true);
  } finally {
    consoleLoading = false;
    scheduleConsolePoll();
  }
}

function setConsolePaused(paused) {
  consolePaused = Boolean(paused);
  const button = document.querySelector("#console-pause");
  button.textContent = consolePaused ? "继续刷新" : "暂停刷新";
  if (consoleMeta) updateConsoleMeta(consoleMeta);
  if (consolePaused) stopConsolePolling();
  else scheduleConsolePoll(0);
}

async function copyVisibleConsoleLogs() {
  const visible = filteredConsoleEntries();
  if (!visible.length) return showToast("当前筛选下没有可复制的日志。", true);
  const text = visible.map((entry) => (
    `[${entry.time || consoleLogTime(entry)}] [${entry.level}] `
    + `[${consoleCategoryLabels[entry.category] || "插件"}] `
    + `[${entry.source || "plugin"}:${entry.line || 0}] ${entry.message || ""}`
  )).join("\n");
  try {
    await navigator.clipboard.writeText(text);
  } catch (_error) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
  showToast(`已复制 ${visible.length} 条脱敏日志。`);
}

async function clearConsoleLogs() {
  if (!(await confirmAction(
    "清空本插件专属持久日志视图？AstrBot 文件日志和任务事件不会被删除。",
    {title: "清空控制台视图", confirmLabel: "确认清空"},
  ))) return;
  const button = document.querySelector("#console-clear");
  setBusy(button, true, "正在清空…");
  try {
    const data = await api("/api/logs", {method: "DELETE"});
    consoleEntries = [];
    consoleCursor = Number(data.cursor || consoleCursor);
    renderConsoleLogs();
    await loadConsoleLogs({quiet: true});
    showToast(data.message || "插件控制台持久视图已清空");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function loadCurrentPanel() {
  if (currentPanel === "overview") await loadBootstrap();
  else if (currentPanel === "settings") await Promise.all([loadBootstrap(), loadConfigProfiles({quiet: true})]);
  else if (currentPanel === "loras") await searchLoras(null);
  else if (currentPanel === "presets") await loadPresets();
  else if (currentPanel === "models") await loadModels();
  else if (currentPanel === "tasks") await loadTasks();
  else if (currentPanel === "console") await loadConsoleLogs({reset: true});
}

function switchPanel(name) {
  currentPanel = name;
  for (const button of document.querySelectorAll(".nav-item")) {
    const active = button.dataset.panel === name;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const panel of document.querySelectorAll(".panel")) {
    panel.classList.toggle("active", panel.id === `panel-${name}`);
  }
  document.querySelector("#page-title").textContent = panelTitles[name];
  window.scrollTo({top: 0, behavior: "smooth"});
  if (name === "settings") loadConfigProfiles({quiet: true});
  if (name === "loras") searchLoras(null);
  if (name === "presets") loadPresets();
  if (name === "models") loadModels();
  if (name === "tasks") loadTasks();
  else stopTaskPolling();
  if (name === "console") loadConsoleLogs({reset: consoleEntries.length === 0});
  else stopConsolePolling();
}

async function logout() {
  if (pluginPageBridge()) {
    showToast("原生插件页使用 AstrBot Dashboard 登录状态，请从主界面退出。", true);
    return;
  }
  try {
    await api("/api/logout", {method: "POST"});
  } finally {
    window.location.replace("/login");
  }
}

function initializeArchivePreferences() {
  const auto = document.querySelector("#archive-auto-toggle");
  const fetchFirst = document.querySelector("#archive-fetch-first");
  auto.checked = readPreference("comfy-anima-auto-archive", "false") === "true";
  fetchFirst.checked = readPreference("comfy-anima-archive-fetch-first", "true") !== "false";
  auto.addEventListener("change", () => writePreference("comfy-anima-auto-archive", auto.checked));
  fetchFirst.addEventListener("change", () => writePreference("comfy-anima-archive-fetch-first", fetchFirst.checked));
}

document.querySelector("#nav").addEventListener("click", (event) => {
  const button = event.target.closest(".nav-item");
  if (button) switchPanel(button.dataset.panel);
});
document.querySelector("#settings-form").addEventListener("submit", saveSettings);
document.querySelector("#workflow-refresh").addEventListener("click", () => loadWorkflows());
document.querySelector("#workflow-check").addEventListener("click", checkWorkflowDependencies);
document.querySelector("#workflow-activate").addEventListener("click", activateWorkflow);
document.querySelector("#workflow-select").addEventListener("change", updateWorkflowSelectionStatus);
document.querySelector("#sampler-steps-override").addEventListener("input", (event) => {
  const value = Number(event.target.value);
  const samplerCount = bootstrapData?.workflow_runtime?.samplers?.length || 0;
  const status = document.querySelector("#workflow-sampler-status");
  if (!Number.isInteger(value) || value < 0 || value > 100) {
    status.textContent = "请输入 0–100 的整数；0 表示跟随工作流模板。";
  } else if (value === 0) {
    status.textContent = `将跟随工作流模板，共 ${samplerCount} 个采样器。`;
  } else {
    status.textContent = `保存并自动重载后，将以 ${value} 步覆盖 ${samplerCount} 个采样器。`;
  }
});
document.querySelector("#provider-refresh").addEventListener("click", () => {
  const current = {};
  for (const [key, selectId, manualId] of [
    ["prompt", "#provider-select", "#provider-manual"],
    ["reverse", "#reverse-provider-select", "#reverse-provider-manual"],
    ["embedding", "#embedding-provider-select", "#embedding-provider-manual"],
    ["rerank", "#rerank-provider-select", "#rerank-provider-manual"],
  ]) {
    const select = document.querySelector(selectId);
    current[key] = select.value === "__manual__"
      ? document.querySelector(manualId).value.trim()
      : select.value;
  }
  loadProviders(current);
});
for (const [selectId, manualId] of [
  ["#provider-select", "#provider-manual"],
  ["#reverse-provider-select", "#reverse-provider-manual"],
  ["#embedding-provider-select", "#embedding-provider-manual"],
  ["#rerank-provider-select", "#rerank-provider-manual"],
]) {
  document.querySelector(selectId).addEventListener("change", (event) => {
    document.querySelector(manualId).hidden = event.target.value !== "__manual__";
  });
}
document.querySelector("#profile-save").addEventListener("click", saveConfigProfile);
document.querySelector("#profile-activate").addEventListener("click", activateConfigProfile);
document.querySelector("#profile-delete").addEventListener("click", deleteConfigProfile);
document.querySelector("#config-profile-select").addEventListener("change", (event) => {
  const item = profileItems.find((profile) => profile.name === event.target.value);
  document.querySelector("#profile-status").textContent = item
    ? `${item.active ? "当前档案。" : "可切换。"} 更新于 ${item.updated_at || "未知时间"}。`
    : "";
});
document.querySelector("#lora-search-form").addEventListener("submit", searchLoras);
document.querySelector("#lora-refresh").addEventListener("click", refreshLoras);
document.querySelector("#lora-download-form").addEventListener("submit", downloadLora);
document.querySelector("#lora-category-filters").addEventListener("click", (event) => {
  const button = event.target.closest(".filter-tab");
  if (!button) return;
  loraFilter = button.dataset.category;
  for (const item of document.querySelectorAll("#lora-category-filters .filter-tab")) {
    const active = item === button;
    item.classList.toggle("active", active);
    item.setAttribute("aria-pressed", String(active));
  }
  renderLoraTable();
});
document.querySelector("#lora-archive-state-filters").addEventListener("click", (event) => {
  const button = event.target.closest(".filter-tab");
  if (!button) return;
  loraArchiveFilter = button.dataset.archiveState;
  for (const item of document.querySelectorAll("#lora-archive-state-filters .filter-tab")) {
    const active = item === button;
    item.classList.toggle("active", active);
    item.setAttribute("aria-pressed", String(active));
  }
  renderLoraTable();
});
document.querySelector("#lora-select-visible").addEventListener("click", () => {
  for (const item of visibleLoras()) selectedLoras.add(item.name);
  renderLoraTable();
});
document.querySelector("#lora-clear-selection").addEventListener("click", () => {
  selectedLoras.clear();
  renderLoraTable();
});
document.querySelector("#lora-select-all").addEventListener("change", (event) => {
  for (const item of visibleLoras()) {
    if (event.target.checked) selectedLoras.add(item.name);
    else selectedLoras.delete(item.name);
  }
  renderLoraTable();
});
document.querySelector("#metadata-selected").addEventListener("click", (event) => {
  const names = selectedLoraNames();
  if (!names.length) return showToast("请先选择至少一个 LoRA。", true);
  fetchLoraMetadata(names, {button: event.currentTarget});
});
document.querySelector("#metadata-all").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (await confirmAction(
    "确定调用 LoRA Manager 为全库获取 Civitai 元数据吗？该操作可能需要较长时间。",
    {title: "获取全库元数据", confirmLabel: "开始获取", danger: false},
  )) {
    await fetchLoraMetadata([], {button});
  }
});
document.querySelector("#archive-changed").addEventListener("click", (event) => runLoraArchive("changed", {button: event.currentTarget}));
document.querySelector("#archive-selected").addEventListener("click", (event) => runLoraArchive("selected", {button: event.currentTarget}));
document.querySelector("#archive-selected-inline").addEventListener("click", (event) => runLoraArchive("selected", {button: event.currentTarget}));
document.querySelector("#archive-all").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (await confirmAction(
    "确定让绘图导演为当前全部 LoRA 重新执行 AI 建档吗？这可能产生多次模型调用。",
    {title: "全库 AI 建档", confirmLabel: "开始建档", danger: false},
  )) {
    await runLoraArchive("all", {button});
  }
});
document.querySelector("#lora-detail-close").addEventListener("click", () => {
  currentLoraDetailName = "";
  document.querySelector("#lora-detail-dialog").close();
});
document.querySelector("#lora-detail-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) {
    currentLoraDetailName = "";
    event.currentTarget.close();
  }
});
document.querySelector("#lora-semantic-form").addEventListener("submit", saveLoraSemantic);
document.querySelector("#lora-detail-reanalyze").addEventListener("click", (event) => {
  if (!currentLoraDetailName) return;
  document.querySelector("#lora-detail-dialog").close();
  runLoraArchive("selected", {names: [currentLoraDetailName], button: event.currentTarget});
});
document.querySelector("#preset-form").addEventListener("submit", savePreset);
document.querySelector("#preset-refresh").addEventListener("click", loadPresets);
document.querySelector("#model-refresh").addEventListener("click", loadModels);
document.querySelector("#task-refresh").addEventListener("click", () => loadTasks());
document.querySelector("#task-type-filter").addEventListener("change", () => {
  selectedTaskId = "";
  loadTasks();
});
document.querySelector("#task-status-filter").addEventListener("change", () => {
  selectedTaskId = "";
  loadTasks();
});
document.querySelector("#task-cancel").addEventListener("click", cancelSelectedTask);
document.querySelector("#task-event-order").addEventListener("change", (event) => {
  taskEventOrder = event.target.value === "asc" ? "asc" : "desc";
  taskEventPage = 1;
  renderTaskEvents();
});
document.querySelector("#task-event-page-size").addEventListener("change", (event) => {
  taskEventPageSize = [10, 20, 50, 100, 200].includes(Number(event.target.value))
    ? Number(event.target.value)
    : 20;
  taskEventPage = 1;
  renderTaskEvents();
});
document.querySelector("#task-event-prev").addEventListener("click", () => changeTaskEventPage(-1));
document.querySelector("#task-event-next").addEventListener("click", () => changeTaskEventPage(1));
document.querySelector("#console-query").addEventListener("input", () => renderConsoleLogs());
document.querySelector("#console-level-filter").addEventListener("change", () => renderConsoleLogs());
document.querySelector("#console-category-filter").addEventListener("change", () => renderConsoleLogs());
document.querySelector("#console-follow").addEventListener("change", (event) => {
  if (event.target.checked) {
    const viewport = document.querySelector("#console-viewport");
    viewport.scrollTop = viewport.scrollHeight;
  }
});
document.querySelector("#console-viewport").addEventListener("scroll", (event) => {
  const viewport = event.currentTarget;
  const distance = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
  if (distance > 80) document.querySelector("#console-follow").checked = false;
});
document.querySelector("#console-pause").addEventListener("click", () => setConsolePaused(!consolePaused));
document.querySelector("#console-copy").addEventListener("click", copyVisibleConsoleLogs);
document.querySelector("#console-clear").addEventListener("click", clearConsoleLogs);
document.querySelector("#reload-data").addEventListener("click", loadCurrentPanel);
document.querySelector("#logout-button").addEventListener("click", logout);
window.addEventListener("beforeunload", () => {
  stopConsolePolling();
  stopTaskPolling();
});

if (pluginPageBridge()) {
  document.documentElement.dataset.host = "astrbot-plugin-page";
  document.querySelector("#logout-button").hidden = true;
}

initializeArchivePreferences();
initializeThemePicker();
updateSelectionUI();
loadBootstrap()
  .then(() => restoreActiveLoraTask())
  .catch((error) => showToast(error.message, true));
