const tg = window.Telegram?.WebApp;
if (tg) tg.ready();

const initData = tg?.initData || localStorage.getItem("initData") || "";
let state = null;
let selectedTariff = null;
let fingerprint = localStorage.getItem("wg_device_id") || crypto.randomUUID();
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

function formatDays(end) {
  if (!end) return "нет подписки";
  const endDate = new Date(end);
  const diff = Math.max(0, Math.ceil((endDate - Date.now()) / (1000 * 60 * 60 * 24)));
  return diff ? `${diff} дн` : "сегодня";
}

function renderTariffs(tariffs) {
  if (!tariffs.length) {
    selectedTariff = null;
    return;
  }
  if (!selectedTariff) {
    selectedTariff = tariffs[0].id;
  }
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
    `;
    list.appendChild(item);
  });
}

async function loadState() {
  state = await api("/api/state");
  el("balance").innerText = `${state.balance} ₽`;
  el("days").innerText = formatDays(state.subscription_end);
  el("devices-allowed").innerText = state.allowed_devices;
  renderTariffs(state.tariffs);
  renderDevices(state.devices);
  el("wg-link").innerText = state.link;
  el("server-name").innerText = state.server ? `Сервер: ${state.server.name}` : "Сервер: —";
  el("suspended-banner").hidden = !state.link_suspended;
  el("ios-help").href = state.ios_help_url;
  el("android-help").href = state.android_help_url;
  el("support-link").href = state.support_url;
  if (tg?.initData) {
    localStorage.setItem("initData", tg.initData);
  }
  const openAdmin = document.getElementById("open-admin");
  const adminPanel = document.getElementById("admin-panel");
  const closeAdmin = document.getElementById("close-admin");
  if (openAdmin) openAdmin.hidden = !state.is_admin;
  if (adminPanel && state.is_admin) {
    adminPanel.hidden = true;
    if (openAdmin) openAdmin.onclick = () => (adminPanel.hidden = false);
    if (closeAdmin) closeAdmin.onclick = () => (adminPanel.hidden = true);
  }
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
    alert("Устройство добавлено");
  } catch (e) {
    alert(e.message);
  }
}

function copyLink() {
  navigator.clipboard.writeText(state?.link || "").then(() => {
    if (tg) tg.showPopup({ message: "Скопировано" });
  });
}

el("topup-btn").onclick = topup;
el("add-device").onclick = addDevice;
el("copy-link").onclick = copyLink;

api("/api/init", { method: "POST", body: { initData } })
  .then(loadState)
  .catch((e) => alert(e.message));

// Admin handlers (secretless)
function setupAdmin() {
  if (!state?.is_admin) return;

  el("broadcast-btn").onclick = async () => {
    const message = el("broadcast-text").value.trim();
    if (!message) return alert("Введите текст");
    try {
      await api("/admin/broadcast", { method: "POST", body: { message } });
      alert("Рассылка отправлена");
    } catch (e) {
      alert(e.message);
    }
  };

  el("add-server").onclick = async () => {
    const name = el("server-name").value.trim();
    const endpoint = el("server-endpoint").value.trim();
    const capacity = parseInt(el("server-capacity").value, 10) || 10;
    if (!name || !endpoint) return alert("Заполните имя и endpoint");
    try {
      await api("/admin/servers", { method: "POST", body: { name, endpoint, capacity } });
      alert("Сервер добавлен");
    } catch (e) {
      alert(e.message);
    }
  };

  el("add-tariff").onclick = async () => {
    const name = el("tariff-name").value.trim();
    const days = parseInt(el("tariff-days").value, 10) || 0;
    const price = parseInt(el("tariff-price").value, 10) || 0;
    const base_devices = parseInt(el("tariff-devices").value, 10) || 1;
    if (!name || !days || !price) return alert("Заполните все поля");
    try {
      await api("/admin/tariffs", { method: "POST", body: { name, days, price, base_devices } });
      alert("Тариф добавлен");
      await loadState();
    } catch (e) {
      alert(e.message);
    }
  };

  const userField = el("admin-user-id");
  el("admin-topup").onclick = async () => {
    const amount = parseInt(el("admin-amount").value, 10) || 0;
    const login = userField.value.trim();
    if (!login || !amount) return alert("Укажите пользователя и сумму");
    const body = login.startsWith("@") ? { username: login.slice(1), amount } : { telegram_id: login, amount };
    try {
      await api("/admin/topup", { method: "POST", body });
      alert("Баланс пополнен");
    } catch (e) {
      alert(e.message);
    }
  };

  el("admin-ban").onclick = async () => {
    const login = userField.value.trim();
    if (!login) return alert("Укажите пользователя");
    const body = login.startsWith("@") ? { username: login.slice(1), banned: true } : { telegram_id: login, banned: true };
    try {
      await api("/admin/ban", { method: "POST", body });
      alert("Пользователь заблокирован");
    } catch (e) {
      alert(e.message);
    }
  };

  el("admin-unban").onclick = async () => {
    const login = userField.value.trim();
    if (!login) return alert("Укажите пользователя");
    const body = login.startsWith("@") ? { username: login.slice(1), banned: false } : { telegram_id: login, banned: false };
    try {
      await api("/admin/ban", { method: "POST", body });
      alert("Пользователь разбанен");
    } catch (e) {
      alert(e.message);
    }
  };
}

const originalLoadState = loadState;
loadState = async function () {
  await originalLoadState();
  setupAdmin();
};
