const tg = window.Telegram?.WebApp;
if (tg) tg.ready();

let initData = tg?.initData || localStorage.getItem("initData") || "";
let state = null;
let policyAccepted = localStorage.getItem("policyAccepted") === "1";
let stateTimer = null;

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

function showGate(message, actions = []) {
  const gate = el("gate");
  const msg = el("gate-message");
  const actionsBox = el("gate-actions");
  if (!gate || !msg || !actionsBox) return;
  msg.innerText = message;
  actionsBox.innerHTML = "";
  actions.forEach((a) => {
    const btn = document.createElement("button");
    btn.className = a.className || "primary";
    btn.textContent = a.text;
    btn.onclick = a.onClick;
    actionsBox.appendChild(btn);
  });
  gate.classList.remove("hidden");
}

function hideGate() {
  const gate = el("gate");
  if (gate) gate.classList.add("hidden");
}

function renderDevices(devices) {
  const list = el("device-list");
  list.innerHTML = "";
  if (!devices.length) {
    list.innerHTML = `<div class="label">Пока нет устройств</div>`;
    return;
  }
  devices.forEach((d, idx) => {
    const item = document.createElement("div");
    item.className = "device-item";
    item.innerHTML = `
      <div>
        <div class="value">${d.label}</div>
        <div class="label">${d.fingerprint.slice(0, 8)} - ${new Date(d.last_seen).toLocaleDateString()}</div>
      </div>
      ${idx === 0 ? "" : `<button class="ghost danger" data-id="${d.id}">Удалить</button>`}
    `;
    const btn = item.querySelector("button");
    if (btn) btn.onclick = () => deleteDevice(d.id);
    list.appendChild(item);
  });
}

async function loadState() {
  state = await api("/api/state");
  el("balance").innerText = `${state.balance} ₽`;
  el("days").innerText = `~${state.estimated_days} д`;
  el("devices-allowed").innerText = state.allowed_devices || 1;
  renderDevices(state.devices);
  el("wg-link").innerText = state.link || "—";
  const connectBtn = el("connect-btn");
  if (connectBtn) connectBtn.disabled = !state.link;
  el("suspended-banner").hidden = !state.link_suspended;
  el("ios-help").href = state.ios_help_url;
  el("android-help").href = state.android_help_url;
  el("support-link").href = state.support_url;
  if (tg?.initData) {
    localStorage.setItem("initData", tg.initData);
    initData = tg.initData;
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
    const fp = crypto.randomUUID();
    const label = `Устройство ${state?.devices?.length ? state.devices.length + 1 : 1}`;
    await api("/api/device", { method: "POST", body: { fingerprint: fp, label } });
    await loadState();
  } catch (e) {
    console.error(e);
    if (tg) tg.showPopup({ message: e.message || "Ошибка при добавлении устройства" });
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

async function runGate() {
  await api("/api/init", { method: "POST", body: { initData } });
  const gate = await api("/api/gate");

  if (!gate.subscribed) {
    showGate("Подпишитесь на наш канал, чтобы продолжить.", [
      {
        text: "Подписаться",
        onClick: () => {
          if (gate.required_channel) {
            window.open(`https://t.me/${gate.required_channel.replace("@", "")}`, "_blank");
          }
        },
      },
      {
        text: "Проверить",
        className: "ghost",
        onClick: () => runGate().catch(() => {}),
      },
    ]);
    return;
  }

  if (!policyAccepted) {
    showGate("Согласитесь с политикой конфиденциальности, чтобы открыть 1VPN.", [
      gate.policy_url
        ? {
            text: "Политика",
            className: "ghost",
            onClick: () => window.open(gate.policy_url, "_blank"),
          }
        : null,
      {
        text: "Согласен",
        onClick: () => {
          policyAccepted = true;
          localStorage.setItem("policyAccepted", "1");
          hideGate();
          loadState().catch(() => {});
        },
      },
    ].filter(Boolean));
    return;
  }

  hideGate();
  try {
    await loadState();
  } catch (e) {
    if (e.message === "subscribe_required") {
      policyAccepted = localStorage.getItem("policyAccepted") === "1";
      return runGate();
    }
    throw e;
  }
  if (stateTimer) clearInterval(stateTimer);
  stateTimer = setInterval(() => {
    loadState().catch((err) => {
      if (err.message === "subscribe_required") {
        policyAccepted = localStorage.getItem("policyAccepted") === "1";
        runGate().catch(() => {});
      }
    });
  }, 10000);
}

runGate().catch((e) => console.error(e));
