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
var prev = {};

function el(id) {
  return document.getElementById(id);
}
var mainEl = document.querySelector("main");

function setUpdating(id, flag) {
  var node = el(id);
  if (!node) return;
  if (flag) node.classList.add("updating");
  else node.classList.remove("updating");
}

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
  var initVal = (tg && tg.initData) || initData || "";
  headers["X-Telegram-Init"] = initVal;

  // Прокладка initData в body/квери, если заголовки режутся
  var method = (options.method || "GET").toUpperCase();
  var body = options.body || null;
  if (!options.skipInit && method !== "GET") {
    if (body == null) body = {};
    if (typeof body === "object" && !Array.isArray(body) && !body.initData) {
      body.initData = initVal;
    }
  }
  if (!options.skipInit && method === "GET" && initVal && path.indexOf("init=") === -1) {
    try {
      var url = new URL(path, window.location.origin);
      url.searchParams.set("init", initVal);
      path = url.pathname + url.search;
    } catch (e) {
      /* ignore */
    }
  }

  return fetch(path, {
    method: options.method || "GET",
    headers: headers,
    body: body ? JSON.stringify(body) : undefined,
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
  if (!list || list.hasAttribute("hidden")) return;
  list.innerHTML = "";
  if (!devices.length) {
    list.innerHTML = '<div class="label">Пока нет устройств</div>';
    return;
  }
  devices.forEach(function (d, idx) {
    var item = document.createElement("div");
    item.className = "device-item fade-new";
    item.innerHTML =
      '<div><div class="value">' + d.label + '</div><div class="label">' +
      d.fingerprint.slice(0, 8) + ' - ' + new Date(d.last_seen).toLocaleDateString() +
      '</div></div>' +
      (idx === 0 ? "" : '<button class="ghost danger" data-id="' + d.id + '">Удалить</button>');
    var btn = item.querySelector("button");
    if (btn) btn.onclick = function () { deleteDevice(d.id); };
    list.appendChild(item);
    requestAnimationFrame(function () {
      item.classList.add("show");
    });
  });
}

function loadState() {
  return api("/api/state").then(function (data) {
    state = data;
    if (state.banned) {
      showGate("Вы заблокированы. Обратитесь в поддержку.", [
        {
          text: "Поддержка",
          onClick: function () {
            if (state.support_url) window.open(state.support_url, "_blank");
          },
        },
      ]);
      return;
    }
    var balanceChanged = prev.balance !== state.balance;
    if (balanceChanged) setUpdating("balance", true);
    setTextSmooth("balance", state.balance + " ₽");
    if (balanceChanged) setTimeout(function () { setUpdating("balance", false); }, 500);

    setTextSmooth("days", "~" + state.estimated_days + " д");
    setTextSmooth("devices-allowed", state.allowed_devices || 1);
    renderDevices(state.devices);

    var placeholderLink = "";
    var linkChanged = prev.link !== state.link;
    if (linkChanged) setUpdating("wg-link", true);
    setTextSmooth("wg-link", state.link || placeholderLink);
    if (linkChanged) setTimeout(function () { setUpdating("wg-link", false); }, 500);

    var connectBtn = el("connect-btn");
    if (connectBtn) connectBtn.disabled = !state.link;
    var suspended = state.link_suspended || (typeof state.estimated_days === "number" && state.estimated_days <= 0);
    var linkRow = el("link-row");
    if (linkRow) {
      if (!suspended && state.link) {
        linkRow.style.display = "flex";
        requestAnimationFrame(function () { linkRow.classList.add("show"); });
      } else {
        linkRow.style.display = "none";
        linkRow.classList.remove("show");
      }
    }
    var connectBtn = el("connect-btn");
    if (connectBtn) {
      var showConnect = !!state.link && state.link_suspended === false && (state.estimated_days || 0) > 0;
      connectBtn.style.display = showConnect ? "inline-flex" : "none";
      connectBtn.disabled = !showConnect;
    }
    var copyBtn = el("copy-link");
    if (copyBtn) copyBtn.style.display = !suspended && state.link ? "inline-flex" : "none";
    var suspendedBanner = el("suspended-banner");
    if (suspendedBanner) suspendedBanner.hidden = !suspended;
    var linkTitle = el("link-title");
    if (linkTitle) linkTitle.style.display = (!suspended && state.link) ? "block" : "none";
    el("ios-help").href = state.ios_help_url;
    el("android-help").href = state.android_help_url;
    el("support-link").href = state.support_url;
    if (tg && tg.initData) {
      localStorage.setItem("initData", tg.initData);
      initData = tg.initData;
    }
    var openAdmin = document.getElementById("open-admin");
    if (openAdmin) openAdmin.hidden = !state.is_admin;
    var deviceSection = el("device-section");
    if (deviceSection) {
      if (!suspended && state.link) {
        deviceSection.style.display = "block";
        requestAnimationFrame(function () { deviceSection.classList.add("show"); });
      } else {
        deviceSection.style.display = "none";
      }
    }
    var devicesAllowed = el("devices-allowed");
    if (devicesAllowed) setTextSmooth("devices-allowed", state.allowed_devices || 0);
    prev.balance = state.balance;
    prev.link = state.link;
  });
}

function handleStateError(err) {
  if (err && err.message === "maintenance") {
    showGate("Временные техработы. Попробуйте позже.", []);
    return true;
  }
  return false;
}

function topup() {
  var init = (tg && tg.initData) || localStorage.getItem("initData") || "";
  var url = "/static/topup.html" + (init ? "?init=" + encodeURIComponent(init) : "");
  window.location.href = url;
}

function deleteDevice(id) {
  api("/api/device/" + id, { method: "DELETE" }).then(loadState).catch(function () { });
}

function showPayments() {
  api("/api/payments")
    .then(function (list) {
      var backdrop = document.createElement("div");
      backdrop.className = "modal-backdrop";
      var card = document.createElement("div");
      card.className = "modal-card";
      var html = "<h3>История пополнений</h3>";
      if (!list.length) {
        html += "<div class='label'>Нет платежей</div>";
      } else {
        html += list
          .map(function (p) {
            return (
              "<div class='line'><span class='label'>#" +
              p.id +
              "</span><span class='value'>" +
              p.amount +
              " ₽, " +
              (p.provider || "") +
              ", " +
              (p.status || "") +
              ", " +
              new Date(p.created_at).toLocaleString() +
              "</span></div>"
            );
          })
          .join("");
      }
      html += "<div class='modal-actions'><button class='accent' id='close-payments'>Закрыть</button></div>";
      card.innerHTML = html;
      backdrop.appendChild(card);
      document.body.appendChild(backdrop);
      card.querySelector("#close-payments").onclick = function () {
        backdrop.remove();
      };
    })
    .catch(function (e) {
      if (tg && tg.showPopup) tg.showPopup({ message: e.message || "Не удалось загрузить историю" });
    });
}

function setDevicesCount() {
  var backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  var card = document.createElement("div");
  card.className = "modal-card";
  var current = state ? state.allowed_devices || 1 : 1;
  card.innerHTML = '<h3>Количество устройств</h3><div class="range-row"><input id="dev-range" type="range" min="1" max="5" value="' + current + '"><div class="value" id="dev-range-val">' + current + '</div></div><div class="modal-actions"><button class="ghost" id="range-cancel">Отмена</button><button class="accent" id="range-apply">OK</button></div>';
  backdrop.appendChild(card);
  document.body.appendChild(backdrop);

  var range = card.querySelector("#dev-range");
  var val = card.querySelector("#dev-range-val");
  range.oninput = function () { val.textContent = range.value; };

  card.querySelector("#range-cancel").onclick = function () {
    backdrop.remove();
  };
  card.querySelector("#range-apply").onclick = function () {
    var desired = parseInt(range.value, 10);
    backdrop.remove();
    if (!desired || desired < 1) return;
    adjustDevices(desired);
  };
}

function adjustDevices(desired) {
  var current = state && state.devices ? state.devices.length : 0;
  var ops = Promise.resolve();
  if (desired > current) {
    var toAdd = desired - current;
    ops = Array.from({ length: toAdd }).reduce(function (p, _, idx) {
      return p.then(function () {
        var fp = randomId();
        var label = "Устройство " + (current + idx + 1);
        return api("/api/device", { method: "POST", body: { fingerprint: fp, label: label } });
      });
    }, Promise.resolve());
  } else if (desired < current) {
    var toRemove = current - desired;
    var ids = (state.devices || []).slice(-toRemove).map(function (d) { return d.id; });
    ops = ids.reduce(function (p, id) {
      return p.then(function () { return api("/api/device/" + id, { method: "DELETE" }); });
    }, Promise.resolve());
  }
  ops.then(loadState).catch(function (e) {
    if (tg && tg.showPopup) tg.showPopup({ message: e.message || "Не удалось изменить количество устройств" });
  });
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
el("add-device").onclick = setDevicesCount;
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
        } else if (!handleStateError(e)) {
          /* ignore */
        }
      });

      if (stateTimer) clearInterval(stateTimer);
      stateTimer = setInterval(function () {
        loadState().catch(function (err) {
          if (err.message === "subscribe_required") {
            policyAccepted = localStorage.getItem("policyAccepted") === "1";
            runGate();
          } else if (!handleStateError(err)) {
            /* ignore */
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
