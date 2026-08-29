// Talks to formharvester.gui.api.Api over the pywebview bridge.

let state = null;
let pollTimer = null;
let activeReviewId = null;
let previousLlmProvider = null;
const autosaveTimers = { settings: null, profile: null };
const autosaveRequests = { settings: null, profile: null };
const autosavePending = new Set();
let autosaveInFlight = 0;
let autosaveError = false;

const defaultLlmModels = {
  openai: "gpt-5",
  anthropic: "claude-sonnet-4-20250514",
  deepseek: "deepseek-v4-flash",
};

const llmModelHints = {
  openai: "OpenAI default: gpt-5",
  anthropic: "Anthropic default: claude-sonnet-4-20250514",
  deepseek: "DeepSeek default: deepseek-v4-flash",
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// --- helpers ------------------------------------------------------------

function get(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

function set(obj, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  const target = keys.reduce((o, k) => (o[k] = o[k] || {}), obj);
  target[last] = value;
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 3200);
}

function readInput(el) {
  if (el.type === "checkbox") return el.checked;
  if (el.type === "number") return el.value === "" ? 0 : Number(el.value);
  return el.value;
}

function writeInput(el, value) {
  if (el.type === "checkbox") el.checked = Boolean(value);
  else el.value = value == null ? "" : value;
}

function renderAutosaveStatus() {
  const status = $("#autosave-status");
  const text = $("#autosave-status-text");
  if (!status || !text) return;

  let mode = "saved";
  let message = "All changes saved";
  if (autosaveInFlight) {
    mode = "saving";
    message = "Saving changes…";
  } else if (autosavePending.size) {
    mode = "pending";
    message = "Unsaved changes";
  } else if (autosaveError) {
    mode = "error";
    message = "Save failed";
  }
  status.classList.remove("saved", "saving", "pending", "error");
  status.classList.add(mode);
  text.textContent = message;
}

function scheduleAutosave(scope) {
  autosavePending.add(scope);
  autosaveError = false;
  renderAutosaveStatus();
  if (autosaveTimers[scope]) clearTimeout(autosaveTimers[scope]);
  autosaveTimers[scope] = setTimeout(() => persistAutosave(scope), 650);
}

async function persistAutosave(scope) {
  if (autosaveRequests[scope]) return autosaveRequests[scope];

  const task = (async () => {
    autosaveTimers[scope] = null;
    if (!state || !autosavePending.has(scope)) {
      renderAutosaveStatus();
      return true;
    }

    autosavePending.delete(scope);
    autosaveInFlight += 1;
    renderAutosaveStatus();

    let result;
    try {
      result = scope === "settings"
        ? await window.pywebview.api.save_settings(collectSettings())
        : await window.pywebview.api.save_profile(collectProfile());
    } catch (error) {
      result = { ok: false, error: error?.message || "The settings bridge was unavailable." };
    }

    if (!result.ok) {
      autosaveError = true;
      toast("Autosave failed: " + result.error, true);
    }
    autosaveInFlight -= 1;
    renderAutosaveStatus();
    return Boolean(result.ok);
  })();

  autosaveRequests[scope] = task;
  try {
    return await task;
  } finally {
    if (autosaveRequests[scope] === task) autosaveRequests[scope] = null;
  }
}

async function flushAutosave(scope) {
  if (autosaveTimers[scope]) {
    clearTimeout(autosaveTimers[scope]);
    autosaveTimers[scope] = null;
  }
  if (autosaveRequests[scope]) {
    const completed = await autosaveRequests[scope];
    if (!completed) return false;
  }
  if (autosavePending.has(scope)) return persistAutosave(scope);
  return true;
}

function bindAutosave() {
  $$("[data-setting]").forEach((el) => {
    const eventName = el.type === "checkbox" || el.tagName === "SELECT" ? "change" : "input";
    el.addEventListener(eventName, () => {
      scheduleAutosave("settings");
      if (el.dataset.setting.startsWith("llm.")) updateCampaignContentMode();
    });
  });
  $$("[data-profile], [data-profile-list]").forEach((el) => {
    el.addEventListener("input", () => scheduleAutosave("profile"));
  });
}

function updateCampaignContentMode(seedPrompts = false) {
  const enabled = Boolean($("#llm-enabled")?.checked);
  const directFields = $("#direct-content-fields");
  const promptFields = $("#llm-prompt-fields");
  const description = $("#content-mode-description");
  const stateBadge = $("#content-mode-state");

  if (directFields) directFields.hidden = enabled;
  if (promptFields) promptFields.hidden = !enabled;
  if (description) {
    description.textContent = enabled
      ? "Instructions for the LLM; generated text is submitted."
      : "Text submitted exactly as written.";
  }
  if (stateBadge) {
    stateBadge.textContent = enabled ? "LLM prompt" : "direct";
    stateBadge.classList.toggle("on", enabled);
  }

  if (enabled && seedPrompts) {
    const directSubject = $('[data-profile="form_fill.subject"]');
    const directMessage = $('[data-profile="form_fill.message"]');
    const subjectPrompt = $('[data-profile="form_fill.subject_prompt"]');
    const messagePrompt = $('[data-profile="form_fill.message_prompt"]');
    let seeded = false;
    if (subjectPrompt && !subjectPrompt.value.trim() && directSubject?.value.trim()) {
      subjectPrompt.value = directSubject.value;
      seeded = true;
    }
    if (messagePrompt && !messagePrompt.value.trim() && directMessage?.value.trim()) {
      messagePrompt.value = directMessage.value;
      seeded = true;
    }
    if (seeded) scheduleAutosave("profile");
  }

  const provider = $("#llm-provider")?.value || "openai";
  const providerNames = { openai: "OpenAI", anthropic: "Anthropic", deepseek: "DeepSeek" };
  const keyInput = $('[data-setting="llm.' + provider + '_api_key"]');
  const hasKey = Boolean(keyInput?.value.trim());
  const warning = $("#llm-key-warning");
  const warningText = $("#llm-key-warning-text");
  if (warning) warning.hidden = !enabled || hasKey;
  if (warningText) {
    warningText.textContent = (providerNames[provider] || provider) +
      " API key is not configured. Open Settings before running.";
  }
}

function updateConditionalFields() {
  const llmProvider = $("#llm-provider")?.value || "openai";

  ["openai", "anthropic", "deepseek"].forEach((provider) => {
    const panel = $("#llm-provider-" + provider);
    if (panel) panel.hidden = provider !== llmProvider;
  });

  const modelHint = $("#llm-model-hint");
  if (modelHint) modelHint.textContent = llmModelHints[llmProvider] || "provider default";
  const model = $("#llm-model");
  if (model) model.placeholder = "e.g. " + (defaultLlmModels[llmProvider] || "model-name");

  const captchaProvider = $("#captcha-provider")?.value || "auto";
  const captchaState = $("#captcha-state");
  if (captchaState) {
    captchaState.textContent = captchaProvider === "auto" ? "auto" : captchaProvider;
    captchaState.classList.toggle("on", captchaProvider !== "none");
  }
  ["auto", "2captcha", "deathbycaptcha", "none"].forEach((provider) => {
    const panel = $("#captcha-provider-" + provider);
    if (panel) panel.hidden = provider !== captchaProvider;
  });
  updateCampaignContentMode();
}

function renderCampaignSelect(id) {
  const select = $(id);
  if (!select) return;
  select.innerHTML = "";
  const names = state.profiles.length ? state.profiles : [state.profile.name];
  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    option.selected = name === state.settings.active_profile;
    select.appendChild(option);
  }
}

