let token = localStorage.getItem("admin_ui_token") || "";

const el = (id) => document.getElementById(id);

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
  el("creds-block").hidden = false;
}

el("login-btn").onclick = async () => {
  try {
    const username = el("login-username").value.trim();
    const password = el("login-password").value.trim();
    const resp = await api("/admin/ui/login", { username, password });
    token = resp.token;
    localStorage.setItem("admin_ui_token", token);
    showPanel();
    alert("Вход выполнен");
  } catch (e) {
    alert(e.message);
  }
};

el("save-creds").onclick = async () => {
  const username = el("new-username").value.trim();
  const password = el("new-password").value.trim();
  if (!username || !password) return alert("Укажите логин и пароль");
  try {
    await api("/admin/ui/creds", { username, password });
    alert("Логин/пароль обновлены");
  } catch (e) {
    alert(e.message);
  }
};

el("broadcast-btn").onclick = async () => {
  const message = el("broadcast-text").value.trim();
  if (!message) return alert("Введите текст");
  try {
    await api("/admin/ui/broadcast", { message });
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
    await api("/admin/ui/servers", { name, endpoint, capacity });
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
    await api("/admin/ui/tariffs", { name, days, price, base_devices });
    alert("Тариф добавлен");
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
    await api("/admin/ui/topup", body);
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
    await api("/admin/ui/ban", body);
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
    await api("/admin/ui/ban", body);
    alert("Пользователь разбанен");
  } catch (e) {
    alert(e.message);
  }
};

// авто-показ панели, если токен сохранён
if (token) {
  showPanel();
}
