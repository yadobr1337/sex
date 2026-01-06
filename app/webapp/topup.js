const tg = window.Telegram?.WebApp;
if (tg) tg.ready();

const initData = tg?.initData || new URLSearchParams(window.location.search).get("init") || localStorage.getItem("initData") || "";
const provider = "sbp";
let pricePerDay = 10;

const el = (id) => document.getElementById(id);

function openPayUrl(url) {
  if (!url) return;
  if (tg && tg.openLink) {
    tg.openLink(url);
  } else {
    window.location.href = url;
  }
}

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
    const data = await api("/api/topup", { method: "POST", body: { amount, provider } });
    if (!data.confirmation_url) return alert("Не удалось получить ссылку оплаты");
    openPayUrl(data.confirmation_url);
  } catch (e) {
    alert(e.message);
  }
}

function showPayments() {
  api("/api/payments")
    .then((list) => {
      const prevOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      const backdrop = document.createElement("div");
      backdrop.className = "modal-backdrop";
      const card = document.createElement("div");
      card.className = "modal-card";
      let html = "<h3>История пополнений</h3>";
      const success = (list || []).filter((p) => (p.status || "").toLowerCase() === "succeeded");
      if (!success.length) {
        html += "<div class='label'>Нет успешных оплат</div>";
      } else {
        html += success
          .map(
            (p) =>
              `<div class="line"><span class="label-small">#${p.id}</span><span>${p.amount} ₽, ${p.provider || ""}, ${new Date(
                p.created_at
              ).toLocaleString()}</span></div>`
          )
          .join("");
      }
      html += '<div class="modal-actions"><button class="accent" id="close-payments">Закрыть</button></div>';
      card.innerHTML = html;
      backdrop.appendChild(card);
      document.body.appendChild(backdrop);
      card.querySelector("#close-payments").onclick = () => {
        document.body.style.overflow = prevOverflow;
        backdrop.remove();
      };
    })
    .catch((e) => alert(e.message || "Не удалось загрузить историю"));
}

document.querySelectorAll(".quick button").forEach((btn) => {
  btn.onclick = () => {
    el("topup-amount").value = btn.dataset.amount;
  };
});

document.querySelectorAll(".provider-btn").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".provider-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    el("hint").textContent = "Оплата через СБП";
  };
});

async function loadPrice() {
  try {
    const state = await api("/api/state");
    pricePerDay = state.price_per_day || 10;
    const month = Math.ceil(pricePerDay * 30);
    const three = Math.ceil(pricePerDay * 90);
    const year = Math.ceil(pricePerDay * 365);
    const buttons = el("quick-buttons")?.querySelectorAll("button");
    const values = [month, three, year];
    buttons?.forEach((b, idx) => {
      b.textContent = "+" + values[idx];
      b.dataset.amount = values[idx];
    });
    el("hint").textContent = "Оплата через СБП";
  } catch {
    // ignore
  }
}

el("topup-submit").onclick = topup;
el("back-btn").onclick = () => {
  window.location.href = "/";
};
el("history-btn").onclick = showPayments;

loadPrice();
