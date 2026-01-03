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
    headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
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
  loadMarzban();
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
  if (!username || !password) return setStatus("Введите логин и пароль", false);
  try {
    await api("/admin/ui/creds", { username, password });
    setStatus("Логин/пароль обновлены");
  } catch (e) {
    setStatus(e.message, false);
  }
};

el("broadcast-btn").onclick = async () => {
  const message = el("broadcast-text").value.trim();
  if (!message) return setStatus("Пустое сообщение", false);
  try {
    await api("/admin/ui/broadcast", { message });
    setStatus("Рассылка отправлена");
  } catch (e) {
    setStatus(e.message, false);
  }
};

async function loadMarzban() {
  try {
    const res = await fetch("/admin/ui/marzban/servers/list", {
      headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
    });
    if (!res.ok) return;
    const data = await res.json();
    const list = el("marz-list");
    if (!list) return;
    list.innerHTML = "";
    data.forEach((s) => {
      const row = document.createElement("div");
      row.className = "server-item";
      row.innerHTML = `<div><div class="value">${s.name}</div><div class="label">${s.api_url}</div></div>`;
      const del = document.createElement("button");
      del.className = "ghost danger";
      del.textContent = "Удалить";
      del.onclick = async () => {
        try {
          await api("/admin/ui/marzban/servers/delete", { server_id: s.id });
          setStatus("Marzban сервер удалён");
          await loadMarzban();
        } catch (e) {
          setStatus(e.message, false);
        }
      };
      row.appendChild(del);
      list.appendChild(row);
    });
  } catch {
    /* ignore */
  }
}

el("add-marz").onclick = async () => {
  const name = el("marz-name").value.trim();
  const api_url = el("marz-api-url").value.trim();
  const api_token = el("marz-api-token").value.trim();
  const capacity = parseInt(el("marz-capacity").value, 10) || 10;
  if (!name || !api_url || !api_token) return setStatus("Заполните имя, URL и токен", false);
  try {
    await api("/admin/ui/marzban/servers", { name, api_url, api_token, capacity });
    setStatus("Marzban сервер добавлен");
    await loadMarzban();
  } catch (e) {
    setStatus(e.message, false);
  }
};

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
    setStatus("Пользователь забанен");
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
    setStatus("Цена за день обновлена");
  } catch (e) {
    setStatus(e.message, false);
  }
};

if (token) showPanel();
