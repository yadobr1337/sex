// Поддержка старых webview: без современных конструкций
const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
if (tg && tg.ready) tg.ready();

// Если не Telegram WebApp - показываем пустую страницу
if (!tg) {
  document.body.innerHTML = "";
  document.documentElement.style.background = "#000";
}

var initData = (tg && tg.initData) || localStorage.getItem("initData") || "";
var state = null;
var policyAccepted = localStorage.getItem("policyAccepted") === "1";
var stateTimer = null;

function el(id) {
  return document.getElementById(id);
}
var mainEl = document.querySelector("main");

function setTextSmooth(id, text) {
  var node = el(id);
  if (!node) return;
  if (!node.classList.contains("fade-update")) node.classList.add("fade-update");
  node.classList.remove("show");
  window.requestAnimationFrame(function () {
    node.textContent = text;
    window.requestAnimationFrame(function () {
      node.classList.add("show");
    });
  });
}

function randomId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxx".replace(/x/g, function () { return Math.floor(Math.random() * 16).toString(16); });
}

function api(path, options) {
  options = options || {};
  var headers = options.headers || {};
  headers["Content-Type"] = "application/json";
  headers["X-Telegram-Init"] = (tg && tg.initData) || initData || "";
  return fetch(path, {
    method: options.method || "GET",
    headers: headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  }).then(function (res) {
    if (!res.ok) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        throw new Error(data.detail || res.statusText);
      });
    }
    return res.json();
  });
}

function showGate(message, actions) {
  var gate = el("gate");
  var msg = el("gate-message");
  var actionsBox = el("gate-actions");
  if (!gate || !msg || !actionsBox) return;
  msg.innerText = message;
  actionsBox.innerHTML = "";
  (actions || []).forEach(function (a) {
    var btn = document.createElement("button");
    btn.className = a.className || "primary";
    btn.textContent = a.text;
    btn.onclick = a.onClick;
    actionsBox.appendChild(btn);
  });
  gate.classList.remove("hidden");
  document.body.classList.add("gate-open");
  if (mainEl) mainEl.classList.add("gated");
}

function hideGate() {
  var gate = el("gate");
  if (gate) gate.classList.add("hidden");
  document.body.classList.remove("gate-open");
  if (mainEl) mainEl.classList.remove("gated");
}

function renderDevices(devices) {
  var list = el("device-list");
  list.innerHTML = "";
  if (!devices.length) {
    list.innerHTML = '<div class="label">Пока нет устройств</div>';
    return;
  }
  devices.forEach(function (d, idx) {
    var item = document.createElement("div");
    item.className = "device-item";
    item.innerHTML =
      '<div><div class="value">' + d.label + '</div><div class="label">' +
      d.fingerprint.slice(0, 8) + ' - ' + new Date(d.last_seen).toLocaleDateString() +
      '</div></div>' +
      (idx === 0 ? "" : '<button class="ghost danger" data-id="' + d.id + '">Удалить</button>');
    var btn = item.querySelector("button");
    if (btn) btn.onclick = function () { deleteDevice(d.id); };
    list.appendChild(item);
  });
}

function loadState() {
  return api("/api/state").then(function (data) {
    state = data;
    setTextSmooth("balance", state.balance + " ₽");
    setTextSmooth("days", "~" + state.estimated_days + " д");
    setTextSmooth("devices-allowed", state.allowed_devices || 1);
    renderDevices(state.devices);
    setTextSmooth("wg-link", state.link || "—");
    var connectBtn = el("connect-btn");
    if (connectBtn) connectBtn.disabled = !state.link;
    el("suspended-banner").hidden = !state.link_suspended;
    el("ios-help").href = state.ios_help_url;
    el("android-help").href = state.android_help_url;
    el("support-link").href = state.support_url;
    if (tg && tg.initData) {
      localStorage.setItem("initData", tg.initData);
      initData = tg.initData;
    }
    var openAdmin = document.getElementById("open-admin");
    if (openAdmin) openAdmin.hidden = !state.is_admin;
  });
}

function topup() {
  var init = (tg && tg.initData) || localStorage.getItem("initData") || "";
  var url = "/static/topup.html" + (init ? "?init=" + encodeURIComponent(init) : "");
  window.location.href = url;
}

function addDevice() {
  var fp = randomId();
  var label = "Устройство " + (state && state.devices && state.devices.length ? state.devices.length + 1 : 1);
  api("/api/device", { method: "POST", body: { fingerprint: fp, label: label } })
    .then(loadState)
    .catch(function (e) {
      if (tg && tg.showPopup) tg.showPopup({ message: e.message || "Ошибка при добавлении устройства" });
    });
}

function deleteDevice(id) {
  api("/api/device/" + id, { method: "DELETE" }).then(loadState).catch(function () { });
}

function copyLink() {
  navigator.clipboard.writeText((state && state.link) || "").then(function () {
    if (tg && tg.showPopup) tg.showPopup({ message: "Скопировано" });
  });
}

function openLink() {
  if (!state || !state.link) return;
  window.location.href = state.link;
}

el("topup-btn").onclick = topup;
el("add-device").onclick = addDevice;
el("copy-link").onclick = copyLink;
var connectBtnInit = el("connect-btn");
if (connectBtnInit) connectBtnInit.onclick = openLink;

function runGate() {
  api("/api/init", { method: "POST", body: { initData: initData } })
    .then(function () { return api("/api/gate"); })
    .then(function (gate) {
      if (!gate.subscribed) {
        showGate("Подпишитесь на наш канал, чтобы продолжить.", [
          {
            text: "Подписаться",
            onClick: function () {
              if (gate.required_channel) {
                window.open("https://t.me/" + gate.required_channel.replace("@", ""), "_blank");
              }
            },
          },
          {
            text: "Проверить",
            className: "ghost",
            onClick: function () { runGate(); },
          },
        ]);
        return;
      }

      if (!policyAccepted) {
        showGate(
          "Согласитесь с политикой конфиденциальности, чтобы открыть 1VPN.",
          [
            gate.policy_url
              ? {
                  text: "Политика",
                  className: "ghost",
                  onClick: function () { window.open(gate.policy_url, "_blank"); },
                }
              : null,
            {
              text: "Согласен",
              onClick: function () {
                policyAccepted = true;
                localStorage.setItem("policyAccepted", "1");
                hideGate();
                loadState().catch(function () { });
              },
            },
          ].filter(function (x) { return !!x; })
        );
        return;
      }

      hideGate();
      loadState().catch(function (e) {
        if (e.message === "subscribe_required") {
          policyAccepted = localStorage.getItem("policyAccepted") === "1";
          runGate();
        }
      });

      if (stateTimer) clearInterval(stateTimer);
      stateTimer = setInterval(function () {
        loadState().catch(function (err) {
          if (err.message === "subscribe_required") {
            policyAccepted = localStorage.getItem("policyAccepted") === "1";
            runGate();
          }
        });
      }, 10000);
    })
    .catch(function () {
      showGate("Не удалось загрузить данные. Повторите попытку.", [
        { text: "Повторить", onClick: function () { runGate(); } },
      ]);
    });
}

runGate();
