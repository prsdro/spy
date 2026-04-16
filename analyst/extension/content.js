// Milkman Trading Analyst — Chrome Extension Content Script

// Configure these for your deployment
const API_URL = "http://localhost:8899/api/analyze";
const API_SECRET = "CHANGE_ME";

let conversation = [];
let lastIndicators = null;

// ── Build UI ──
function createUI() {
  const container = document.createElement("div");
  container.id = "milkman-analyst";

  container.innerHTML = `
    <div id="ma-window">
      <div id="ma-header">
        <div>
          <div class="title">milkman<span>.</span> analyst</div>
          <div class="status" id="ma-status">ready</div>
        </div>
        <button id="ma-close">&times;</button>
      </div>
      <div id="ma-messages">
        <div class="ma-msg system">Send a message to fetch live SPY data and get analysis.</div>
      </div>
      <div class="ma-indicators" id="ma-indicators"></div>
      <div id="ma-input-area">
        <input id="ma-input" type="text" placeholder="What's the setup today?" autocomplete="off">
        <button id="ma-send">Analyze</button>
      </div>
    </div>
    <div id="ma-toggle">🥛</div>
  `;

  document.body.appendChild(container);

  // Event listeners
  document.getElementById("ma-toggle").addEventListener("click", toggleWindow);
  document.getElementById("ma-close").addEventListener("click", toggleWindow);
  document.getElementById("ma-send").addEventListener("click", sendMessage);
  document.getElementById("ma-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
}

function toggleWindow() {
  document.getElementById("ma-window").classList.toggle("open");
  if (document.getElementById("ma-window").classList.contains("open")) {
    document.getElementById("ma-input").focus();
  }
}

// ── Messaging ──
function addMessage(text, type = "analyst") {
  const messages = document.getElementById("ma-messages");
  const msg = document.createElement("div");
  msg.className = `ma-msg ${type}`;

  if (type === "analyst") {
    // Basic markdown: **bold**, `code`, newlines
    let html = text
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");
    msg.innerHTML = html;
  } else {
    msg.textContent = text;
  }

  messages.appendChild(msg);
  messages.scrollTop = messages.scrollHeight;
  return msg;
}

function addLoading() {
  const messages = document.getElementById("ma-messages");
  const loading = document.createElement("div");
  loading.className = "ma-loading";
  loading.id = "ma-loading";
  loading.innerHTML = "<span></span><span></span><span></span>";
  messages.appendChild(loading);
  messages.scrollTop = messages.scrollHeight;
}

function removeLoading() {
  const el = document.getElementById("ma-loading");
  if (el) el.remove();
}

function updateIndicators(ind) {
  if (!ind) return;
  const el = document.getElementById("ma-indicators");
  const priceColor = ind.price > ind.prev_close ? "bull" : "bear";
  const change = ((ind.price - ind.prev_close) / ind.prev_close * 100).toFixed(2);
  const changeSign = change >= 0 ? "+" : "";

  el.innerHTML = `
    <span>SPY <span class="ind-val ${priceColor}">${ind.price}</span></span>
    <span class="${priceColor}">${changeSign}${change}%</span>
    <span>PDC <span class="ind-val">${ind.prev_close}</span></span>
    <span>ATR <span class="ind-val">${ind.daily_atr}</span></span>
    <span>PO <span class="ind-val">${ind.phase_oscillator_10m || '—'}</span></span>
    <span>Range <span class="ind-val">${ind.range_pct_atr || '—'}%</span></span>
  `;
}

function setStatus(text) {
  document.getElementById("ma-status").textContent = text;
}

// ── API Call ──
async function sendMessage() {
  const input = document.getElementById("ma-input");
  const sendBtn = document.getElementById("ma-send");
  const message = input.value.trim();

  if (!message) return;

  // Show user message
  addMessage(message, "user");
  input.value = "";
  sendBtn.disabled = true;
  setStatus("fetching live data...");
  addLoading();

  // Build conversation for context
  conversation.push({ role: "user", content: message });

  try {
    const resp = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${API_SECRET}`,
      },
      body: JSON.stringify({
        message: message,
        conversation: conversation.slice(-6), // last 3 exchanges
      }),
    });

    removeLoading();

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }

    const data = await resp.json();

    // Update indicators bar
    lastIndicators = data.indicators;
    updateIndicators(data.indicators);

    // Show analysis
    addMessage(data.analysis, "analyst");
    conversation.push({ role: "assistant", content: data.analysis });

    setStatus(`updated ${data.timestamp}`);

  } catch (err) {
    removeLoading();
    addMessage(`Error: ${err.message}`, "error");
    setStatus("error");
    // Remove the failed message from conversation
    conversation.pop();
  }

  sendBtn.disabled = false;
  input.focus();
}

// ── Init ──
createUI();
