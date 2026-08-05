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
let promptStatusData = null;
let promptIndexTaskRunId = "";
let experimentalProfileItems = [];
let promptActiveTab = "composer";
let promptAssetItems = [];
let promptAssetPage = 1;
let promptAssetPages = 1;
let promptAssetFingerprint = "";
let promptLabBatch = null;
let promptLabSelection = "";
let promptLabUseComposerBase = true;
let promptPlanItems = [];
let presetItems = [];
let loraViewMode = "table";
let loraGalleryItems = [];
let loraGalleryPage = 1;
let loraGalleryPages = 1;
let loraGalleryFingerprint = "";
let loraPreviewObserver = null;
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
  prompt: "提示词工坊",
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
  generation: "图片生成",
  lora_semantic_analysis: "LoRA 语义建档",
  lora_archive: "LoRA AI 建档",
  lora_metadata: "LoRA 元数据",
  lora_metadata_fetch: "LoRA 元数据",
  lora_download: "LoRA 下载",
  lora_refresh: "LoRA 刷新",
  asset_delete: "资产删除",
  reverse_prompt: "图片反推",
  reverse_draw: "反推画图",
  control_generation: "底图控制",
  character_swap: "语义换角",
  semantic_redraw: "整图语义重绘",
  rtx_upscale: "RTX 放大",
  inpaint: "遮罩局部重绘",
  danbooru_index_update: "Danbooru 索引更新",
  prompt_diagnostic: "提示词诊断",
  prompt_asset_import: "视觉素材导入",
  prompt_asset_remote_import: "视觉素材远程更新",
  prompt_asset_local_sync: "本地素材同步",
  prompt_lab_generate: "Prompt Lab 候选",
  lora_visual_warmup: "LoRA 缩略图预热",
};

const activeTaskStatuses = new Set(["queued", "running"]);

const numberFields = new Set([
  "default_width",
  "default_height",
  "max_concurrent_jobs",
  "max_queued_jobs_per_user",
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
  "prompt_diagnostics_capacity",
  "danbooru_index_timeout",
  "danbooru_index_max_size_mb",
  "danbooru_api_general_min_posts",
  "danbooru_api_meta_min_posts",
  "danbooru_api_page_size",
  "danbooru_api_request_interval_ms",
  "danbooru_api_timeout",
  "danbooru_api_max_records",
  "danbooru_auto_update_interval_hours",
]);

