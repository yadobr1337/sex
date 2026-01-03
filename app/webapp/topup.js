const tg = window.Telegram?.WebApp;
if (tg) tg.ready();

const initData = tg?.initData || new URLSearchParams(window.location.search).get("init") || localStorage.getItem("initData") || "";

const el = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init": initData,
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

async function topup() {
  const input = el("topup-amount");
  const amount = parseInt(input.value, 10);
  if (Number.isNaN(amount) || amount < 50) return alert("Минимум 50₽");
  try {
    const data = await api("/api/topup", { method: "POST", body: { amount } });
    window.open(data.confirmation_url, "_blank");
  } catch (e) {
    alert(e.message);
  }
}

document.querySelectorAll(".quick button").forEach((btn) => {
  btn.onclick = () => {
    el("topup-amount").value = btn.dataset.amount;
  };
});

el("topup-submit").onclick = topup;
el("back-btn").onclick = () => {
  window.location.href = "/";
};
