let token = localStorage.getItem("admin_ui_token") || "";
const el = (id) => document.getElementById(id);
const statusLine = () => el("status-line");

function setStatus(msg, ok = true) {
  const s = statusLine();
  if (!s) return;
  s.textContent = msg || "";
  s.style.color = ok ? "#8dffa8" : "#ffb3ad";
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Admin-Token": token } : {}),
    },
    body: JSON.stringify(body),
  });
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
  loadServers();
  loadPrice();
}

el("login-btn").onclick = async () => {
  try {
    const username = el("login-username").value.trim();
    const password = el("login-password").value.trim();
    const resp = await api("/admin/ui/login", { username, password });
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
    setStatus("Логин/пароль обновлены");
  } catch (e) {
    setStatus(e.message, false);
  }
};

el("broadcast-btn").onclick = async () => {
  const message = el("broadcast-text").value.trim();
  if (!message) return setStatus("Введите текст", false);
  try {
    await api("/admin/ui/broadcast", { message });
    setStatus("Рассылка отправлена");
  } catch (e) {
    setStatus(e.message, false);
  }
};

el("add-server").onclick = async () => {
  const name = el("server-name").value.trim();
  const endpoint = el("server-endpoint").value.trim();
  const capacity = parseInt(el("server-capacity").value, 10) || 10;
  if (!name || !endpoint) return setStatus("Заполните имя и endpoint", false);
  try {
    await api("/admin/ui/servers", { name, endpoint, capacity });
    setStatus("Сервер добавлен");
    await loadServers();
  } catch (e) {
    setStatus(e.message, false);
  }
};

async function loadServers() {
  try {
    const res = await fetch("/admin/ui/servers/list", {
      headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
    });
    if (!res.ok) return;
    const data = await res.json();
    const list = el("server-list");
    if (!list) return;
    list.innerHTML = "";
    data.servers.forEach((s) => {
      const row = document.createElement("div");
      row.className = "server-item";
      row.innerHTML = `<div><div class="value">${s.name}</div><div class="label">${s.endpoint}</div></div>`;

      const actions = document.createElement("div");
      const capInput = document.createElement("input");
      capInput.type = "number";
      capInput.min = "0";
      capInput.value = s.capacity;
      capInput.style.width = "70px";
      capInput.className = "ghost";

      const upd = document.createElement("button");
      upd.className = "ghost";
      upd.textContent = "Обновить";
      upd.onclick = async () => {
        const capacity = parseInt(capInput.value, 10) || 0;
        try {
          await api("/admin/ui/servers/update", { server_id: s.id, capacity });
          setStatus("Сервер обновлён");
          await loadServers();
        } catch (e) {
          setStatus(e.message, false);
        }
      };

      const del = document.createElement("button");
      del.className = "ghost danger";
      del.textContent = "Удалить";
      del.onclick = async () => {
        try {
          await api("/admin/ui/servers/delete", { server_id: s.id });
          setStatus("Сервер удалён");
          await loadServers();
        } catch (e) {
          setStatus(e.message, false);
        }
      };
      actions.append(capInput, upd, del);
      row.appendChild(actions);
      list.appendChild(row);
    });
  } catch (e) {
    /* ignore */
  }
}

if (token) {
  loadServers();
}

const userField = el("admin-user-id");

el("admin-topup").onclick = async () => {
  const amount = parseInt(el("admin-amount").value, 10) || 0;
  const login = userField.value.trim();
  if (!login || !amount) return setStatus("Укажите пользователя и сумму", false);
  const body = login.startsWith("@") ? { username: login.slice(1), amount } : { telegram_id: login, amount };
  try {
    await api("/admin/ui/topup", body);
    setStatus("Баланс пополнен");
  } catch (e) {
    setStatus(e.message, false);
  }
};

el("admin-ban").onclick = async () => {
  const login = userField.value.trim();
  if (!login) return setStatus("Укажите пользователя", false);
  const body = login.startsWith("@") ? { username: login.slice(1), banned: true } : { telegram_id: login, banned: true };
  try {
    await api("/admin/ui/ban", body);
    setStatus("Пользователь заблокирован");
  } catch (e) {
    setStatus(e.message, false);
  }
};

el("admin-unban").onclick = async () => {
  const login = userField.value.trim();
  if (!login) return setStatus("Укажите пользователя", false);
  const body = login.startsWith("@") ? { username: login.slice(1), banned: false } : { telegram_id: login, banned: false };
  try {
    await api("/admin/ui/ban", body);
    setStatus("Пользователь разбанен");
  } catch (e) {
    setStatus(e.message, false);
  }
};

async function loadPrice() {
  try {
    const res = await fetch("/admin/ui/price", {
      headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
    });
    if (!res.ok) return;
    const data = await res.json();
    el("price-30").value = data.price;
  } catch {
    /* ignore */
  }
}

el("save-price").onclick = async () => {
  const price = parseInt(el("price-30").value, 10) || 0;
  if (!price) return setStatus("Укажите цену", false);
  try {
    await api("/admin/ui/price", { price });
    setStatus("Цена обновлена");
  } catch (e) {
    setStatus(e.message, false);
  }
};

// авто-показ панели, если токен сохранён
if (token) {
  showPanel();
}