const booleanFields = new Set([
  "enable_upscale",
  "enable_inpaint",
  "send_generation_notice",
  "show_chat_generation_details",
  "enable_prompt_llm",
  "enable_natural_draw",
  "enable_llm_pic_trigger",
  "enable_chat_draw_terminal_guard",
  "enable_prompt_composer_v2",
  "enable_prompt_diagnostics",
  "prompt_diagnostics_include_content",
  "danbooru_api_include_aliases",
  "danbooru_auto_update_enabled",
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
    control: {
      title: "Anima 底图控制",
      command: "/底图控制 <要求> [--m p|d|l|r]",
      summary: "一张底图可控制 Pose、Depth、Lineart 或 Reference，并支持组合。",
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
    anima_control: "control",
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
    empty.textContent = "未发现底图控制、整图改图、RTX 独立放大、Quick Inpaint 或 LanPaint 能力。";
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

function identityBindingLines(value) {
  if (!Array.isArray(value)) return [];
  return value.map((binding) => {
    const activation = valueList(binding?.activation_terms).join(", ");
    return [binding?.character_canonical || "", binding?.copyright_canonical || "", activation].join(" | ");
  });
}

function fillLoraReviewForm(detail) {
  const form = document.querySelector("#lora-semantic-form");
  const semantic = detail.semantic || {};
  form.elements.name.value = detail.name;
  form.elements.category.value = semantic.category || detail.category || "unclassified";
  form.elements.character_names.value = valueList(semantic.character_names || detail.character_name).join("\n");
  form.elements.source_works.value = valueList(semantic.source_works || detail.source_work).join("\n");
  form.elements.activation_terms.value = valueList(semantic.activation_terms).join("\n");
  form.elements.identity_bindings.value = identityBindingLines(semantic.identity_bindings).join("\n");
  form.elements.artist_style_names.value = valueList(semantic.artist_style_names).join("\n");
  form.elements.aliases.value = valueList(semantic.aliases || detail.aliases).join("\n");
}

function renderLoraDetail(detail) {
  const content = document.querySelector("#lora-detail-content");
  document.querySelector("#lora-detail-title").textContent = detail.model_name || detail.file_name || "LoRA 资料档案";
  document.querySelector("#lora-detail-name").textContent = detail.name;
  const health = detail.metadata_health || {};
  document.querySelector("#lora-detail-status").textContent =
    `实时资料健康状态：${health.status || "unknown"} · AI 建档：${archiveStateLabels[detail.analysis_status] || detail.analysis_status || "未建档"} · exact 身份：${detail.semantic?.identity_bindings?.length ? `已绑定 ${detail.semantic.identity_bindings.length} 项` : "未绑定"}`;
  content.replaceChildren(
    detailBlock("身份与版本", [
      ["模型名", detail.model_name], ["版本名", detail.version_name], ["基础模型", detail.base_model],
      ["模型类型", detail.model_type], ["子类型", detail.sub_type], ["目录", detail.folder],
    ]),
    detailBlock("语义与触发", [
      ["当前分类", detail.semantic?.category || detail.category], ["角色名", detail.semantic?.character_names || detail.character_name],
      ["作品", detail.semantic?.source_works || detail.source_work], ["画师 / 风格", detail.semantic?.artist_style_names],
      ["Danbooru exact 绑定", identityBindingLines(detail.semantic?.identity_bindings)], ["共享激活词", detail.semantic?.activation_terms],
      ["别名", detail.semantic?.aliases || detail.aliases], ["Manager 触发词", detail.trigger_words], ["标签", detail.tags],
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
  payload.semantic_schema_version = 3;
  payload.identity_bindings = String(payload.identity_bindings || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const [characterCanonical = "", copyrightCanonical = "", activationText = ""] = line.split("|").map((part) => part.trim());
    return {
      character_canonical: characterCanonical,
      copyright_canonical: copyrightCanonical,
      activation_terms: activationText.split(/[,，;；]+/).map((item) => item.trim()).filter(Boolean),
    };
  });
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
    if (loraViewMode === "gallery") await loadLoraGallery({quiet: true});
    else await searchLoras(null);
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
    presetItems = data.items || [];
    for (const item of presetItems) {
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
      const editButton = document.createElement("button");
      editButton.className = "secondary compact";
      editButton.type = "button";
      editButton.textContent = "编辑";
      editButton.addEventListener("click", () => editPreset(item));
      const deleteButton = document.createElement("button");
      deleteButton.className = "danger compact";
      deleteButton.type = "button";
      deleteButton.textContent = "删除";
      deleteButton.addEventListener("click", () => deletePreset(item.name));
      action.append(editButton, deleteButton);
      const aliases = unique(item.derived_aliases || item.aliases || []);
      const triggerLines = [
        `手动补充：${item.trigger_words || "（无）"}`,
        `Manager 最新：${(item.manager_trigger_words || []).join(", ") || "（无）"}`,
        `最终有效：${(item.effective_trigger_words || []).join(", ") || "（无）"}`,
      ];
      row.append(
        textCell([item.name, aliases.length ? `简称：${aliases.join(" / ")}` : ""].filter(Boolean).join("\n"), "multiline"),
        textCell(item.category_label),
        textCell((item.loras || []).join("\n"), "multiline"),
        textCell(triggerLines.join("\n"), "multiline"),
        textCell([item.note, item.description].filter(Boolean).join("\n") || "—", "multiline"),
        statusCell,
        action,
      );
      table.append(row);
    }
    empty.hidden = presetItems.length > 0;
    empty.textContent = presetItems.length ? "" : "尚未保存任何组合。";
  } catch (error) {
    empty.textContent = error.message;
    showToast(error.message, true);
  }
}

function resetPresetEditor() {
  const form = document.querySelector("#preset-form");
  form.reset();
  form.elements.namedItem("identifier").value = "";
  form.elements.namedItem("enabled").checked = true;
  document.querySelector("#preset-editor-title").textContent = "新建组合";
  document.querySelector("#preset-save").textContent = "强制刷新并保存";
  document.querySelector("#preset-cancel-edit").hidden = true;
}

function editPreset(item) {
  const form = document.querySelector("#preset-form");
  form.elements.namedItem("identifier").value = item.name || "";
  form.elements.namedItem("name").value = item.name || "";
  form.elements.namedItem("category").value = item.category || "mixed";
  form.elements.namedItem("aliases").value = (item.aliases || []).join("\n");
  form.elements.namedItem("note").value = item.note || "";
  form.elements.namedItem("loras").value = (item.loras || []).join("\n");
  form.elements.namedItem("trigger_words").value = item.trigger_words || "";
  form.elements.namedItem("description").value = item.description || "";
  form.elements.namedItem("enabled").checked = item.enabled !== false;
  document.querySelector("#preset-editor-title").textContent = `编辑：${item.name}`;
  document.querySelector("#preset-save").textContent = "强制刷新并更新";
  document.querySelector("#preset-cancel-edit").hidden = false;
  form.scrollIntoView({behavior: "smooth", block: "start"});
}

async function savePreset(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  setBusy(button, true, "正在保存…");
  const values = new FormData(form);
  const payload = {
    identifier: values.get("identifier"),
    name: values.get("name"),
    category: values.get("category"),
    loras: String(values.get("loras") || "").split("\n").map((item) => item.trim()).filter(Boolean),
    trigger_words: values.get("trigger_words"),
    description: values.get("description"),
    aliases: values.get("aliases"),
    note: values.get("note"),
    enabled: form.elements.namedItem("enabled").checked,
  };
  try {
    const data = await api("/api/presets", {method: "POST", body: JSON.stringify(payload)});
    showToast(data.message);
    resetPresetEditor();
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

function promptValueList(value) {
  if (Array.isArray(value)) return value.map((item) => String(item ?? "").trim()).filter(Boolean);
  if (value === null || value === undefined || value === "") return [];
  return [String(value).trim()].filter(Boolean);
}

function promptNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function promptTimestamp(value) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  const date = Number.isFinite(numeric)
    ? new Date(numeric > 10_000_000_000 ? numeric : numeric * 1000)
    : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", {hour12: false});
}

function promptStatusPart(data, ...keys) {
  for (const key of keys) {
    const value = data?.[key];
    if (value && typeof value === "object" && !Array.isArray(value)) return value;
  }
  return {};
}

function promptDiagnosticItems(data) {
  if (Array.isArray(data?.diagnostics)) return data.diagnostics;
  const diagnostics = promptStatusPart(data, "diagnostics", "memory_diagnostics");
  for (const value of [
    diagnostics.items,
    diagnostics.records,
    diagnostics.recent,
    data?.recent_diagnostics,
    data?.diagnostic_items,
  ]) {
    if (Array.isArray(value)) return value;
  }
  return [];
}

function appendPromptValueList(container, values, emptyText = "无") {
  const items = promptValueList(values);
  if (!items.length) {
    const empty = document.createElement("span");
    empty.className = "prompt-empty-value";
    empty.textContent = emptyText;
    container.append(empty);
    return;
  }
  const list = document.createElement("div");
  list.className = "prompt-token-list";
  for (const value of items) list.append(chip(value));
  container.append(list);
}

function promptResultSection(title, values, {wide = false, code = false, emptyText = "无"} = {}) {
  const section = document.createElement("section");
  section.className = `prompt-result-section${wide ? " wide" : ""}${code ? " code-section" : ""}`;
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading);
  if (code) {
    const pre = document.createElement("pre");
    pre.textContent = String(values || emptyText);
    section.append(pre);
  } else {
    appendPromptValueList(section, values, emptyText);
  }
  return section;
}

function renderPromptDiagnosticHistory(items) {
  const container = document.querySelector("#prompt-diagnostic-history");
  container.replaceChildren();
  const records = Array.isArray(items) ? items : [];
  if (!records.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state compact-empty";
    empty.textContent = "暂无诊断记录。";
    container.append(empty);
    return;
  }
  for (const record of records.slice(0, 24)) {
    const article = document.createElement("article");
    article.className = "prompt-history-item";
    const head = document.createElement("div");
    head.className = "prompt-history-head";
    const title = document.createElement("strong");
    const identifier = String(record.diagnostic_id || record.id || "diagnostic");
    title.textContent = `${record.source || "runtime"} · ${identifier.slice(0, 10)}`;
    const time = document.createElement("time");
    time.textContent = promptTimestamp(record.created_at || record.timestamp);
    head.append(title, time);
    const summary = document.createElement("p");
    const warnings = promptNumber(
      record.validation_warning_count,
      promptValueList(record.validation_warnings || record.warnings).length,
    );
    const conflicts = promptNumber(
      record.conflict_count,
      promptValueList(record.conflicts).length,
    );
    const unknown = promptNumber(
      record.unknown_tag_count,
      promptValueList(record.unknown_tags).length,
    );
    const adaptive = promptNumber(
      record.adaptive_negative_count,
      promptValueList(record.adaptive_negative_added).length,
    );
    summary.textContent = `冲突 ${conflicts} · 未知 ${unknown} · 警告 ${warnings} · 动态负面 ${adaptive}`;
    article.append(head, summary);
    container.append(article);
  }
}

function renderPromptStatus(data) {
  promptStatusData = data || {};
  const composer = promptStatusPart(data, "composer", "prompt_composer");
  const index = promptStatusPart(data, "danbooru", "danbooru_index", "index");
  const diagnostics = promptStatusPart(data, "diagnostics", "memory_diagnostics");
  const settings = bootstrapData?.settings || {};
  const composerEnabled = composer.enabled ?? data?.enable_prompt_composer_v2 ?? settings.enable_prompt_composer_v2;
  const negativeMode = composer.adaptive_negative_mode || data?.adaptive_negative_mode || settings.adaptive_negative_mode || "off";
  const validationMode = composer.validation_mode || data?.danbooru_validation_mode || settings.danbooru_validation_mode || "off";
  const effectiveValidationMode = composer.effective_validation_mode || validationMode;
  const validationLabel = composer.guarded_degraded_to_report
    ? `${validationMode}->${effectiveValidationMode}`
    : validationMode;
  const indexReady = Boolean(index.ready);
  const tagCount = promptNumber(index.tag_count ?? index.tags);
  const aliasCount = promptNumber(index.alias_count ?? index.aliases);
  const uniqueAliasCount = promptNumber(index.unique_alias_count);
  const ambiguousAliasCount = promptNumber(index.ambiguous_alias_count);
  const canonicalConflictCount = promptNumber(index.canonical_conflict_alias_count);
  const localizedAliases = index.localized_aliases && typeof index.localized_aliases === "object"
    ? index.localized_aliases
    : {};
  const diagnosticItems = promptDiagnosticItems(data);
  const diagnosticCount = promptNumber(
    diagnostics.count ?? diagnostics.size ?? composer.count,
    diagnosticItems.length,
  );
  const diagnosticCapacity = promptNumber(
    diagnostics.capacity ?? diagnostics.max_items ?? composer.capacity ?? data?.prompt_diagnostics_capacity,
    settings.prompt_diagnostics_capacity || 0,
  );
  const updateTask = index.update_task && typeof index.update_task === "object"
    ? index.update_task
    : {};
  const updateRunId = String(updateTask.run_id || updateTask.id || "");
  const updateStatus = String(updateTask.status || "").toLowerCase();
  const updateActive = activeTaskStatuses.has(updateStatus);
  const updateModeLabel = updateTask.mode === "official_api" ? "官方 API" : "URL";
  const autoUpdate = index.auto_update && typeof index.auto_update === "object"
    ? index.auto_update
    : {};
  promptIndexTaskRunId = updateRunId;
  const taskButton = document.querySelector("#prompt-index-task");
  taskButton.hidden = !updateRunId;
  taskButton.textContent = updateActive ? "查看更新进度" : "查看最近任务";

  document.querySelector("#prompt-composer-state").textContent = composerEnabled ? "ON" : "OFF";
  document.querySelector("#prompt-composer-detail").textContent = `负面词 ${negativeMode} · 校验 ${validationLabel}`;
  document.querySelector("#prompt-index-state").textContent = updateActive
    ? "BUILDING"
    : (indexReady ? "READY" : "EMPTY");
  document.querySelector("#prompt-index-detail").textContent = updateActive
    ? `${updateModeLabel} · ${taskProgress(updateTask).toFixed(0)}% · 当前 ${tagCount.toLocaleString()} Tags`
    : (indexReady
      ? `${tagCount.toLocaleString()} Tags · ${aliasCount.toLocaleString()} Aliases`
      : (index.error || "尚未导入本地索引"));
  document.querySelector("#prompt-diagnostic-count").textContent = diagnosticCount.toLocaleString();
  document.querySelector("#prompt-diagnostic-capacity").textContent = diagnosticCapacity
    ? `内存上限 ${diagnosticCapacity} 条 · 重载清空`
    : "仅保存在内存";
  document.querySelector("#prompt-index-badge").textContent = updateActive
    ? (updateStatus === "queued" ? "QUEUED" : "RUNNING")
    : (indexReady ? "READY" : "NOT READY");
  document.querySelector("#prompt-index-tags").textContent = tagCount.toLocaleString();
  document.querySelector("#prompt-index-aliases").textContent = aliasCount.toLocaleString();
  document.querySelector("#prompt-index-unique-aliases").textContent = uniqueAliasCount.toLocaleString();
  document.querySelector("#prompt-index-ambiguous-aliases").textContent = `${ambiguousAliasCount.toLocaleString()} / ${canonicalConflictCount.toLocaleString()}`;
  document.querySelector("#prompt-index-revision").textContent = index.revision || index.version || "—";
  document.querySelector("#prompt-index-updated").textContent = promptTimestamp(index.imported_at || index.updated_at);
  document.querySelector("#prompt-index-source-updated").textContent = promptTimestamp(index.source_updated_at);
  document.querySelector("#prompt-index-source-cutoff").textContent = promptTimestamp(index.source_cutoff_at);
  document.querySelector("#prompt-index-localized").textContent = localizedAliases.ready
    ? `${promptNumber(localizedAliases.entry_count).toLocaleString()} 条${localizedAliases.csv_loaded ? " · CSV 已加载" : " · 内置/运行时"}`
    : (localizedAliases.csv_error ? `CSV 异常：${localizedAliases.csv_error}` : "未加载");
  document.querySelector("#prompt-index-source").textContent = index.source
    || index.url
    || settings.danbooru_index_url
    || settings.danbooru_api_base_url
    || "尚未配置或导入";
  const categories = index.category_counts || index.categories || {};
  document.querySelector("#prompt-index-categories").textContent = Object.keys(categories).length
    ? Object.entries(categories).map(([name, count]) => `${name} ${promptNumber(count).toLocaleString()}`).join(" · ")
    : "—";
  let indexStatusText = "";
  if (updateActive) {
    indexStatusText = `${updateModeLabel} 索引任务${taskStatusLabel(updateStatus)}；${indexReady ? "当前旧索引继续可用。" : "当前尚无可用旧索引。"}`;
  } else if (updateStatus === "succeeded") {
    indexStatusText = `最近一次 ${updateModeLabel} 索引任务已成功；本地索引已原子切换。`;
  } else if (["failed", "timed_out", "cancelled", "interrupted", "partial"].includes(updateStatus)) {
    const reason = updateTask.error_summary || updateTask.error || index.error || "旧索引已保留";
    indexStatusText = `最近一次 ${updateModeLabel} 索引任务${taskStatusLabel(updateStatus)}：${reason}`;
  } else if (index.error) {
    indexStatusText = `索引状态异常：${index.error}`;
  } else {
    indexStatusText = indexReady
      ? "本地索引可用；更新失败时仍会保留当前版本。"
      : "尚无可用索引；可从官方 API 生成，或先配置自定义数据源 URL。";
  }
  if (autoUpdate.enabled) {
    const nextRun = promptTimestamp(autoUpdate.next_run_at);
    indexStatusText += ` 自动更新：每 ${promptNumber(autoUpdate.interval_hours)} 小时；下次 ${nextRun}。`;
  } else {
    indexStatusText += " 自动更新未启用。";
  }
  document.querySelector("#prompt-index-status").textContent = indexStatusText;
  renderPromptDiagnosticHistory(diagnosticItems);
}

function renderPromptDiagnostic(data) {
  const result = data?.result || data?.composed || data || {};
  const layers = Object.keys(promptStatusPart(result, "layers", "prompt_layers")).length
    ? promptStatusPart(result, "layers", "prompt_layers")
    : promptStatusPart(data, "layers", "prompt_layers");
  const diagnostics = Object.keys(promptStatusPart(result, "diagnostics", "diagnostic")).length
    ? promptStatusPart(result, "diagnostics", "diagnostic")
    : promptStatusPart(data, "diagnostics", "diagnostic");
  const identifier = String(result.diagnostic_id || diagnostics.diagnostic_id || data?.diagnostic_id || "");
  const positive = result.positive_prompt || result.positive || result.prompt || "";
  const negative = result.negative_prompt || result.negative || "";
  const container = document.querySelector("#prompt-diagnostic-result");
  container.replaceChildren();
  document.querySelector("#prompt-result-id").textContent = identifier ? identifier.slice(0, 12) : "LOCAL RESULT";

  container.append(
    promptResultSection("最终正面提示词", positive, {wide: true, code: true, emptyText: "后端未返回完整内容；请检查“诊断包含完整提示词”设置。"}),
    promptResultSection("最终负面提示词", negative, {wide: true, code: true, emptyText: "无负面提示词"}),
    promptResultSection("LoRA 控制层", layers.lora_tags || result.lora_tags, {emptyText: "没有 LoRA 控制标签"}),
    promptResultSection("硬 Tags", layers.hard_tags || result.hard_tags, {emptyText: "没有可分离的硬 Tags"}),
    promptResultSection("视觉短语", layers.visual_phrases || result.visual_phrases, {emptyText: "没有柔性视觉短语"}),
    promptResultSection("场景关系句", layers.scene_sentence || result.scene_sentence, {wide: true, code: true, emptyText: "没有识别到场景关系句"}),
    promptResultSection("重复项已移除", diagnostics.duplicates_removed || result.duplicates_removed),
    promptResultSection("冲突与丢弃", [
      ...promptValueList(diagnostics.conflicts || result.conflicts),
      ...promptValueList(diagnostics.discarded_tags || result.discarded_tags),
    ]),
    promptResultSection("自适应负面词", diagnostics.adaptive_negative_added || result.adaptive_negative_added),
    promptResultSection("Danbooru 警告", [
      ...promptValueList(diagnostics.unknown_tags || result.unknown_tags),
      ...promptValueList(diagnostics.validation_warnings || result.validation_warnings),
    ]),
  );
}

async function loadPromptStatus({quiet = false} = {}) {
  try {
    const data = await api("/api/prompt/status");
    renderPromptStatus(data);
    return data;
  } catch (error) {
    document.querySelector("#prompt-index-status").textContent = `提示词状态读取失败：${error.message}`;
    if (!quiet) showToast(error.message, true);
    return null;
  }
}

function renderExperimentalProfiles(data) {
  const items = Array.isArray(data) ? data : (data?.items || data?.profiles || data?.results || []);
  experimentalProfileItems = Array.isArray(items) ? items : [];
  const readyCount = experimentalProfileItems.filter((item) => item.ready).length;
  document.querySelector("#prompt-experiment-count").textContent = readyCount.toLocaleString();
  const container = document.querySelector("#prompt-experiment-list");
  container.replaceChildren();
  if (!experimentalProfileItems.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state compact-empty";
    empty.textContent = "没有返回实验能力定义。";
    container.append(empty);
    return;
  }
  for (const item of experimentalProfileItems) {
    const article = document.createElement("article");
    article.className = `prompt-experiment-item ${item.ready ? "ready" : "blocked"}`;
    const head = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.label || item.name || item.id || "实验能力";
    const badge = document.createElement("span");
    badge.className = "ticket-tag";
    badge.textContent = item.ready ? "READY" : "BLOCKED";
    head.append(title, badge);
    const missing = promptValueList(item.missing_nodes || item.missing);
    const required = promptValueList(item.required_nodes || item.required);
    const detail = document.createElement("p");
    detail.textContent = missing.length
      ? `缺少节点：${missing.join("、")}`
      : (required.length ? `节点合同：${required.join("、")}` : "未声明节点合同");
    article.append(head, detail);
    const notes = promptValueList(item.notes);
    if (notes.length) {
      const note = document.createElement("small");
      note.textContent = notes.join(" ");
      article.append(note);
    }
    container.append(article);
  }
}

async function loadExperimentalProfiles({quiet = false} = {}) {
  const status = document.querySelector("#prompt-experiment-status");
  status.textContent = "正在读取 ComfyUI 实验能力…";
  try {
    const data = await api("/api/experiments/check");
    renderExperimentalProfiles(data);
    status.textContent = data.message || "检查只读取实时节点与调度器，不会修改 ComfyUI。";
    return data;
  } catch (error) {
    status.textContent = `实验能力检查失败：${error.message}`;
    if (!quiet) showToast(error.message, true);
    return null;
  }
}

async function loadPromptWorkbench({quiet = false} = {}) {
  await loadPromptStatus({quiet});
  if (promptActiveTab === "assets") await loadPromptAssets({quiet});
  if (promptActiveTab === "lab") await loadPromptPlans({quiet});
  if (promptActiveTab === "diagnostics") await loadExperimentalProfiles({quiet});
}

async function diagnosePrompt(event) {
  event.preventDefault();
  const button = document.querySelector("#prompt-diagnose");
  const positive = document.querySelector("#prompt-diagnostic-positive").value.trim();
  const negative = document.querySelector("#prompt-diagnostic-negative").value.trim();
  const status = document.querySelector("#prompt-diagnostic-status");
  if (!positive) {
    status.textContent = "请先输入正面提示词。";
    document.querySelector("#prompt-diagnostic-positive").focus();
    return;
  }
  setBusy(button, true, "正在诊断…");
  status.textContent = "正在执行本地分层、冲突与标签检查…";
  try {
    const data = await api("/api/prompt/diagnose", {
      method: "POST",
      body: JSON.stringify({prompt: positive, negative_prompt: negative}),
    });
    renderPromptDiagnostic(data);
    status.textContent = data.message || "本地诊断完成；未调用 LLM，未提交 ComfyUI。";
    await loadPromptStatus({quiet: true});
  } catch (error) {
    status.textContent = `诊断失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function clearPromptDiagnostics() {
  if (!(await confirmAction(
    "清空当前插件进程中的提示词诊断记录？此操作不会删除任务、日志或 Danbooru 索引。",
    {title: "清空内存诊断", confirmLabel: "确认清空", danger: false},
  ))) return;
  const button = document.querySelector("#prompt-diagnostics-clear");
  setBusy(button, true, "正在清空…");
  try {
    const data = await api("/api/prompt/diagnostics", {method: "DELETE"});
    renderPromptDiagnosticHistory([]);
    document.querySelector("#prompt-diagnostic-count").textContent = "0";
    showToast(data.message || "内存提示词诊断已清空");
    await loadPromptStatus({quiet: true});
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function updateDanbooruIndex(mode = "url") {
  const normalizedMode = mode === "official_api" ? "official_api" : "url";
  const official = normalizedMode === "official_api";
  if (!(await confirmAction(
    official
      ? "从 Danbooru 官方公开 API 流式生成完整本地索引？任务会进入任务中心，失败或取消时保留当前版本。"
      : "从全局设置中的数据源 URL 下载并原子更新本地 Danbooru 索引？任务会进入任务中心，失败或取消时保留当前版本。",
    {
      title: official ? "从官方 API 生成索引" : "从 URL 更新索引",
      confirmLabel: official ? "开始生成" : "开始更新",
      danger: false,
    },
  ))) return;
  const button = document.querySelector(
    official ? "#prompt-index-official-update" : "#prompt-index-update",
  );
  const status = document.querySelector("#prompt-index-status");
  setBusy(button, true, official ? "正在创建…" : "正在更新…");
  status.textContent = official
    ? "正在创建官方 API 索引任务…"
    : "正在创建 URL 索引更新任务…";
  try {
    const data = await api("/api/danbooru/update", {
      method: "POST",
      body: JSON.stringify({mode: normalizedMode}),
    });
    status.textContent = data.message || "Danbooru 索引任务已创建。";
    showToast(status.textContent);
    await loadPromptStatus({quiet: true});
    const runId = String(data.run_id || data.task?.run_id || data.task?.id || "");
    if (runId) await openTaskCenter(runId);
  } catch (error) {
    status.textContent = `索引任务创建失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

const promptSlotNames = [
  "lora",
  "identity",
  "appearance",
  "clothing",
  "pose",
  "camera",
  "background",
  "lighting",
  "style",
  "visual_phrases",
  "relation",
  "negative",
];

const promptAssetTypeLabels = {
  character: "角色",
  clothing: "服装",
  pose: "姿势",
  background: "背景",
  artist: "画师 / 风格",
};

const promptAssetSlotMap = {
  character: "identity",
  clothing: "clothing",
  pose: "pose",
  background: "background",
  artist: "style",
};

function splitPromptField(value) {
  return String(value || "")
    .split(/\r?\n|,\s*/u)
    .map((item) => item.trim())
    .filter(Boolean);
}

function readPromptSlots() {
  const slots = {};
  for (const name of promptSlotNames) {
    slots[name] = document.querySelector(`[data-slot-input="${name}"]`).value.trim();
  }
  slots.scene_sentence = slots.relation;
  return slots;
}

function readPromptLockedSlots() {
  return [...document.querySelectorAll("[data-slot-lock]:checked")]
    .map((input) => input.dataset.slotLock)
    .filter((name) => promptSlotNames.includes(name));
}

function promptLayersFromSlots(slots = readPromptSlots()) {
  return {
    lora: splitPromptField(slots.lora),
    identity: splitPromptField(slots.identity),
    appearance: splitPromptField(slots.appearance),
    clothing: splitPromptField(slots.clothing),
    pose: splitPromptField(slots.pose),
    camera: splitPromptField(slots.camera),
    background: splitPromptField(slots.background),
    lighting: splitPromptField(slots.lighting),
    style: splitPromptField(slots.style),
    relation: String(slots.relation || "").trim(),
  };
}

function compositionParts(data) {
  const confirmed = data?.confirmed && typeof data.confirmed === "object" ? data.confirmed : null;
  const root = confirmed || data?.composed || data?.result || data || {};
  const nestedLayers = promptStatusPart(root, "layers", "prompt_layers");
  const nestedDiagnostics = promptStatusPart(root, "diagnostics", "diagnostic");
  const layers = Object.keys(nestedLayers).length
    ? nestedLayers
    : promptStatusPart(data, "layers", "prompt_layers");
  const diagnostics = Object.keys(nestedDiagnostics).length
    ? nestedDiagnostics
    : promptStatusPart(data, "diagnostics", "diagnostic");
  return {root, layers, diagnostics};
}

function renderCompositionProof(containerSelector, badgeSelector, data, badgeText = "COMPOSED") {
  const container = document.querySelector(containerSelector);
  const badge = document.querySelector(badgeSelector);
  const {root, layers, diagnostics} = compositionParts(data);
  const positive = root.positive_prompt || root.positive || root.prompt || "";
  const negative = root.negative_prompt || root.negative || "";
  container.replaceChildren(
    promptResultSection("最终正面提示词", positive, {wide: true, code: true, emptyText: "后端未返回正面提示词"}),
    promptResultSection("最终负面提示词", negative, {wide: true, code: true, emptyText: "无负面提示词"}),
    promptResultSection("LoRA 控制", layers.lora_tags || root.lora_tags, {emptyText: "无 LoRA"}),
    promptResultSection("硬 Tags", layers.hard_tags || root.hard_tags, {emptyText: "无硬 Tags"}),
    promptResultSection("视觉短语", layers.visual_phrases || root.visual_phrases, {emptyText: "无视觉短语"}),
    promptResultSection("场景关系句", layers.scene_sentence || root.scene_sentence, {wide: true, code: true, emptyText: "无场景关系句"}),
    promptResultSection("冲突 / 警告", [
      ...promptValueList(diagnostics.conflicts || root.conflicts),
      ...promptValueList(diagnostics.validation_warnings || diagnostics.warnings || root.warnings),
    ]),
    promptResultSection("去重 / 丢弃", [
      ...promptValueList(diagnostics.duplicates_removed || root.duplicates_removed),
      ...promptValueList(diagnostics.discarded_tags || root.discarded_terms),
    ]),
  );
  badge.textContent = badgeText;
}

async function composePromptSlots(event) {
  event.preventDefault();
  const button = document.querySelector("#prompt-compose-slots");
  const status = document.querySelector("#prompt-slot-status");
  const slots = readPromptSlots();
  const hasContent = promptSlotNames.some((name) => slots[name]);
  if (!hasContent) {
    status.textContent = "请先填写至少一个槽位。";
    document.querySelector("#prompt-slot-identity").focus();
    return;
  }
  setBusy(button, true, "正在组合…");
  status.textContent = "正在按 LoRA → 硬 Tags → 视觉短语 → 场景句组合并校验…";
  try {
    const data = await api("/api/prompt/compose-slots", {
      method: "POST",
      body: JSON.stringify({
        slots,
        locked_slots: readPromptLockedSlots(),
        negative_prompt: slots.negative,
        source: "web_prompt_composer",
      }),
    });
    renderCompositionProof("#prompt-compose-result", "#prompt-compose-badge", data);
    status.textContent = data.message || "组合完成；结果仍是草稿，没有提交 ComfyUI。";
  } catch (error) {
    status.textContent = `组合失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function clearUnlockedPromptSlots() {
  const locked = new Set(readPromptLockedSlots());
  for (const name of promptSlotNames) {
    if (!locked.has(name)) document.querySelector(`[data-slot-input="${name}"]`).value = "";
  }
  document.querySelector("#prompt-slot-status").textContent = "已清空未锁定槽位。";
}

function switchPromptTab(name, {focus = false, load = true} = {}) {
  const allowed = new Set(["composer", "assets", "lab", "diagnostics"]);
  promptActiveTab = allowed.has(name) ? name : "composer";
  writePreference("comfy-anima-prompt-tab", promptActiveTab);
  for (const button of document.querySelectorAll("[data-prompt-tab]")) {
    const active = button.dataset.promptTab === promptActiveTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    if (active && focus) button.focus();
  }
  for (const page of document.querySelectorAll(".prompt-subpage")) {
    const active = page.id === `prompt-page-${promptActiveTab}`;
    page.classList.toggle("active", active);
    page.hidden = !active;
  }
  if (!load || currentPanel !== "prompt") return;
  if (promptActiveTab === "assets") loadPromptAssets({quiet: true});
  if (promptActiveTab === "lab") loadPromptPlans({quiet: true});
  if (promptActiveTab === "diagnostics") loadExperimentalProfiles({quiet: true});
}

function initializePromptSubnav() {
  switchPromptTab(readPreference("comfy-anima-prompt-tab", "composer"), {load: false});
  document.querySelector("#prompt-workbench-tabs").addEventListener("keydown", (event) => {
    if (!new Set(["ArrowLeft", "ArrowRight", "Home", "End"]).has(event.key)) return;
    const buttons = [...document.querySelectorAll("[data-prompt-tab]")];
    const current = buttons.findIndex((button) => button.dataset.promptTab === promptActiveTab);
    let next = current;
    if (event.key === "ArrowLeft") next = (current - 1 + buttons.length) % buttons.length;
    if (event.key === "ArrowRight") next = (current + 1) % buttons.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    event.preventDefault();
    switchPromptTab(buttons[next].dataset.promptTab, {focus: true});
  });
}

function promptAssetDisplayName(item) {
  return String(item?.name_zh || item?.name_en || item?.label || item?.asset_id || "未命名素材");
}

function promptAssetProvenance(item) {
  return item?.provenance && typeof item.provenance === "object" && !Array.isArray(item.provenance)
    ? item.provenance
    : {};
}

function promptAssetCard(item) {
  const article = document.createElement("article");
  article.className = "prompt-asset-card";
  article.dataset.assetId = String(item.asset_id || "");
  const head = document.createElement("header");
  const heading = document.createElement("div");
  const label = document.createElement("span");
  label.className = "mono-label";
  label.textContent = promptAssetTypeLabels[item.asset_type] || item.asset_type || "素材";
  const title = document.createElement("h3");
  title.textContent = promptAssetDisplayName(item);
  heading.append(label, title);
  const favorite = document.createElement("button");
  favorite.className = "asset-favorite-button";
  favorite.type = "button";
  favorite.setAttribute("aria-pressed", String(Boolean(item.favorite)));
  favorite.setAttribute("aria-label", item.favorite ? "取消收藏" : "收藏素材");
  favorite.textContent = item.favorite ? "★" : "☆";
  favorite.addEventListener("click", () => setPromptAssetFavorite(item, favorite));
  head.append(heading, favorite);

  const tags = document.createElement("div");
  tags.className = "prompt-asset-tags";
  const tagValues = promptValueList(item.tags);
  for (const value of tagValues.slice(0, 8)) tags.append(chip(value));
  if (tagValues.length > 8) tags.append(chip(`+${tagValues.length - 8}`, "neutral"));
  if (!tagValues.length) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "没有 Tags";
    tags.append(empty);
  }

  const provenance = promptAssetProvenance(item);
  const facts = document.createElement("dl");
  facts.className = "prompt-asset-facts";
  for (const [name, value] of [
    ["来源", provenance.source || provenance.dataset || "未声明"],
    ["许可", provenance.license || provenance.spdx || "未声明"],
    ["版本", provenance.version || provenance.revision || "—"],
  ]) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = name;
    detail.textContent = String(value);
    row.append(term, detail);
    facts.append(row);
  }

  const actions = document.createElement("div");
  actions.className = "prompt-asset-actions";
  const add = document.createElement("button");
  add.className = "primary";
  add.type = "button";
  add.textContent = "加入构图台";
  add.addEventListener("click", () => addPromptAssetToComposer(item));
  actions.append(add);
  if (item.is_custom) {
    const edit = document.createElement("button");
    edit.className = "secondary";
    edit.type = "button";
    edit.textContent = "编辑";
    edit.addEventListener("click", () => editPromptCustomAsset(item));
    actions.append(edit);
  }
  article.append(head, tags, facts, actions);
  return article;
}

function renderPromptAssets(data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  promptAssetItems = items;
  promptAssetPage = Math.max(1, Number(data?.page || promptAssetPage || 1));
  promptAssetPages = Math.max(1, Number(data?.pages || 1));
  promptAssetFingerprint = String(data?.fingerprint || data?.library_fingerprint || promptAssetFingerprint || "");
  const grid = document.querySelector("#prompt-asset-grid");
  grid.replaceChildren(...items.map(promptAssetCard));
  document.querySelector("#prompt-asset-empty").hidden = items.length > 0;
  document.querySelector("#prompt-asset-page").textContent = `第 ${promptAssetPage} / ${promptAssetPages} 页 · ${Number(data?.total || items.length).toLocaleString()} 项`;
  document.querySelector("#prompt-asset-prev").disabled = promptAssetPage <= 1;
  document.querySelector("#prompt-asset-next").disabled = promptAssetPage >= promptAssetPages;
}

async function loadPromptAssetStatus({quiet = false} = {}) {
  try {
    const data = await api("/api/prompt-assets/status");
    document.querySelector("#prompt-asset-count").textContent = Number(data.asset_count || data.total || 0).toLocaleString();
    document.querySelector("#prompt-asset-favorite-count").textContent = Number(data.favorite_count || 0).toLocaleString();
    document.querySelector("#prompt-asset-custom-count").textContent = Number(data.custom_count || 0).toLocaleString();
    document.querySelector("#prompt-asset-imported-at").textContent = promptTimestamp(data.last_import_at);
    promptAssetFingerprint = String(data.fingerprint || data.last_import_sha256 || promptAssetFingerprint || "");
    return data;
  } catch (error) {
    if (!quiet) showToast(error.message, true);
    document.querySelector("#prompt-asset-status").textContent = `素材库状态读取失败：${error.message}`;
    return null;
  }
}

function renderPromptAssetFacetOptions(selector, values) {
  const datalist = document.querySelector(selector);
  const options = (Array.isArray(values) ? values : []).map((item) => {
    const option = document.createElement("option");
    option.value = String(item?.value || "");
    option.label = `${Number(item?.count || 0).toLocaleString()} 项`;
    return option;
  }).filter((option) => option.value);
  datalist.replaceChildren(...options);
}

async function loadPromptAssetFacets({quiet = false} = {}) {
  const assetType = document.querySelector("#prompt-asset-type").value;
  const customOnly = assetType === "__custom__";
  try {
    const data = await api("/api/prompt-assets/facets", {
      method: "POST",
      body: JSON.stringify({
        asset_type: customOnly ? "" : assetType,
        source: document.querySelector("#prompt-asset-source").value.trim(),
        favorite_only: document.querySelector("#prompt-asset-favorites-only").checked,
        custom_only: customOnly ? true : null,
        limit: 200,
      }),
    });
    if (data.fingerprint) promptAssetFingerprint = String(data.fingerprint);
    renderPromptAssetFacetOptions("#prompt-asset-category-options", data.categories);
    renderPromptAssetFacetOptions("#prompt-asset-trait-options", data.traits);
    return data;
  } catch (error) {
    if (!quiet) showToast(error.message, true);
    return null;
  }
}

async function searchPromptAssets(event = null, {quiet = false} = {}) {
  if (event) event.preventDefault();
  const status = document.querySelector("#prompt-asset-status");
  const assetType = document.querySelector("#prompt-asset-type").value;
  const customOnly = assetType === "__custom__";
  const libraryType = customOnly ? "" : assetType;
  status.textContent = "正在读取分页素材…";
  try {
    const data = await api("/api/prompt-assets/search", {
      method: "POST",
      body: JSON.stringify({
        query: document.querySelector("#prompt-asset-query").value.trim(),
        asset_type: libraryType,
        categories: splitPromptField(document.querySelector("#prompt-asset-categories").value),
        traits: splitPromptField(document.querySelector("#prompt-asset-traits").value),
        tags: splitPromptField(document.querySelector("#prompt-asset-tags").value),
        source: document.querySelector("#prompt-asset-source").value.trim(),
        favorite_only: document.querySelector("#prompt-asset-favorites-only").checked,
        custom_only: customOnly ? true : null,
        page: promptAssetPage,
        page_size: Number(document.querySelector("#prompt-asset-page-size").value),
      }),
    });
    renderPromptAssets(data);
    status.textContent = `当前页 ${promptAssetItems.length} 项；只把分页结果放入 DOM。`;
    return data;
  } catch (error) {
    renderPromptAssets({items: [], page: 1, pages: 1});
    status.textContent = `素材搜索失败：${error.message}`;
    if (!quiet) showToast(error.message, true);
    return null;
  }
}

async function loadPromptAssets({quiet = false} = {}) {
  await Promise.all([
    loadPromptAssetStatus({quiet}),
    loadPromptAssetFacets({quiet}),
    searchPromptAssets(null, {quiet}),
  ]);
}

async function syncLocalPromptAssets() {
  const button = document.querySelector("#prompt-assets-sync-local");
  const status = document.querySelector("#prompt-asset-status");
  setBusy(button, true, "正在同步…");
  status.textContent = "正在强制刷新 LoRA Manager，并把最新语义索引与已保存预设转换为本地视觉素材…";
  try {
    const data = await api("/api/prompt-assets/sync-local", {method: "POST", body: JSON.stringify({})});
    status.textContent = data.message || `本地素材同步完成，本次 ${Number(data.synced || data.count || 0).toLocaleString()} 项。`;
    promptAssetPage = 1;
    await loadPromptAssets({quiet: true});
  } catch (error) {
    status.textContent = `本地素材同步失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function setPromptAssetFavorite(item, button) {
  setBusy(button, true, "…");
  try {
    const favorite = !Boolean(item.favorite);
    const data = await api("/api/prompt-assets/favorite", {
      method: "PUT",
      body: JSON.stringify({asset_id: item.asset_id, favorite}),
    });
    item.favorite = data.favorite ?? favorite;
    button.textContent = item.favorite ? "★" : "☆";
    button.setAttribute("aria-pressed", String(Boolean(item.favorite)));
    button.setAttribute("aria-label", item.favorite ? "取消收藏" : "收藏素材");
    await loadPromptAssetStatus({quiet: true});
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
    button.textContent = item.favorite ? "★" : "☆";
  }
}

function addPromptAssetToComposer(item) {
  const slot = promptAssetSlotMap[item.asset_type] || "visual_phrases";
  const input = document.querySelector(`[data-slot-input="${slot}"]`);
  const values = promptValueList(item.tags);
  if (!values.length) values.push(...promptValueList(item.traits));
  if (!values.length) values.push(promptAssetDisplayName(item));
  const addition = values.join(", ");
  input.value = [input.value.trim(), addition].filter(Boolean).join(", ");
  switchPromptTab("composer");
  input.focus();
  document.querySelector("#prompt-slot-status").textContent = `已将“${promptAssetDisplayName(item)}”加入${slot}槽。`;
}

function resetPromptCustomForm() {
  document.querySelector("#prompt-custom-form").reset();
  document.querySelector("#prompt-custom-id").value = "";
  document.querySelector("#prompt-custom-mode").textContent = "NEW";
  document.querySelector("#prompt-custom-delete").hidden = true;
  document.querySelector("#prompt-custom-status").textContent = "";
}

function editPromptCustomAsset(item) {
  document.querySelector("#prompt-custom-id").value = String(item.asset_id || "");
  document.querySelector("#prompt-custom-type").value = item.asset_type || "custom";
  document.querySelector("#prompt-custom-name-zh").value = item.name_zh || "";
  document.querySelector("#prompt-custom-name-en").value = item.name_en || "";
  document.querySelector("#prompt-custom-aliases").value = promptValueList(item.aliases).join(", ");
  document.querySelector("#prompt-custom-tags").value = promptValueList(item.tags).join(", ");
  document.querySelector("#prompt-custom-traits").value = [
    ...promptValueList(item.traits),
    ...promptValueList(item.categories).map((value) => `#${value}`),
  ].join(", ");
  document.querySelector("#prompt-custom-mode").textContent = "EDIT";
  document.querySelector("#prompt-custom-delete").hidden = false;
  document.querySelector("#prompt-custom-name-zh").focus();
}

function promptCustomPayload() {
  const traits = splitPromptField(document.querySelector("#prompt-custom-traits").value);
  return {
    asset_type: document.querySelector("#prompt-custom-type").value,
    type: document.querySelector("#prompt-custom-type").value,
    name_zh: document.querySelector("#prompt-custom-name-zh").value.trim(),
    name_en: document.querySelector("#prompt-custom-name-en").value.trim(),
    aliases: splitPromptField(document.querySelector("#prompt-custom-aliases").value),
    tags: splitPromptField(document.querySelector("#prompt-custom-tags").value),
    traits: traits.filter((value) => !value.startsWith("#")),
    categories: traits.filter((value) => value.startsWith("#")).map((value) => value.slice(1)).filter(Boolean),
    provenance: {source: "custom", license: "user-authored"},
  };
}

async function savePromptCustomAsset(event) {
  event.preventDefault();
  const button = document.querySelector("#prompt-custom-save");
  const status = document.querySelector("#prompt-custom-status");
  const assetId = document.querySelector("#prompt-custom-id").value;
  const asset = promptCustomPayload();
  setBusy(button, true, "正在保存…");
  try {
    const data = await api("/api/prompt-assets/custom", {
      method: assetId ? "PUT" : "POST",
      body: JSON.stringify(assetId ? {asset_id: assetId, changes: asset} : asset),
    });
    status.textContent = data.message || (assetId ? "自定义素材已更新。" : "自定义素材已创建。");
    resetPromptCustomForm();
    promptAssetPage = 1;
    await loadPromptAssets({quiet: true});
  } catch (error) {
    status.textContent = `保存失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function deletePromptCustomAsset() {
  const assetId = document.querySelector("#prompt-custom-id").value;
  if (!assetId) return;
  if (!(await confirmAction("删除这个自定义素材？导入素材不能通过此入口删除。", {title: "删除自定义素材", confirmLabel: "确认删除"}))) return;
  const button = document.querySelector("#prompt-custom-delete");
  setBusy(button, true, "正在删除…");
  try {
    await api("/api/prompt-assets/custom", {method: "DELETE", body: JSON.stringify({asset_id: assetId})});
    resetPromptCustomForm();
    await loadPromptAssets({quiet: true});
    showToast("自定义素材已删除");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function importPromptAssets(event) {
  event.preventDefault();
  const button = document.querySelector("#prompt-asset-import");
  const status = document.querySelector("#prompt-asset-import-status");
  const format = document.querySelector("#prompt-asset-import-format").value;
  const mode = document.querySelector("#prompt-asset-import-mode").value;
  const source = document.querySelector("#prompt-asset-import-source").value.trim();
  const license = document.querySelector("#prompt-asset-import-license").value.trim();
  const content = document.querySelector("#prompt-asset-import-content").value;
  if (mode === "replace" && !(await confirmAction(
    "替换整个视觉素材库会删除其他来源的已导入素材，但会保留本次包中的条目。是否继续？",
    {title: "替换整个素材库", confirmLabel: "确认替换"},
  ))) return;
  const contentBytes = typeof TextEncoder === "function"
    ? new TextEncoder().encode(content).byteLength
    : content.length * 3;
  if (contentBytes > 1000 * 1024) {
    status.textContent = `导入内容约 ${(contentBytes / 1048576).toFixed(2)} MiB，超过安全请求上限；请拆分素材包。`;
    document.querySelector("#prompt-asset-import-content").focus();
    return;
  }
  setBusy(button, true, "正在导入…");
  try {
    const data = await api("/api/prompt-assets/import", {
      method: "POST",
      body: JSON.stringify({content, format, source, version: license, provenance: {source, license}, mode}),
    });
    status.textContent = data.message || `素材包已导入 ${Number(data.imported || data.count || 0).toLocaleString()} 项。`;
    document.querySelector("#prompt-asset-import-content").value = "";
    promptAssetPage = 1;
    await loadPromptAssets({quiet: true});
  } catch (error) {
    status.textContent = `导入失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function updatePromptAssetsFromUrl(event) {
  event.preventDefault();
  const button = document.querySelector("#prompt-asset-url-import");
  const status = document.querySelector("#prompt-asset-import-status");
  const url = document.querySelector("#prompt-asset-url").value.trim();
  const source = document.querySelector("#prompt-asset-url-source").value.trim();
  setBusy(button, true, "正在安全获取…");
  try {
    const data = await api("/api/prompt-assets/update-url", {
      method: "POST",
      body: JSON.stringify({url, source, timeout: 30, mode: "merge", provenance: {source, transport: "admin_url"}}),
    });
    status.textContent = data.message || "远程素材包已校验并更新。";
    promptAssetPage = 1;
    await loadPromptAssets({quiet: true});
  } catch (error) {
    status.textContent = `URL 更新失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function visiblePromptAssetPools() {
  const pools = {};
  for (const item of promptAssetItems) {
    const layer = promptAssetSlotMap[item.asset_type];
    if (!layer || layer === "visual_phrases") continue;
    if (!pools[layer]) pools[layer] = [];
    pools[layer].push({
      asset_id: item.asset_id,
      label: promptAssetDisplayName(item),
      tags: promptValueList(item.tags),
      visual_phrases: promptValueList(item.traits),
    });
  }
  return pools;
}

const promptLabTypeLayers = {
  character: "identity",
  outfit: "clothing",
  pose: "pose",
  background: "background",
  artist: "style",
};

const promptLabLibraryTypes = {
  character: "character",
  outfit: "clothing",
  pose: "pose",
  background: "background",
  artist: "artist",
};

function promptLabAssetRecord(item) {
  return {
    asset_id: item.asset_id,
    label: promptAssetDisplayName(item),
    tags: promptValueList(item.tags).slice(0, 16).map((value) => value.slice(0, 160)),
    visual_phrases: promptValueList(item.traits).slice(0, 6).map((value) => value.slice(0, 160)),
  };
}

function promptLabPoolHasType(pools, assetType) {
  const layer = promptLabTypeLayers[assetType];
  const aliases = [assetType, promptLabLibraryTypes[assetType], layer];
  return aliases.some((name) => Array.isArray(pools?.[name]) && pools[name].length > 0);
}

async function loadPromptLabPools(selectedTypes) {
  const pools = visiblePromptAssetPools();
  const missing = selectedTypes.filter((assetType) => !promptLabPoolHasType(pools, assetType));
  if (missing.length) {
    const pages = await Promise.all(missing.map(async (assetType) => {
      const data = await api("/api/prompt-assets/search", {
        method: "POST",
        body: JSON.stringify({
          asset_type: promptLabLibraryTypes[assetType],
          page: 1,
          page_size: 24,
          sort: "name",
        }),
      });
      if (data.fingerprint) promptAssetFingerprint = String(data.fingerprint);
      return [assetType, Array.isArray(data.items) ? data.items : []];
    }));
    for (const [assetType, items] of pages) {
      const layer = promptLabTypeLayers[assetType];
      if (!pools[layer]) pools[layer] = [];
      pools[layer].push(...items.map(promptLabAssetRecord));
    }
  }
  return {
    pools,
    enabledTypes: selectedTypes.filter((assetType) => promptLabPoolHasType(pools, assetType)),
    missingTypes: selectedTypes.filter((assetType) => !promptLabPoolHasType(pools, assetType)),
  };
}

function promptLabBaseLayers() {
  return promptLabUseComposerBase ? promptLayersFromSlots() : {};
}

function promptLabSelectedValues(selector) {
  return [...document.querySelectorAll(`${selector} input:checked`)].map((input) => input.value);
}

function promptLabCandidateCard(candidate) {
  const article = document.createElement("article");
  article.className = `prompt-candidate-card${promptLabSelection === candidate.candidate_id ? " selected" : ""}`;
  article.tabIndex = 0;
  article.dataset.candidateId = candidate.candidate_id;
  const head = document.createElement("header");
  const title = document.createElement("h3");
  title.textContent = `候选 ${candidate.ordinal || "—"}`;
  const badge = document.createElement("span");
  badge.className = "ticket-tag";
  badge.textContent = String(candidate.candidate_id || "").slice(0, 14) || "CANDIDATE";
  head.append(title, badge);
  const layers = document.createElement("dl");
  layers.className = "prompt-candidate-layers";
  const rawLayers = candidate.layers || {};
  for (const [name, label] of [
    ["identity", "身份"], ["clothing", "服装"], ["pose", "姿势"], ["camera", "镜头"],
    ["background", "背景"], ["style", "风格"], ["relation", "关系句"], ["lora", "LoRA"],
  ]) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = promptValueList(rawLayers[name]).join(", ") || "—";
    row.append(term, detail);
    layers.append(row);
  }
  const foot = document.createElement("div");
  foot.className = "prompt-candidate-actions";
  const select = document.createElement("button");
  select.className = promptLabSelection === candidate.candidate_id ? "secondary" : "ghost";
  select.type = "button";
  select.textContent = promptLabSelection === candidate.candidate_id ? "已选择" : "选择比较";
  select.addEventListener("click", () => selectPromptLabCandidate(candidate.candidate_id));
  const confirm = document.createElement("button");
  confirm.className = "primary prompt-lab-confirm-button";
  confirm.type = "button";
  confirm.textContent = document.querySelector("#prompt-plan-save")?.checked === false
    ? "仅确认 Composer"
    : "确认并保存方案";
  confirm.addEventListener("click", async () => {
    selectPromptLabCandidate(candidate.candidate_id);
    await confirmPromptLabCandidate(confirm);
  });
  foot.append(select, confirm);
  const warnings = promptValueList(candidate.warnings);
  article.append(head, layers);
  if (warnings.length) {
    const note = document.createElement("p");
    note.className = "candidate-warning";
    note.textContent = warnings.join(" · ");
    article.append(note);
  }
  article.append(foot);
  article.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectPromptLabCandidate(candidate.candidate_id);
    }
  });
  return article;
}

function renderPromptLabBatch(data) {
  promptLabBatch = data?.batch || data || null;
  const candidates = Array.isArray(promptLabBatch?.candidates) ? promptLabBatch.candidates : [];
  promptLabSelection = candidates[0]?.candidate_id || "";
  const container = document.querySelector("#prompt-lab-candidates");
  container.replaceChildren();
  if (!candidates.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "后端没有返回候选卡。";
    container.append(empty);
  } else {
    for (const candidate of candidates) container.append(promptLabCandidateCard(candidate));
  }
}

function selectPromptLabCandidate(candidateId) {
  promptLabSelection = String(candidateId || "");
  if (!promptLabBatch) return;
  const candidates = Array.isArray(promptLabBatch.candidates) ? promptLabBatch.candidates : [];
  const container = document.querySelector("#prompt-lab-candidates");
  container.replaceChildren(...candidates.map(promptLabCandidateCard));
  const selected = [...container.children].find((item) => item.dataset.candidateId === promptLabSelection);
  if (selected) selected.scrollIntoView({block: "nearest", inline: "nearest"});
}

async function generatePromptLab(event) {
  event.preventDefault();
  const button = document.querySelector("#prompt-lab-generate");
  const status = document.querySelector("#prompt-lab-status");
  const count = Number(document.querySelector("#prompt-lab-count").value);
  if (!Number.isInteger(count) || count < 2 || count > 6) {
    status.textContent = "候选数量必须是 2–6。";
    return;
  }
  const selectedTypes = promptLabSelectedValues("#prompt-lab-types");
  let pools;
  let enabledTypes = selectedTypes;
  let missingTypes = [];
  setBusy(button, true, "正在读取素材…");
  status.textContent = "正在读取所选类别的分页素材池…";
  try {
    const text = document.querySelector("#prompt-lab-pools").value.trim();
    if (text) {
      pools = JSON.parse(text);
      enabledTypes = selectedTypes.filter((assetType) => promptLabPoolHasType(pools, assetType));
      missingTypes = selectedTypes.filter((assetType) => !promptLabPoolHasType(pools, assetType));
    } else {
      if (!promptAssetFingerprint) await loadPromptAssetStatus({quiet: true});
      ({pools, enabledTypes, missingTypes} = await loadPromptLabPools(selectedTypes));
    }
  } catch (_error) {
    status.textContent = "候选素材池读取失败；请检查 JSON 或素材库状态。";
    document.querySelector("#prompt-lab-pools").focus();
    setBusy(button, false);
    return;
  }
  button.textContent = "正在抽取…";
  status.textContent = "正在按固定 Seed 生成可复现候选；不会调用 ComfyUI…";
  try {
    const slots = readPromptSlots();
    const data = await api("/api/prompt-lab/generate", {
      method: "POST",
      body: JSON.stringify({
        seed: document.querySelector("#prompt-lab-seed").value.trim(),
        count,
        base_layers: promptLabBaseLayers(),
        asset_pools: pools,
        locked_layers: promptLabSelectedValues("#prompt-lab-locks"),
        enabled_asset_types: enabledTypes,
        negative_prompt: slots.negative,
        visual_phrases: splitPromptField(slots.visual_phrases),
        asset_library_fingerprint: promptAssetFingerprint,
      }),
    });
    renderPromptLabBatch(data);
    const missingNote = missingTypes.length ? `；无可用素材：${missingTypes.join("、")}` : "";
    status.textContent = data.message || `已生成 ${promptLabBatch?.candidates?.length || 0} 张草稿卡；请明确确认一张${missingNote}。`;
  } catch (error) {
    status.textContent = `候选生成失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function confirmPromptLabCandidate(button) {
  if (!promptLabBatch || !promptLabSelection) {
    document.querySelector("#prompt-lab-status").textContent = "请先生成并选择一张候选卡。";
    return;
  }
  const savePlan = document.querySelector("#prompt-plan-save").checked;
  const planName = document.querySelector("#prompt-plan-name").value.trim();
  const actionText = savePlan
    ? "确认组合所选候选并保存为可在 QQ 调用的方案？这一步不会自动生成图片。"
    : "确认将所选候选送入 Prompt Composer？这一步不会保存方案，也不会生成图片。";
  if (!(await confirmAction(actionText, {title: "确认候选草稿", confirmLabel: savePlan ? "确认并保存" : "仅确认组合", danger: false}))) return;
  setBusy(button, true, "正在确认…");
  try {
    const data = await api("/api/prompt-lab/confirm", {
      method: "POST",
      body: JSON.stringify({
        batch_id: promptLabBatch.batch_id,
        selection: promptLabSelection,
        candidate_id: promptLabSelection,
        asset_library_fingerprint: promptAssetFingerprint,
        save_plan: savePlan,
        plan_name: planName,
      }),
    });
    renderCompositionProof("#prompt-lab-confirm-result", "#prompt-lab-confirm-badge", data, "CONFIRMED");
    const plan = data?.plan || data?.result?.plan || null;
    const planId = String(plan?.plan_id || plan?.id || "");
    document.querySelector("#prompt-lab-status").textContent = data.message || (planId
      ? `方案 ${planId} 已保存；可在 QQ 使用 /方案 ${planId}。`
      : "候选已确认并经过 Composer；未提交 ComfyUI。");
    if (savePlan) await loadPromptPlans({quiet: true});
  } catch (error) {
    document.querySelector("#prompt-lab-status").textContent = `确认失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function copyPromptPlanCommand(planId) {
  const id = String(planId || "").trim();
  if (!id) return;
  const command = `/方案 ${id}`;
  try {
    await navigator.clipboard.writeText(command);
  } catch (_error) {
    const textarea = document.createElement("textarea");
    textarea.value = command;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
  showToast(`已复制：${command}`);
}

function promptPlanCard(plan) {
  const planId = String(plan?.plan_id || plan?.id || "").trim();
  const builtin = Boolean(plan?.builtin) || planId.startsWith("EX-");
  const article = document.createElement("article");
  article.className = `prompt-plan-card${builtin ? " builtin" : ""}`;
  const head = document.createElement("header");
  const heading = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = builtin ? "BUILT-IN EXAMPLE" : "SAVED PLAN";
  const title = document.createElement("h3");
  title.textContent = String(plan?.name || planId || "未命名方案");
  heading.append(eyebrow, title);
  const badge = document.createElement("span");
  badge.className = "ticket-tag";
  badge.textContent = planId || "NO ID";
  head.append(heading, badge);

  const facts = document.createElement("dl");
  facts.className = "prompt-plan-facts";
  for (const [label, value] of [
    ["管线", plan?.pipeline || "base"],
    ["更新", promptTimestamp(plan?.updated_at || plan?.created_at)],
  ]) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = String(value || "—");
    row.append(term, detail);
    facts.append(row);
  }

  const preview = document.createElement("p");
  preview.className = "prompt-plan-preview";
  preview.textContent = String(plan?.positive_prompt || plan?.positive || "未返回提示词预览");
  const actions = document.createElement("div");
  actions.className = "prompt-plan-actions";
  const copy = document.createElement("button");
  copy.className = "secondary";
  copy.type = "button";
  copy.textContent = "复制 QQ 指令";
  copy.disabled = !planId;
  copy.addEventListener("click", () => copyPromptPlanCommand(planId));
  actions.append(copy);
  if (!builtin) {
    const remove = document.createElement("button");
    remove.className = "ghost danger-button";
    remove.type = "button";
    remove.textContent = "删除方案";
    remove.disabled = !planId;
    remove.addEventListener("click", () => deletePromptPlan(planId, plan?.name));
    actions.append(remove);
  }
  article.append(head, facts, preview, actions);
  return article;
}

function renderPromptPlans(data) {
  const items = Array.isArray(data) ? data : (data?.items || data?.plans || data?.results || []);
  promptPlanItems = Array.isArray(items) ? items : [];
  const container = document.querySelector("#prompt-plan-list");
  container.replaceChildren();
  document.querySelector("#prompt-plan-count").textContent = `${promptPlanItems.length} PLANS`;
  if (!promptPlanItems.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state compact-empty";
    empty.textContent = "尚未保存方案；可先确认一张候选卡，或使用内置示例。";
    container.append(empty);
    return;
  }
  for (const plan of promptPlanItems) container.append(promptPlanCard(plan));
}

async function loadPromptPlans({quiet = false} = {}) {
  const status = document.querySelector("#prompt-plan-status");
  status.textContent = "正在读取持久化方案库…";
  try {
    const data = await api("/api/prompt-plans");
    renderPromptPlans(data);
    status.textContent = data?.message || `已读取 ${promptPlanItems.length} 个方案。`;
    return data;
  } catch (error) {
    status.textContent = `方案库读取失败：${error.message}`;
    if (!quiet) showToast(error.message, true);
    return null;
  }
}

async function deletePromptPlan(planId, planName = "") {
  const label = String(planName || planId || "此方案");
  if (!(await confirmAction(`删除自定义方案“${label}”？此操作不会删除素材库或 LoRA。`, {title: "删除 QQ 方案", confirmLabel: "确认删除"}))) return;
  const status = document.querySelector("#prompt-plan-status");
  status.textContent = `正在删除 ${planId}…`;
  try {
    const data = await api("/api/prompt-plans/delete", {
      method: "POST",
      body: JSON.stringify({plan_id: planId}),
    });
    status.textContent = data?.message || `方案 ${planId} 已删除。`;
    await loadPromptPlans({quiet: true});
  } catch (error) {
    status.textContent = `方案删除失败：${error.message}`;
    showToast(error.message, true);
  }
}

function switchLoraView(mode) {
  loraViewMode = mode === "gallery" ? "gallery" : "table";
  const table = loraViewMode === "table";
  document.querySelector("#lora-table-view").hidden = !table;
  document.querySelector("#lora-empty").hidden = !table || loraItems.length > 0;
  document.querySelector("#lora-gallery-view").hidden = table;
  document.querySelector("#lora-gallery-filters").hidden = table;
  for (const [selector, active] of [["#lora-view-table", table], ["#lora-view-gallery", !table]]) {
    const button = document.querySelector(selector);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  writePreference("comfy-anima-lora-view", loraViewMode);
  if (currentPanel === "loras") {
    if (table) searchLoras(null, {skipAutoArchive: true});
    else loadLoraGallery({quiet: true});
  }
}

function safePreviewDataUrl(value) {
  const text = String(value || "");
  return /^data:image\/(?:png|jpeg|webp);base64,[a-z0-9+/=\r\n]+$/iu.test(text) ? text : "";
}

async function loadLoraPreview(image, item) {
  if (!item.preview_key || image.dataset.loaded === "true") return;
  image.dataset.loaded = "true";
  image.classList.add("loading");
  try {
    const data = await api(`/api/loras/preview?key=${encodeURIComponent(item.preview_key)}&fingerprint=${encodeURIComponent(loraGalleryFingerprint)}`);
    const dataUrl = safePreviewDataUrl(data.data_url);
    if (!dataUrl) throw new Error("缩略图接口未返回受支持的图片数据");
    image.src = dataUrl;
    image.classList.remove("loading");
    image.classList.add("ready");
  } catch (error) {
    image.classList.remove("loading");
    image.classList.add("failed");
    image.alt = `${item.display_name || item.name || "LoRA"}（预览不可用）`;
    image.parentElement.dataset.previewError = error.message.slice(0, 120);
  }
}

function observeLoraPreview(image, item) {
  image.__loraVisualItem = item;
  if (!("IntersectionObserver" in window)) {
    loadLoraPreview(image, item);
    return;
  }
  if (!loraPreviewObserver) {
    loraPreviewObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        loraPreviewObserver.unobserve(entry.target);
        loadLoraPreview(entry.target, entry.target.__loraVisualItem || {});
      }
    }, {rootMargin: "240px 0px"});
  }
  loraPreviewObserver.observe(image);
}

function loraGalleryCard(item) {
  const article = document.createElement("article");
  article.className = "lora-gallery-card";
  const media = document.createElement("figure");
  media.className = "lora-preview-frame";
  if (item.preview_key) {
    const image = document.createElement("img");
    image.alt = `${item.display_name || item.name || "LoRA"} 的本地 companion 预览`;
    image.loading = "lazy";
    image.decoding = "async";
    media.append(image);
    observeLoraPreview(image, item);
  } else {
    const missing = document.createElement("span");
    missing.className = "lora-preview-missing";
    missing.textContent = item.preview_status === "remote_only" ? "仅远程预览\n安全策略不代理" : "NO LOCAL\nPREVIEW";
    media.append(missing);
  }
  const body = document.createElement("div");
  body.className = "lora-gallery-body";
  const title = document.createElement("h3");
  title.textContent = item.display_name || item.name || "未命名 LoRA";
  const file = document.createElement("code");
  file.textContent = item.name || "—";
  const badges = document.createElement("div");
  badges.className = "chip-list";
  badges.append(
    chip(loraCategoryLabels[normalizeCategory(item.category)] || "未分类"),
    chip(`元数据 ${item.metadata_status || "unknown"}`, item.metadata_status === "complete" ? "good" : "neutral"),
    chip(`预览 ${item.preview_status || "missing"}`, item.preview_key ? "good" : "bad"),
  );
  if (item.favorite) badges.append(chip("★ 收藏", "good"));
  const fingerprint = document.createElement("small");
  fingerprint.className = "lora-gallery-item-fingerprint";
  fingerprint.textContent = `FILE ${String(item.fingerprint || "—").slice(0, 14)}`;
  const actions = document.createElement("div");
  actions.className = "lora-gallery-actions";
  const detail = document.createElement("button");
  detail.type = "button";
  detail.className = "secondary";
  detail.textContent = "实时资料";
  detail.addEventListener("click", () => openLoraDetail(item, detail));
  actions.append(detail);
  body.append(title, file, badges, fingerprint, actions);
  article.append(media, body);
  return article;
}

function loraGallerySkeletonCard() {
  const article = document.createElement("article");
  article.className = "lora-gallery-card is-skeleton";
  article.setAttribute("aria-hidden", "true");

  const media = document.createElement("div");
  media.className = "lora-preview-frame lora-skeleton-block";

  const body = document.createElement("div");
  body.className = "lora-gallery-body";
  for (const className of ["title", "file", "chips", "fingerprint", "button"]) {
    const block = document.createElement("span");
    block.className = `lora-skeleton-block lora-skeleton-${className}`;
    body.append(block);
  }
  article.append(media, body);
  return article;
}

function renderLoraGallerySkeleton(count = 6) {
  if (loraPreviewObserver) loraPreviewObserver.disconnect();
  const grid = document.querySelector("#lora-gallery-grid");
  const safeCount = Math.max(3, Math.min(8, Number(count) || 6));
  grid.setAttribute("aria-busy", "true");
  grid.replaceChildren(...Array.from({length: safeCount}, () => loraGallerySkeletonCard()));
  document.querySelector("#lora-gallery-empty").hidden = true;
}

function renderLoraGallery(data) {
  loraGalleryItems = Array.isArray(data?.items) ? data.items : [];
  loraGalleryPage = Math.max(1, Number(data?.page || loraGalleryPage || 1));
  loraGalleryPages = Math.max(1, Number(data?.pages || 1));
  loraGalleryFingerprint = String(data?.manifest_fingerprint || data?.fingerprint || "");
  if (loraPreviewObserver) loraPreviewObserver.disconnect();
  const grid = document.querySelector("#lora-gallery-grid");
  grid.setAttribute("aria-busy", "false");
  grid.replaceChildren(...loraGalleryItems.map(loraGalleryCard));
  document.querySelector("#lora-gallery-empty").hidden = loraGalleryItems.length > 0;
  document.querySelector("#lora-gallery-page").textContent = `第 ${loraGalleryPage} / ${loraGalleryPages} 页 · ${Number(data?.total || loraGalleryItems.length).toLocaleString()} 项`;
  document.querySelector("#lora-gallery-prev").disabled = loraGalleryPage <= 1;
  document.querySelector("#lora-gallery-next").disabled = loraGalleryPage >= loraGalleryPages;
  document.querySelector("#lora-gallery-fingerprint").textContent = `MANIFEST ${loraGalleryFingerprint.slice(0, 12) || "—"}`;
}

async function loadLoraGallery({quiet = false} = {}) {
  const status = document.querySelector("#lora-gallery-cache-status");
  status.textContent = "正在读取 LoRA 视觉清单与文件指纹…";
  renderLoraGallerySkeleton(Number(document.querySelector("#lora-gallery-page-size").value));
  try {
    const data = await api("/api/loras/gallery", {
      method: "POST",
      body: JSON.stringify({
        query: document.querySelector("#lora-query").value.trim(),
        categories: promptValueList(document.querySelector("#lora-gallery-category").value),
        metadata_statuses: promptValueList(document.querySelector("#lora-gallery-metadata").value),
        preview_statuses: promptValueList(document.querySelector("#lora-gallery-preview").value),
        favorites_only: document.querySelector("#lora-gallery-favorites").checked,
        page: loraGalleryPage,
        page_size: Number(document.querySelector("#lora-gallery-page-size").value),
      }),
    });
    renderLoraGallery(data);
    const previewCounts = data.preview_counts || {};
    status.textContent = `图库显示 ${loraGalleryItems.length} 项；缓存 ${Number(previewCounts.cached || 0)} · 本地 ${Number(previewCounts.local || 0)} · 缺失 ${Number(previewCounts.missing || 0)}。`;
    return data;
  } catch (error) {
    renderLoraGallery({items: [], page: 1, pages: 1});
    status.textContent = `图库读取失败：${error.message}`;
    if (!quiet) showToast(error.message, true);
    return null;
  }
}

async function loadLoraThumbnailStatus({quiet = false} = {}) {
  try {
    const data = await api("/api/loras/thumbnails/status");
    const warmup = data.warmup || data.status || data;
    const manifest = data.manifest || {};
    const queued = Number(warmup.queued || warmup.pending || 0);
    const completed = Number(warmup.completed || warmup.cached || 0);
    const failed = Number(warmup.failed || 0);
    const available = Number(manifest.preview_counts?.cached || 0) + Number(manifest.preview_counts?.local || 0);
    document.querySelector("#lora-gallery-cache-status").textContent = `缩略图：排队 ${queued} · 本轮完成 ${completed} · 失败 ${failed} · 当前可用 ${available}`;
    return data;
  } catch (error) {
    if (!quiet) showToast(error.message, true);
    return null;
  }
}

async function warmLoraGallery() {
  const button = document.querySelector("#lora-gallery-warm");
  const keys = loraGalleryItems.map((item) => item.preview_key).filter(Boolean);
  setBusy(button, true, "正在排队…");
  try {
    const data = await api("/api/loras/thumbnails/warm", {
      method: "POST",
      body: JSON.stringify({keys, limit: keys.length || Number(document.querySelector("#lora-gallery-page-size").value)}),
    });
    const schedule = data.schedule || data;
    showToast(data.message || `已接受 ${Number(schedule.accepted || 0)} 个缩略图预热任务`);
    const warmup = data.status || data.warmup || {};
    document.querySelector("#lora-gallery-cache-status").textContent = `缩略图预热：排队 ${Number(warmup.queued || 0)} · 完成 ${Number(warmup.completed || 0)} · 失败 ${Number(warmup.failed || 0)}`;
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function clearLoraThumbnailCache() {
  if (!(await confirmAction("清理插件生成的 LoRA 缩略图缓存？不会删除 LoRA、companion 原图或 Civitai 元数据。", {title: "清理缩略图缓存", confirmLabel: "确认清理", danger: false}))) return;
  const button = document.querySelector("#lora-gallery-cache-clear");
  setBusy(button, true, "正在清理…");
  try {
    const data = await api("/api/loras/thumbnails/cache", {method: "DELETE"});
    showToast(data.message || `已清理 ${Number(data.removed || 0)} 个缓存文件`);
    document.querySelector("#lora-gallery-cache-status").textContent = `缓存清理完成；释放 ${Number(data.removed_bytes || data.bytes_removed || 0).toLocaleString()} bytes。图库数据未变，按“刷新图库”可重读预览状态。`;
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function loadCurrentPanel() {
  if (currentPanel === "overview") await loadBootstrap();
  else if (currentPanel === "settings") await Promise.all([loadBootstrap(), loadConfigProfiles({quiet: true})]);
  else if (currentPanel === "loras") {
    if (loraViewMode === "gallery") await loadLoraGallery();
    else await searchLoras(null);
  }
  else if (currentPanel === "presets") await loadPresets();
  else if (currentPanel === "models") await loadModels();
  else if (currentPanel === "tasks") await loadTasks();
  else if (currentPanel === "console") await loadConsoleLogs({reset: true});
  else if (currentPanel === "prompt") await loadPromptWorkbench();
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
  if (name === "loras") {
    if (loraViewMode === "gallery") loadLoraGallery({quiet: true});
    else searchLoras(null);
  }
  if (name === "presets") loadPresets();
  if (name === "models") loadModels();
  if (name === "tasks") loadTasks();
  else stopTaskPolling();
  if (name === "console") loadConsoleLogs({reset: consoleEntries.length === 0});
  else stopConsolePolling();
  if (name === "prompt") loadPromptWorkbench({quiet: true});
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
document.querySelector("#lora-search-form").addEventListener("submit", (event) => {
  if (loraViewMode === "gallery") {
    event.preventDefault();
    loraGalleryPage = 1;
    loadLoraGallery();
  } else {
    searchLoras(event);
  }
});
document.querySelector("#lora-refresh").addEventListener("click", refreshLoras);
document.querySelector("#lora-download-form").addEventListener("submit", downloadLora);
document.querySelector("#lora-view-table").addEventListener("click", () => switchLoraView("table"));
document.querySelector("#lora-view-gallery").addEventListener("click", () => switchLoraView("gallery"));
document.querySelector("#lora-gallery-refresh").addEventListener("click", () => loadLoraGallery());
document.querySelector("#lora-gallery-warm").addEventListener("click", warmLoraGallery);
document.querySelector("#lora-gallery-cache-status-refresh").addEventListener("click", () => loadLoraThumbnailStatus());
document.querySelector("#lora-gallery-cache-clear").addEventListener("click", clearLoraThumbnailCache);
for (const selector of ["#lora-gallery-category", "#lora-gallery-metadata", "#lora-gallery-preview", "#lora-gallery-favorites", "#lora-gallery-page-size"]) {
  document.querySelector(selector).addEventListener("change", () => {
    loraGalleryPage = 1;
    loadLoraGallery({quiet: true});
  });
}
document.querySelector("#lora-gallery-prev").addEventListener("click", () => {
  if (loraGalleryPage <= 1) return;
  loraGalleryPage -= 1;
  loadLoraGallery({quiet: true});
});
document.querySelector("#lora-gallery-next").addEventListener("click", () => {
  if (loraGalleryPage >= loraGalleryPages) return;
  loraGalleryPage += 1;
  loadLoraGallery({quiet: true});
});
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
document.querySelector("#preset-cancel-edit").addEventListener("click", resetPresetEditor);
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
document.querySelector("#prompt-diagnostic-form").addEventListener("submit", diagnosePrompt);
document.querySelector("#prompt-diagnostics-clear").addEventListener("click", clearPromptDiagnostics);
document.querySelector("#prompt-index-update").addEventListener("click", () => updateDanbooruIndex("url"));
document.querySelector("#prompt-index-official-update").addEventListener("click", () => updateDanbooruIndex("official_api"));
document.querySelector("#prompt-index-task").addEventListener("click", () => {
  if (promptIndexTaskRunId) openTaskCenter(promptIndexTaskRunId);
});
document.querySelector("#prompt-status-refresh").addEventListener("click", () => loadPromptStatus());
document.querySelector("#prompt-experiments-refresh").addEventListener("click", () => loadExperimentalProfiles());
document.querySelector("#prompt-workbench-tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-prompt-tab]");
  if (button) switchPromptTab(button.dataset.promptTab);
});
document.querySelector("#prompt-slot-form").addEventListener("submit", composePromptSlots);
document.querySelector("#prompt-slots-clear").addEventListener("click", clearUnlockedPromptSlots);
document.querySelector("#prompt-open-assets").addEventListener("click", () => switchPromptTab("assets", {focus: true}));
document.querySelector("#prompt-asset-search-form").addEventListener("submit", (event) => {
  promptAssetPage = 1;
  searchPromptAssets(event);
  loadPromptAssetFacets({quiet: true});
});
document.querySelector("#prompt-assets-sync-local").addEventListener("click", syncLocalPromptAssets);
document.querySelector("#prompt-asset-type").addEventListener("change", () => {
  promptAssetPage = 1;
  searchPromptAssets(null, {quiet: true});
  loadPromptAssetFacets({quiet: true});
});
document.querySelector("#prompt-asset-page-size").addEventListener("change", () => {
  promptAssetPage = 1;
  searchPromptAssets(null, {quiet: true});
});
document.querySelector("#prompt-asset-favorites-only").addEventListener("change", () => {
  promptAssetPage = 1;
  searchPromptAssets(null, {quiet: true});
  loadPromptAssetFacets({quiet: true});
});
document.querySelector("#prompt-asset-prev").addEventListener("click", () => {
  if (promptAssetPage <= 1) return;
  promptAssetPage -= 1;
  searchPromptAssets(null, {quiet: true});
});
document.querySelector("#prompt-asset-next").addEventListener("click", () => {
  if (promptAssetPage >= promptAssetPages) return;
  promptAssetPage += 1;
  searchPromptAssets(null, {quiet: true});
});
document.querySelector("#prompt-custom-form").addEventListener("submit", savePromptCustomAsset);
document.querySelector("#prompt-custom-reset").addEventListener("click", resetPromptCustomForm);
document.querySelector("#prompt-custom-delete").addEventListener("click", deletePromptCustomAsset);
document.querySelector("#prompt-asset-import-form").addEventListener("submit", importPromptAssets);
document.querySelector("#prompt-asset-url-form").addEventListener("submit", updatePromptAssetsFromUrl);
document.querySelector("#prompt-lab-form").addEventListener("submit", generatePromptLab);
document.querySelector("#prompt-plans-refresh").addEventListener("click", () => loadPromptPlans());
document.querySelector("#prompt-plan-save").addEventListener("change", (event) => {
  document.querySelector("#prompt-plan-name").disabled = !event.target.checked;
  for (const button of document.querySelectorAll(".prompt-lab-confirm-button")) {
    button.textContent = event.target.checked ? "确认并保存方案" : "仅确认 Composer";
  }
});
document.querySelector("#prompt-lab-use-composer").addEventListener("click", (event) => {
  promptLabUseComposerBase = !promptLabUseComposerBase;
  event.currentTarget.classList.toggle("active", promptLabUseComposerBase);
  event.currentTarget.textContent = promptLabUseComposerBase ? "已读取构图台基础层" : "不读取构图台基础层";
  document.querySelector("#prompt-lab-status").textContent = promptLabUseComposerBase
    ? "候选会保留构图台基础层与锁定槽。"
    : "候选从空基础层开始。";
});
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
initializePromptSubnav();
switchLoraView(readPreference("comfy-anima-lora-view", "table"));
updateSelectionUI();
loadBootstrap()
  .then(() => restoreActiveLoraTask())
  .catch((error) => showToast(error.message, true));
