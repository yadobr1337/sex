let token = localStorage.getItem("admin_ui_token") || "";
const el = (id) => document.getElementById(id);
const statusLine = () => el("status-line");
let statusTimer = null;

function showToast(msg, ok = true) {
  const box = el("toast-container");
  if (!box) return;
  const t = document.createElement("div");
  t.className = "toast " + (ok ? "ok" : "err");
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => {
    t.remove();
  }, 4000);
}

function setStatus(msg, ok = true) {
  const s = statusLine();
  if (!s) return;
  s.textContent = msg || "";
  s.style.color = ok ? "#8dffa8" : "#ffb3ad";
   showToast(msg, ok);
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    token = "";
    localStorage.removeItem("admin_ui_token");
    location.reload();
    throw new Error("Нужно войти заново");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || res.statusText);
  }
  return res.json();
}

function showPanel() {
  el("panel").hidden = false;
  const lb = el("login-block");
  if (lb) lb.remove();
  setStatus("Вы вошли в админку");
  startStatusPoll();
  loadRemSquads();
  loadPrice();
  loadMaintenance();
  loadMaintenanceAllow();
}

el("login-btn").onclick = async () => {
  try {
    const username = el("login-username").value.trim();
    const password = el("login-password").value.trim();
    const resp = await api("/admin/ui/login", { username, password });
    if (!resp.token) throw new Error("Ошибка входа");
    token = resp.token;
    localStorage.setItem("admin_ui_token", token);
    showPanel();
  } catch (e) {
    setStatus(e.message, false);
  }
};

el("save-creds").onclick = async () => {
  const username = el("new-username").value.trim();
  const password = el("new-password").value.trim();
  if (!username || !password) return setStatus("Укажите логин и пароль", false);
  try {
    await api("/admin/ui/creds", { username, password });
    setStatus("Данные сохранены");
  } catch (e) {
    setStatus(e.message, false);
  }
};

el("broadcast-btn").onclick = async () => {
  const message = el("broadcast-text").value.trim();
  const photoInput = el("broadcast-photo");
  const file = photoInput?.files?.[0];
  if (!message && !file) return setStatus("Введите текст или выберите фото", false);
  try {
    if (file) {
      const form = new FormData();
      form.append("message", message);
      form.append("file", file);
      const res = await fetch("/admin/ui/broadcast_photo_upload", {
        method: "POST",
        headers: { ...(token ? { "X-Admin-Token": token } : {}) },
        body: form,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || res.statusText);
      }
      setStatus("Рассылка с фото отправлена");
    } else {
      await api("/admin/ui/broadcast", { message });
      setStatus("Рассылка отправлена");
    }
  } catch (e) {
    setStatus(e.message, false);
  }
};

async function loadRemSquads() {
  try {
    const res = await fetch("/admin/ui/rem/squads/list", {
      headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
    });
    if (res.status === 401) {
      token = "";
      localStorage.removeItem("admin_ui_token");
      location.reload();
      return;
    }
    if (!res.ok) return;
    const data = await res.json();
    const list = el("rem-list");
    if (!list) return;
    list.innerHTML = "";
    data.forEach((s) => {
      const row = document.createElement("div");
      row.className = "server-item";
      const nameCol = document.createElement("div");
      nameCol.className = "value";
      nameCol.textContent = s.name;
      const uuidCol = document.createElement("div");
      uuidCol.className = "label";
      uuidCol.textContent = s.uuid;
      const input = document.createElement("input");
      input.type = "number";
      input.min = "1";
      input.value = s.capacity;
      input.className = "inline-input";

      const actions = document.createElement("div");
      actions.className = "actions";

      const upd = document.createElement("button");
      upd.className = "ghost";
      upd.textContent = "Обновить";
      upd.onclick = async () => {
        const cap = parseInt(input.value, 10) || s.capacity;
        try {
          await api("/admin/ui/rem/squads/update", { squad_id: s.id, capacity: cap });
          setStatus("Ёмкость обновлена");
          await loadRemSquads();
        } catch (e) {
          setStatus(e.message, false);
        }
      };

      const del = document.createElement("button");
      del.className = "ghost danger";
      del.textContent = "Удалить";
      del.onclick = async () => {
        try {
          await api("/admin/ui/rem/squads/delete", { squad_id: s.id });
          setStatus("Сквад удалён");
          await loadRemSquads();
        } catch (e) {
          setStatus(e.message, false);
        }
      };
      actions.appendChild(upd);
      actions.appendChild(del);

      row.appendChild(nameCol);
      row.appendChild(uuidCol);
      row.appendChild(input);
      row.appendChild(actions);
      list.appendChild(row);
    });
  } catch {
    /* ignore */
  }
}