function selectPanel(panelName) {
  $$("nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.panel === panelName);
  });
  $$(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === "panel-" + panelName);
  });
}

// --- rendering ----------------------------------------------------------

function render() {
  $("#version").textContent = "v" + state.version;
  $("#home-path").textContent = "config: " + state.home;

  renderCampaignSelect("#profile-select");
  renderCampaignSelect("#campaign-editor-select");
  const campaignName = $("#campaign-name");
  if (campaignName) campaignName.value = state.profile.name || "";
  const campaignExists = state.profiles.includes(state.profile.name);
  const campaignActionsDisabled = state.running || state.profiles.length <= 1;
  const renameButton = $("#btn-rename-campaign");
  const deleteButton = $("#btn-delete-campaign");
  if (renameButton) renameButton.disabled = state.running || !campaignExists;
  if (deleteButton) {
    deleteButton.disabled = campaignActionsDisabled;
    deleteButton.title = state.profiles.length <= 1
      ? "Keep at least one campaign configured."
      : "";
  }
  const campaignStatus = $("#campaign-status");
  const queryCount = (state.profile.queries || []).length;
  if (campaignStatus) {
    campaignStatus.textContent = queryCount
      ? queryCount + " quer" + (queryCount === 1 ? "y" : "ies")
      : "needs queries";
    campaignStatus.classList.toggle("on", queryCount > 0);
  }

  $$("[data-setting]").forEach((el) => writeInput(el, get(state.settings, el.dataset.setting)));
  $$("[data-profile]").forEach((el) => writeInput(el, get(state.profile, el.dataset.profile)));
  $$("[data-profile-list]").forEach((el) => {
    el.value = (get(state.profile, el.dataset.profileList) || []).join("\n");
  });
  previousLlmProvider = get(state.settings, "llm.provider");
  updateConditionalFields();
  renderPolicyState();
  renderLeadMetrics(state.lead_metrics || {});
  renderHealth(state.health || {});
}

