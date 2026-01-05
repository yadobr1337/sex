const tg = window.Telegram?.WebApp;
if (tg) tg.ready();

const initData = tg?.initData || localStorage.getItem("initData") || "";
let state = null;
const fingerprint = localStorage.getItem("wg_device_id") || crypto.randomUUID();
localStorage.setItem("wg_device_id", fingerprint);

const el = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init": tg?.initData || initData || "",
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || res.statusText);
  }
  return res.json();
}

function renderDevices(devices) {
  const list = el("device-list");
  list.innerHTML = "";
  if (!devices.length) {
    list.innerHTML = `<div class="label">Пока нет устройств</div>`;
    return;
  }
  devices.forEach((d) => {
    const item = document.createElement("div");
    item.className = "device-item";
    item.innerHTML = `
      <div>
        <div class="value">${d.label}</div>
        <div class="label">${d.fingerprint.slice(0, 8)} · ${new Date(d.last_seen).toLocaleDateString()}</div>
      </div>
      <button class="ghost danger" data-id="${d.id}">Удалить</button>
    `;
    item.querySelector("button").onclick = () => deleteDevice(d.id);
    list.appendChild(item);
  });
}

async function loadState() {
  state = await api("/api/state");
  el("balance").innerText = `${state.balance} руб`;
  el("days").innerText = `~${state.estimated_days} дн`;
  el("devices-allowed").innerText = state.allowed_devices || 1;
  renderDevices(state.devices);
  el("wg-link").innerText = state.link || "—";
  const connectBtn = el("connect-btn");
  if (connectBtn) connectBtn.disabled = !state.link || state.link_suspended;
  el("suspended-banner").hidden = !state.link_suspended;
  el("ios-help").href = state.ios_help_url;
  el("android-help").href = state.android_help_url;
  el("support-link").href = state.support_url;
  if (tg?.initData) {
    localStorage.setItem("initData", tg.initData);
  }
  const openAdmin = document.getElementById("open-admin");
  if (openAdmin) openAdmin.hidden = !state.is_admin;
}

async function topup() {
  const init = tg?.initData || localStorage.getItem("initData") || "";
  const url = `/static/topup.html${init ? `?init=${encodeURIComponent(init)}` : ""}`;
  window.location.href = url;
}

async function addDevice() {
  try {
    await api("/api/device", { method: "POST", body: { fingerprint, label: "Мое устройство" } });
    await loadState();
  } catch (e) {
    console.error(e);
  }
}

async function deleteDevice(id) {
  try {
    await api(`/api/device/${id}`, { method: "DELETE" });
    await loadState();
  } catch (e) {
    console.error(e);
  }
}

function copyLink() {
  navigator.clipboard.writeText(state?.link || "").then(() => {
    if (tg) tg.showPopup({ message: "Скопировано" });
  });
}

function openLink() {
  if (!state?.link) return;
  window.location.href = state.link;
}

el("topup-btn").onclick = topup;
el("add-device").onclick = addDevice;
el("copy-link").onclick = copyLink;
const connectBtnInit = el("connect-btn");
if (connectBtnInit) connectBtnInit.onclick = openLink;

api("/api/init", { method: "POST", body: { initData } })
  .then(loadState)
  .catch((e) => console.error(e));