el("add-rem").onclick = async () => {
  const name = el("rem-name").value.trim();
  const uuid = el("rem-uuid").value.trim();
  const capacity = parseInt(el("rem-capacity").value, 10) || 50;
  if (!name || !uuid) return setStatus("Укажи название и UUID сквада", false);
  try {
    await api("/admin/ui/rem/squads", { name, uuid, capacity });
    setStatus("Сквад добавлен");
    await loadRemSquads();
  } catch (e) {
    setStatus(e.message, false);
  }
};

async function refreshRemStatus() {
  const s = el("rem-status");
  if (!s) return;
  s.hidden = false;
  s.classList.remove("status-ok", "status-bad");
  s.textContent = "Проверка панели...";
  try {
    const res = await fetch("/admin/ui/rem/status", {
      headers: { ...(token ? { "X-Admin-Token": token } : {}) },
    });
    if (res.status === 401) {
      token = "";
      localStorage.removeItem("admin_ui_token");
      location.reload();
      return;
    }
    const data = await res.json();
    const ok = !!data.ok;
    s.classList.add(ok ? "status-ok" : "status-bad");
    s.textContent = ok ? "Панель подключена" : `Нет связи: ${data.detail || data.status || res.status}`;
  } catch (e) {
    s.classList.add("status-bad");
    s.textContent = `Нет связи: ${e.message}`;
  }
}

function startStatusPoll() {
  refreshRemStatus();
  if (statusTimer) clearInterval(statusTimer);
  statusTimer = setInterval(refreshRemStatus, 10000);
}

// Пользователь
const userField = el("admin-user-id");
const amountField = el("admin-amount");
const infoBlock = el("admin-user-info");

function resolveUserBody() {
  const login = userField.value.trim();
  if (!login) return null;
  return login.startsWith("@") ? { username: login.slice(1) } : { telegram_id: login };
}

el("admin-topup").onclick = async () => {
  const body = resolveUserBody();
  const amount = parseInt(amountField.value, 10) || 0;
  if (!body || !amount) return setStatus("Укажите пользователя и сумму", false);
  try {
    const res = await api("/admin/ui/topup", { ...body, amount });
    setStatus("Пополнено, баланс: " + res.balance);
    if (infoBlock) infoBlock.innerText = "Баланс: " + res.balance;
  } catch (e) {
    setStatus(e.message, false);
  }
};

const debitBtn = el("admin-debit");
if (debitBtn) {
  debitBtn.onclick = async () => {
    const body = resolveUserBody();
    const amount = parseInt(amountField.value, 10) || 0;
    if (!body || !amount) return setStatus("Укажите пользователя и сумму", false);
    try {
      const res = await api("/admin/ui/debit", { ...body, amount });
      setStatus("Списано, баланс: " + res.balance);
      if (infoBlock) infoBlock.innerText = "Баланс: " + res.balance;
    } catch (e) {
      setStatus(e.message, false);
    }
  };
}

const infoBtn = el("admin-info");
if (infoBtn) {
  infoBtn.onclick = async () => {
    const body = resolveUserBody();
    if (!body) return setStatus("Укажите пользователя", false);
    try {
      const info = await api("/admin/ui/userinfo", body);
      if (infoBlock) {
        const subDate = info.subscription_end ? new Date(info.subscription_end).toLocaleString() : "нет";
        const link = info.link || "—";
        infoBlock.innerHTML = `
          <div class="line"><span class="label">Баланс:</span><span class="value">${info.balance} руб</span></div>
          <div class="line"><span class="label">Подписка до:</span><span class="value">${subDate}</span></div>
          <div class="line"><span class="label">Устройства:</span><span class="value">${info.allowed_devices} (актив: ${info.devices})</span></div>
          <div class="line"><span class="label">Статус:</span><span class="value">${info.banned ? "БАН" : "Ок"}</span></div>
          <div class="line"><span class="label">Ссылка:</span><span class="value">${link}</span></div>
        `;
      }
      setStatus("Данные пользователя загружены");
    } catch (e) {
      setStatus(e.message, false);
    }
  };
}

