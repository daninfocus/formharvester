// Talks to formharvester.gui.api.Api over the pywebview bridge.

let state = null;
let pollTimer = null;

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

// --- rendering ----------------------------------------------------------

function render() {
  $("#version").textContent = "v" + state.version;
  $("#home-path").textContent = "config: " + state.home;

  const select = $("#profile-select");
  select.innerHTML = "";
  const names = state.profiles.length ? state.profiles : [state.profile.name];
  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    option.selected = name === state.settings.active_profile;
    select.appendChild(option);
  }

  $$("[data-setting]").forEach((el) => writeInput(el, get(state.settings, el.dataset.setting)));
  $$("[data-profile]").forEach((el) => writeInput(el, get(state.profile, el.dataset.profile)));
  $$("[data-profile-list]").forEach((el) => {
    el.value = (state.profile[el.dataset.profileList] || []).join("\n");
  });
}

function setRunning(running) {
  $("#status-dot").classList.toggle("running", running);
  $("#status-text").textContent = running ? "harvesting" : "idle";
  $("#btn-start").disabled = running;
  $("#btn-stop").disabled = !running;
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
  setRunning(state.running);
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
    next[el.dataset.profileList] = el.value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  });
  return next;
}

async function saveSettings() {
  const result = await window.pywebview.api.save_settings(collectSettings());
  if (!result.ok) return toast(result.error, true);
  await reload();
  toast("Settings saved.");
}

async function saveCampaign() {
  const result = await window.pywebview.api.save_profile(collectProfile());
  if (!result.ok) return toast(result.error, true);
  await reload();
  toast("Campaign saved.");
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
  const { lines, running } = await window.pywebview.api.poll();
  appendLines(lines);
  setRunning(running);
}

// --- wiring -------------------------------------------------------------

$$("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    $$("nav button").forEach((b) => b.classList.toggle("active", b === button));
    $$(".panel").forEach((p) => {
      p.classList.toggle("active", p.id === "panel-" + button.dataset.panel);
    });
  });
});

$("#btn-save-settings").addEventListener("click", saveSettings);
$("#btn-save-campaign").addEventListener("click", saveCampaign);
$("#btn-start").addEventListener("click", start);

$("#btn-stop").addEventListener("click", async () => {
  const result = await window.pywebview.api.stop();
  if (!result.ok) toast(result.error, true);
});

$("#btn-clear").addEventListener("click", () => {
  $("#console").innerHTML = '<span class="empty">Cleared.</span>';
});

$("#profile-select").addEventListener("change", async (event) => {
  await window.pywebview.api.use_profile(event.target.value);
  await reload();
  toast("Switched to " + event.target.value + ".");
});

$("#btn-create").addEventListener("click", async () => {
  const input = $("#new-profile");
  const result = await window.pywebview.api.create_profile(input.value);
  if (!result.ok) return toast(result.error, true);
  input.value = "";
  await reload();
  toast("Profile created.");
});

window.addEventListener("pywebviewready", async () => {
  await reload();
  pollTimer = setInterval(poll, 700);
});
