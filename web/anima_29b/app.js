"use strict";

let bootstrap = null;
let loras = [];
let loraFilter = "eligible";

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("登录已失效");
  }
  const payload = await response.json();
  if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload.data;
}

function setStatus(text, error = false) {
  const node = document.querySelector("#page-status");
  node.textContent = text || "";
  node.classList.toggle("error", error);
}

function familySet(item) {
  return new Set((item.compatible_model_families || item.archive?.compatible_model_families || []).map((v) => String(v).toLowerCase()));
}

function mode(item) {
  return String(item.compatibility_mode || item.archive?.compatibility_mode || "unknown").toLowerCase();
}

function eligible(item) {
  const families = familySet(item);
  return (mode(item) === "native_29b" && families.has("anima_29b_40l"))
    || (mode(item) === "legacy_projection" && families.has("anima_legacy_28l"));
}

function renderContract(settings) {
  const is29b = settings.model_profile_id === "anima_29b" && settings.model_family === "anima_29b_40l";
  document.querySelector("#active-profile").textContent = is29b ? "Anima 2.9B · anima_29b_40l" : `当前为 ${settings.model_profile_id || "Legacy"}`;
  document.querySelector("#unet").textContent = settings.unet_model_name || "未登记";
  document.querySelector("#patch-node").textContent = settings.lora_patch_node_type || "不需要";
  document.querySelector("#patch-receipt").textContent = settings.lora_patch_contract_id || "不需要";
  const state = document.querySelector("#contract-state");
  state.textContent = is29b ? "40-layer contract" : "未激活";
  state.className = `badge ${is29b ? "good" : "bad"}`;
  document.querySelector("#contract-note").textContent = is29b
    ? "2.9B Profile 已激活；提交门禁会再次检查模型三件套、工作流 manifest 与 patch receipt。"
    : "请先启用 Anima 2.9B。Legacy 设置和 LoRA 不会在本页被改写。";
}

function renderWorkflows(data) {
  const list = document.querySelector("#workflow-list");
  list.replaceChildren();
  const rows = (data.workflow_runtime?.pipelines || []).filter((item) => String(item.profile_id || "").includes("29b") || String(item.display_name || "").includes("2.9B"));
  for (const item of rows) {
    const row = document.createElement("div");
    row.className = "workflow-row";
    const title = document.createElement("strong");
    title.textContent = item.display_name || item.id;
    const meta = document.createElement("span");
    meta.className = `badge ${item.ready ? "good" : "bad"}`;
    meta.textContent = item.ready ? "READY" : (item.error || "UNAVAILABLE");
    row.append(title, meta);
    list.append(row);
  }
  if (!rows.length) list.innerHTML = '<p class="muted">没有可用的 2.9B 工作流；这通常表示模型或 40-layer manifest 尚未适配。</p>';
}

function renderLoras() {
  const list = document.querySelector("#lora-list");
  list.replaceChildren();
  const visible = loras.filter((item) => {
    if (loraFilter === "eligible") return eligible(item);
    if (loraFilter === "native_29b") return mode(item) === "native_29b";
    if (loraFilter === "legacy_projection") return mode(item) === "legacy_projection";
    return Boolean(familySet(item).size);
  });
  for (const item of visible) {
    const row = document.createElement("div");
    row.className = "lora-row";
    const title = document.createElement("strong");
    title.textContent = item.name;
    const meta = document.createElement("span");
    meta.className = "lora-meta";
    const tag = document.createElement("span");
    tag.className = `chip ${eligible(item) ? "good" : "neutral"}`;
    tag.textContent = mode(item) === "native_29b" ? "原生 2.9B" : mode(item) === "legacy_projection" ? "Legacy 投影" : "未声明";
    meta.append(tag);
    row.append(title, meta);
    list.append(row);
  }
  if (!visible.length) list.innerHTML = '<p class="muted">当前筛选没有可用 LoRA。请在 Legacy 页面完成人工模型族审核，或登记 2.9B 原生 LoRA。</p>';
}

async function load() {
  try {
    setStatus("正在读取 2.9B 运行态…");
    bootstrap = await api("/api/bootstrap");
    renderContract(bootstrap.settings || {});
    renderWorkflows(bootstrap);
    document.querySelector("#version").textContent = `v${bootstrap.version}`;
    document.querySelector("#queue").textContent = `队列：${bootstrap.running_jobs || 0} 运行 · ${bootstrap.queued_jobs || 0} 等待`;
    document.querySelector("#settings-form").elements.default_width.value = bootstrap.settings.default_width || 1024;
    document.querySelector("#settings-form").elements.default_height.value = bootstrap.settings.default_height || 1024;
    document.querySelector("#settings-form").elements.default_generation_pipeline.value = bootstrap.settings.default_generation_pipeline || "base";
    document.querySelector("#settings-form").elements.max_total_dynamic_loras.value = bootstrap.settings.max_total_dynamic_loras || 4;
    document.querySelector("#settings-form").elements.enable_inpaint.checked = Boolean(bootstrap.settings.enable_inpaint);
    const data = await api("/api/loras?q=&limit=200");
    loras = data.items || [];
    renderLoras();
    setStatus("2.9B 页面状态已更新");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function switchProfile(name) {
  try {
    const profiles = await api("/api/config-profiles");
    const profile = (profiles.items || []).find((item) => item.name === name || item.settings?.model_profile_id === name);
    if (!profile) throw new Error(`未找到 ${name} Profile`);
    document.querySelector("#profile-status").textContent = "正在切换并重载…";
    await api("/api/config-profiles/switch", {method:"POST", body: JSON.stringify({identifier: profile.name})});
    document.querySelector("#profile-status").textContent = "切换已提交，等待插件重载。";
    window.setTimeout(load, 2800);
  } catch (error) {
    document.querySelector("#profile-status").textContent = error.message;
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const settings = bootstrap?.settings || {};
  if (settings.model_profile_id !== "anima_29b") {
    document.querySelector("#settings-status").textContent = "请先启用 Anima 2.9B，再保存此页面的设置。";
    return;
  }
  const form = event.currentTarget;
  const payload = {
    model_profile_id: "anima_29b",
    model_family: "anima_29b_40l",
    default_width: Number(form.elements.default_width.value),
    default_height: Number(form.elements.default_height.value),
    default_generation_pipeline: form.elements.default_generation_pipeline.value,
    max_total_dynamic_loras: Number(form.elements.max_total_dynamic_loras.value),
    enable_inpaint: form.elements.enable_inpaint.checked,
  };
  try {
    const result = await api("/api/settings", {method:"PUT", body: JSON.stringify(payload)});
    document.querySelector("#settings-status").textContent = result.message || "已保存，等待重载。";
  } catch (error) {
    document.querySelector("#settings-status").textContent = error.message;
  }
}

document.querySelector("#refresh").addEventListener("click", load);
document.querySelector("#check-workflows").addEventListener("click", async () => { try { await api("/api/workflows/check"); await load(); } catch (error) { setStatus(error.message, true); } });
document.querySelector("#search-loras").addEventListener("click", load);
document.querySelector("#activate-29b").addEventListener("click", () => switchProfile("anima_29b"));
document.querySelector("#activate-legacy").addEventListener("click", () => switchProfile("anima_legacy"));
document.querySelector("#settings-form").addEventListener("submit", saveSettings);
for (const button of document.querySelectorAll(".filter")) button.addEventListener("click", () => { loraFilter = button.dataset.filter; document.querySelectorAll(".filter").forEach((item) => item.classList.toggle("active", item === button)); renderLoras(); });
load();