el("admin-ban").onclick = async () => {
  const body = resolveUserBody();
  if (!body) return setStatus("Укажите пользователя", false);
  try {
    await api("/admin/ui/ban", { ...body, banned: true });
    setStatus("Пользователь забанен");
    if (infoBtn) infoBtn.click();
  } catch (e) {
    setStatus(e.message, false);
  }
};

el("admin-unban").onclick = async () => {
  const body = resolveUserBody();
  if (!body) return setStatus("Укажите пользователя", false);
  try {
    await api("/admin/ui/ban", { ...body, banned: false });
    setStatus("Пользователь разбанен");
    if (infoBtn) infoBtn.click();
  } catch (e) {
    setStatus(e.message, false);
  }
};

const payHistoryBtn = el("admin-payments");
if (payHistoryBtn) {
  payHistoryBtn.onclick = async () => {
    const body = resolveUserBody();
    if (!body) return setStatus("Укажите пользователя", false);
    try {
      const list = await api("/admin/ui/payments", body);
      const box = el("admin-payments-list");
      if (box) {
        if (!list.length) {
          box.innerHTML = "<div class='label'>Оплат нет</div>";
        } else {
          box.innerHTML = list
            .map(
              (p) =>
                `<div class="line"><span class="label">#${p.id}</span><span class="value">${p.amount} ₽, ${p.provider}, ${p.status}, ${new Date(p.created_at).toLocaleString()}</span></div>`
            )
            .join("");
        }
      }
      setStatus("История загрузилась");
    } catch (e) {
      setStatus(e.message, false);
    }
  };
}

async function loadPrice() {
  try {
    const res = await fetch("/admin/ui/price", {
      headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
    });
    if (!res.ok) return;
    const data = await res.json();
    el("price-day").value = data.price;
  } catch {
    /* ignore */
  }
}

el("save-price").onclick = async () => {
  const price = parseFloat(el("price-day").value) || 0;
  if (!price) return setStatus("Укажите цену", false);
  try {
    await api("/admin/ui/price", { price });
    setStatus("Цена сохранена");
  } catch (e) {
    setStatus(e.message, false);
  }
};

async function loadMaintenance() {
  try {
    const res = await fetch("/admin/ui/maintenance", {
      headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
    });
    if (!res.ok) return;
    const data = await res.json();
    const cb = el("maintenance-toggle");
    if (cb) cb.checked = !!data.enabled;
  } catch {
    /* ignore */
  }
}

const saveMaintBtn = el("save-maintenance");
if (saveMaintBtn) {
  saveMaintBtn.onclick = async () => {
    const cb = el("maintenance-toggle");
    const enabled = cb ? cb.checked : false;
    try {
      await api("/admin/ui/maintenance", { enabled });
      setStatus(enabled ? "Техработы включены" : "Техработы выключены");
    } catch (e) {
      setStatus(e.message, false);
    }
  };
}

async function loadMaintenanceAllow() {
  try {
    const res = await fetch("/admin/ui/maintenance/allow", {
      headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
    });
    if (!res.ok) return;
    const data = await res.json();
    const input = el("maintenance-allow");
    if (input && data.telegram_ids) input.value = data.telegram_ids.join(", ");
  } catch {
    /* ignore */
  }
}

const saveMaintAllowBtn = el("save-maintenance-allow");
if (saveMaintAllowBtn) {
  saveMaintAllowBtn.onclick = async () => {
    const input = el("maintenance-allow");
    const raw = input ? input.value : "";
    const ids = raw
      .split(/[,\\s]+/)
      .map((x) => x.trim())
      .filter((x) => x);
    try {
      await api("/admin/ui/maintenance/allow", { telegram_ids: ids });
      setStatus("Список исключений сохранен");
    } catch (e) {
      setStatus(e.message, false);
    }
  };
}

if (token) showPanel();
