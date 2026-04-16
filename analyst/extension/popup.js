// Configure these for your deployment
const API = localStorage.getItem("ma_api_url") || "http://localhost:8899/api/analyze";
const QUERY_API = localStorage.getItem("ma_query_url") || "http://localhost:8899/api/query";
const SECRET = localStorage.getItem("ma_api_secret") || "CHANGE_ME";

let convo = JSON.parse(localStorage.getItem("ma_convo") || "[]");
let saved = JSON.parse(localStorage.getItem("ma_messages") || "[]");
let savedInd = localStorage.getItem("ma_indicators") || "";
let pendingQuery = null; // stores the question for query flow

function restore() {
  const el = document.getElementById("messages");
  if (saved.length === 0) {
    el.innerHTML = '<div class="msg system">SPY analysis. Data ~15 min delayed. Ask anything — if I don\'t have the stat, I\'ll offer to query the database.</div>';
  } else {
    el.innerHTML = "";
    saved.forEach(m => addMsg(m.text, m.type, true));
  }
  if (savedInd) document.getElementById("indicators").innerHTML = savedInd;
}

function saveState() {
  localStorage.setItem("ma_convo", JSON.stringify(convo.slice(-10)));
  localStorage.setItem("ma_messages", JSON.stringify(saved.slice(-30)));
  localStorage.setItem("ma_indicators", document.getElementById("indicators").innerHTML);
}

document.getElementById("send").onclick = send;
document.getElementById("input").onkeydown = e => { if (e.key === "Enter") send(); };
document.getElementById("clear").onclick = () => {
  convo = []; saved = []; savedInd = ""; pendingQuery = null;
  localStorage.removeItem("ma_convo"); localStorage.removeItem("ma_messages"); localStorage.removeItem("ma_indicators");
  document.getElementById("messages").innerHTML = '<div class="msg system">Session cleared.</div>';
  document.getElementById("indicators").innerHTML = "";
};

function addMsg(text, type, isRestore) {
  const el = document.createElement("div");
  el.className = "msg " + type;

  if (type === "analyst") {
    let html = text
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");

    // Detect query offer and add button
    if (html.includes("[QUERY_OFFER]")) {
      html = html.replace("<strong>[QUERY_OFFER]</strong>", "").replace("[QUERY_OFFER]", "");
      html += '<br><button class="query-btn" onclick="runQuery()">🔍 Run Analysis</button>';
      // Store the last user question as the pending query
      pendingQuery = convo.length > 0 ? convo[convo.length - 1].content : null;
    }
    el.innerHTML = html;
  } else if (type === "query-result") {
    el.className = "msg analyst";
    el.innerHTML = '<strong style="color:#60a5fa">📊 Database Query Result:</strong><br>' +
      text.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\n/g, "<br>");
  } else {
    el.textContent = text;
  }

  document.getElementById("messages").appendChild(el);
  document.getElementById("messages").scrollTop = 99999;
  if (!isRestore) { saved.push({text, type}); saveState(); }
}

async function send() {
  const input = document.getElementById("input");
  const btn = document.getElementById("send");
  const msg = input.value.trim();
  if (!msg) return;

  addMsg(msg, "user");
  input.value = "";
  btn.disabled = true;
  document.getElementById("status").textContent = "fetching live data...";

  const ld = document.createElement("div");
  ld.className = "loading"; ld.id = "loading";
  ld.innerHTML = "<span></span><span></span><span></span>";
  document.getElementById("messages").appendChild(ld);
  document.getElementById("messages").scrollTop = 99999;

  convo.push({role:"user", content:msg});

  try {
    const resp = await fetch(API, {
      method: "POST",
      headers: {"Content-Type":"application/json", "Authorization":"Bearer "+SECRET},
      body: JSON.stringify({message:msg, conversation:convo.slice(-6)}),
    });
    document.getElementById("loading")?.remove();
    if (!resp.ok) { const e = await resp.json().catch(()=>({})); throw new Error(e.detail||"HTTP "+resp.status); }

    const data = await resp.json();
    const ind = data.indicators;
    const chg = ((ind.price-ind.prev_close)/ind.prev_close*100).toFixed(2);
    const cls = ind.price > ind.prev_close ? "bull" : "bear";

    document.getElementById("indicators").innerHTML =
      '<span>SPY <span class="val '+cls+'">'+ind.price.toFixed(2)+'</span></span>'+
      '<span class="'+cls+'">'+(chg>=0?"+":"")+chg+'%</span>'+
      '<span>PDC <span class="val">'+ind.prev_close+'</span></span>'+
      '<span>ATR <span class="val">'+ind.daily_atr+'</span></span>'+
      '<span>PO <span class="val">'+(ind.phase_oscillator_10m||"—")+'</span></span>'+
      '<span style="color:#4a4e5c">'+(ind.latest_bar||"").slice(11,16)+'</span>';

    addMsg(data.analysis, "analyst");
    convo.push({role:"assistant", content:data.analysis});
    document.getElementById("status").textContent = "updated "+(ind.latest_bar||"").slice(0,16);
    saveState();
  } catch(err) {
    document.getElementById("loading")?.remove();
    addMsg("Error: "+err.message, "error");
    document.getElementById("status").textContent = "error";
    convo.pop();
  }
  btn.disabled = false;
  input.focus();
}

// Query flow — run database analysis
window.runQuery = async function() {
  if (!pendingQuery) return;

  const question = pendingQuery;
  pendingQuery = null;

  // Disable all query buttons
  document.querySelectorAll(".query-btn").forEach(b => { b.disabled = true; b.textContent = "Running..."; });
  document.getElementById("status").textContent = "querying database...";

  const ld = document.createElement("div");
  ld.className = "loading"; ld.id = "loading";
  ld.innerHTML = "<span></span><span></span><span></span>";
  document.getElementById("messages").appendChild(ld);
  document.getElementById("messages").scrollTop = 99999;

  try {
    const resp = await fetch(QUERY_API, {
      method: "POST",
      headers: {"Content-Type":"application/json", "Authorization":"Bearer "+SECRET},
      body: JSON.stringify({question}),
    });
    document.getElementById("loading")?.remove();
    if (!resp.ok) { const e = await resp.json().catch(()=>({})); throw new Error(e.detail||"HTTP "+resp.status); }

    const data = await resp.json();
    addMsg(data.answer, "query-result");
    convo.push({role:"assistant", content:"[Database query result]: " + data.answer});
    document.getElementById("status").textContent = "query complete";
    saveState();
  } catch(err) {
    document.getElementById("loading")?.remove();
    addMsg("Query error: "+err.message, "error");
    document.getElementById("status").textContent = "query error";
  }

  document.querySelectorAll(".query-btn").forEach(b => { b.disabled = true; b.textContent = "✓ Done"; });
};

restore();
document.getElementById("input").focus();