function renderPolicyState() {
  const enabled = Boolean(get(state.profile, "policy.autopilot_enabled"));
  const badge = $("#policy-state");
  if (!badge) return;
  badge.textContent = enabled ? "autopilot" : "manual";
  badge.classList.toggle("on", enabled);
}

function renderLeadMetrics(metrics) {
  const values = {
    total: metrics.total || 0,
    qualified: metrics.qualified || 0,
    submitted: metrics.submitted || 0,
    average_score: metrics.average_score || 0,
  };
  if ($("#metric-total")) $("#metric-total").textContent = values.total;
  if ($("#metric-qualified")) $("#metric-qualified").textContent = values.qualified;
  if ($("#metric-submitted")) $("#metric-submitted").textContent = values.submitted;
  if ($("#metric-average")) $("#metric-average").textContent = values.average_score;
}

function renderHealth(health) {
  const labels = { llm: "LLM", captcha: "CAPTCHA" };
  for (const [key, label] of Object.entries(labels)) {
    const chip = $("#" + key + "-health");
    if (!chip) continue;
    const result = health?.[key] || { state: "checking", detail: "checking..." };
    const stateName = ["ok", "warning", "checking", "disabled"].includes(result.state)
      ? result.state
      : "warning";
    chip.classList.remove("ok", "warning", "checking", "disabled");
    chip.classList.add(stateName);
    chip.title = label + ": " + (result.detail || "unknown");
    chip.setAttribute("aria-label", chip.title);
  }
}

function appendLeadDetail(container, label, value) {
  const row = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = label + ": ";
  row.append(strong, document.createTextNode(value || "none"));
  container.appendChild(row);
}

function renderLeads(payload) {
  renderLeadMetrics(payload.metrics || {});
  const cards = $("#lead-cards");
  const empty = $("#leads-empty");
  if (!cards || !empty) return;
  cards.replaceChildren();
  empty.hidden = Boolean(payload.leads?.length);
  for (const lead of payload.leads || []) {
    const card = document.createElement("article");
    card.className = "lead-card";

    const header = document.createElement("div");
    header.className = "lead-card-header";
    const titleGroup = document.createElement("div");
    const title = document.createElement("div");
    title.className = "lead-card-title";
    title.textContent = lead.domain;
    const meta = document.createElement("div");
    meta.className = "lead-card-meta";
    meta.textContent = lead.url + " · " + lead.status;
    titleGroup.append(title, meta);
    const score = document.createElement("div");
    score.className = "lead-card-score";
    score.textContent = Math.round(lead.score || 0) + "/100";
    header.append(titleGroup, score);
    card.appendChild(header);

    const details = document.createElement("div");
    details.className = "lead-card-details";
    const technologyNames = (lead.technologies || []).map((item) => item.name).join(", ");
    appendLeadDetail(details, "Technologies", technologyNames);
    appendLeadDetail(details, "Emails", (lead.emails || []).join(", "));
    appendLeadDetail(details, "Why", (lead.reasons || []).join(" · "));
    if (lead.draft_subject || lead.draft_message) appendLeadDetail(details, "Draft", lead.draft_subject);
    card.appendChild(details);

    const actions = document.createElement("div");
    actions.className = "actions lead-card-actions";
    const auditButton = document.createElement("button");
    auditButton.className = "btn";
    auditButton.textContent = "Audit";
    auditButton.addEventListener("click", async () => {
      const result = await window.pywebview.api.get_lead_audit(lead.id);
      if (result.ok) toast(result.events.length + " audit events recorded for " + lead.domain + ".");
    });
    actions.appendChild(auditButton);
    const suppressButton = document.createElement("button");
    suppressButton.className = lead.suppressed ? "btn" : "btn danger";
    suppressButton.textContent = lead.suppressed ? "Unsuppress" : "Suppress";
    suppressButton.addEventListener("click", async () => {
      const method = lead.suppressed ? "unsuppress_lead" : "suppress_lead";
      const result = await window.pywebview.api[method](lead.id);
      if (!result.ok) return toast(result.error, true);
      await refreshLeads();
      toast(lead.suppressed ? "Lead restored." : "Lead suppressed.");
    });
    actions.appendChild(suppressButton);
    card.appendChild(actions);
    cards.appendChild(card);
  }
}

function setRunning(running) {
  $("#status-dot").classList.toggle("running", running);
  $("#status-text").textContent = running ? "harvesting" : "idle";
  $("#btn-start").disabled = running;
  $("#btn-stop").disabled = !running;
}

function renderReview(review) {
  const dialog = $("#review-dialog");
  if (!review) {
    activeReviewId = null;
    dialog.hidden = true;
    return;
  }
  if (activeReviewId === review.id) return;

  activeReviewId = review.id;
  $("#review-target").textContent = review.url;
  $("#review-subject").value = review.subject || "";
  $("#review-message").value = review.message || "";
  dialog.hidden = false;
  $("#review-subject").focus();
}

function setReviewBusy(busy) {
  $("#btn-review-skip").disabled = busy;
  $("#btn-review-approve").disabled = busy;
}

function appendLines(lines) {
  if (!lines.length) return;
  const box = $("#console");
  const empty = box.querySelector(".empty");
  if (empty) empty.remove();

  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  for (const line of lines) {
    const div = document.createElement("div");
    div.className = "line";
    div.textContent = line;
    box.appendChild(div);
  }
  if (atBottom) box.scrollTop = box.scrollHeight;
}

// --- actions ------------------------------------------------------------

async function reload() {
  state = await window.pywebview.api.get_state();
  render();
  await refreshLeads();
  setRunning(state.running);
  renderReview(state.review);
}

async function refreshLeads() {
  if (!window.pywebview?.api?.get_leads) return;
  const status = $("#lead-status-filter")?.value || null;
  const payload = await window.pywebview.api.get_leads(status);
  renderLeads(payload);
}

function collectSettings() {
  const next = JSON.parse(JSON.stringify(state.settings));
  $$("[data-setting]").forEach((el) => set(next, el.dataset.setting, readInput(el)));
  return next;
}

function collectProfile() {
  const next = JSON.parse(JSON.stringify(state.profile));
  $$("[data-profile]").forEach((el) => set(next, el.dataset.profile, readInput(el)));
  $$("[data-profile-list]").forEach((el) => {
    set(next, el.dataset.profileList, el.value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean));
  });
  return next;
}

async function start() {
  const result = await window.pywebview.api.start();
  if (!result.ok) return toast(result.error, true);
  $("#console").innerHTML = "";
  setRunning(true);
  toast("Harvest started.");
}

async function poll() {
  if (!window.pywebview) return;
  const { lines, running, review, lead_metrics, health } = await window.pywebview.api.poll();
  appendLines(lines);
  renderLeadMetrics(lead_metrics || {});
  renderHealth(health || {});
  setRunning(running);
  renderReview(review);
}

// --- wiring -------------------------------------------------------------

$$("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    selectPanel(button.dataset.panel);
    if (button.dataset.panel === "leads") refreshLeads();
  });
});

$("#btn-start").addEventListener("click", start);

$("#llm-provider").addEventListener("change", (event) => {
  const model = $("#llm-model");
  const oldDefault = defaultLlmModels[previousLlmProvider];
  if (!model.value.trim() || model.value.trim() === oldDefault) {
    model.value = defaultLlmModels[event.target.value] || "";
  }
  previousLlmProvider = event.target.value;
  updateConditionalFields();
});

$("#llm-enabled").addEventListener("change", () => {
  updateCampaignContentMode(true);
  updateConditionalFields();
});
$("#captcha-provider").addEventListener("change", updateConditionalFields);
$("#lead-status-filter").addEventListener("change", refreshLeads);
$("#btn-refresh-leads").addEventListener("click", refreshLeads);
$("#btn-export-leads").addEventListener("click", async () => {
  const result = await window.pywebview.api.export_leads();
  if (result.ok) toast("Leads exported to " + result.path + ".");
  else toast(result.error, true);
});
$("#lead-status-filter").addEventListener("change", refreshLeads);
$("#btn-refresh-leads").addEventListener("click", refreshLeads);
$("#btn-export-leads").addEventListener("click", async () => {
  const result = await window.pywebview.api.export_leads();
  if (result.ok) toast("Leads exported to " + result.path + ".");
  else toast(result.error, true);
});

$("#btn-stop").addEventListener("click", async () => {
  const result = await window.pywebview.api.stop();
  if (!result.ok) toast(result.error, true);
});

$("#btn-clear").addEventListener("click", () => {
  $("#console").innerHTML = '<span class="empty">Cleared.</span>';
});

$("#btn-review-approve").addEventListener("click", async () => {
  if (!activeReviewId) return;
  setReviewBusy(true);
  const result = await window.pywebview.api.approve_review(
    activeReviewId,
    $("#review-subject").value,
    $("#review-message").value,
  );
  setReviewBusy(false);
  if (!result.ok) toast(result.error, true);
});

$("#btn-review-skip").addEventListener("click", async () => {
  if (!activeReviewId) return;
  setReviewBusy(true);
  const result = await window.pywebview.api.skip_review(activeReviewId);
  setReviewBusy(false);
  if (!result.ok) toast(result.error, true);
});

async function useCampaign(name) {
  if (!await flushAutosave("profile")) return;
  const result = await window.pywebview.api.use_profile(name);
  if (!result.ok) return toast(result.error, true);
  await reload();
  toast("Now using the " + name + " campaign.");
}

$("#profile-select").addEventListener("change", (event) => useCampaign(event.target.value));
$("#campaign-editor-select").addEventListener("change", (event) => useCampaign(event.target.value));

$("#btn-edit-campaign").addEventListener("click", () => selectPanel("campaign"));

$("#btn-new-campaign").addEventListener("click", () => {
  selectPanel("campaign");
  $("#new-profile").focus();
});

$("#btn-open-llm-settings").addEventListener("click", () => {
  selectPanel("settings");
  const provider = $("#llm-provider").value || "openai";
  const keyInput = $('[data-setting="llm.' + provider + '_api_key"]');
  if (keyInput) keyInput.focus();
});

$("#btn-create").addEventListener("click", async () => {
  const input = $("#new-profile");
  if (!await flushAutosave("profile")) return;
  const result = await window.pywebview.api.create_profile(input.value);
  if (!result.ok) return toast(result.error, true);
  input.value = "";
  await reload();
  toast("Campaign created and selected.");
});

$("#btn-rename-campaign").addEventListener("click", async () => {
  const oldName = state.profile.name;
  const newName = $("#campaign-name").value.trim();
  if (!await flushAutosave("profile")) return;
  const result = await window.pywebview.api.rename_profile(oldName, newName);
  if (!result.ok) return toast(result.error, true);
  await reload();
  toast("Campaign renamed to " + newName + ".");
});

$("#btn-delete-campaign").addEventListener("click", async () => {
  const name = state.profile.name;
  if (!window.confirm("Delete the '" + name + "' campaign? This cannot be undone.")) return;
  if (!await flushAutosave("profile")) return;
  const result = await window.pywebview.api.delete_profile(name);
  if (!result.ok) return toast(result.error, true);
  await reload();
  toast("Campaign deleted.");
});

bindAutosave();

window.addEventListener("pywebviewready", async () => {
  await reload();
  pollTimer = setInterval(poll, 700);
});
