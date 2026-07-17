const TOKEN_KEY = "glc_install_token";
let ws = null;
let connectedChannel = null;
let CAPS = {};
let channelData = [];

const CHANNEL_ICONS = {
  telegram: "TG", discord: "DC", slack: "SL", whatsapp: "WA", teams: "TM",
  matrix: "MX", line: "LN", signal: "SG", gmail: "GM", imap: "IM",
  twilio_sms: "SMS", twilio_voice: "TV", webui: "UI", webhook: "WH", local_mic: "MC",
};

const CHANNEL_COLORS = {
  telegram: "#26A5E4", discord: "#5865F2", slack: "#E01E5A", whatsapp: "#25D366",
  teams: "#7B83EB", matrix: "#0DBD8B", line: "#06C755", signal: "#3B82F6",
  gmail: "#EA4335", imap: "#F59E0B", twilio_sms: "#F22F46", twilio_voice: "#FF6B6B",
  webui: "#A78BFA", webhook: "#14B8A6", local_mic: "#EC4899",
};

function $(id) { return document.getElementById(id); }
function token() { return localStorage.getItem(TOKEN_KEY) || ""; }
function authHeaders() {
  const t = token();
  return t ? { Authorization: `Bearer ${t}` } : {};
}
function log(el, data) {
  el.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
}
function fmtAgo(ts) {
  if (!ts) return "—";
  const d = Math.round(Date.now() / 1000 - ts);
  if (d < 60) return `${d}s ago`;
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  return `${Math.round(d / 3600)}h ago`;
}

function showToast(message, ok = true) {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();
  const el = document.createElement("div");
  el.className = `toast ${ok ? "ok" : "err"}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2800);
}

function shortAdapter(path) {
  const parts = path.split(".");
  return parts.length >= 2 ? `${parts.slice(-3).join(".")}` : path;
}

function wsBaseUri(channel) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  // C3: no durable install token in query string — ticket via subprotocol
  return `${proto}://${location.host}/v1/channels/${channel}`;
}

async function fetchWsTicket() {
  const r = await fetch("/v1/control/ws-ticket", {
    method: "POST",
    headers: { ...authHeaders() },
  });
  if (!r.ok) throw new Error(`ws-ticket failed: ${r.status}`);
  const d = await r.json();
  return d.ticket;
}

function selectWsChannel(name) {
  const select = $("ws-channel");
  if (!select) return;
  const ch = channelData.find((c) => c.name === name);
  if (!ch?.enabled) {
    showToast(`Enable ${name} first (toggle in grid above)`, false);
    return;
  }
  if ([...select.options].some((o) => o.value === name)) {
    select.value = name;
    document.querySelectorAll(".channel-card").forEach((card) => {
      card.classList.toggle("selected", card.dataset.channel === name);
    });
    if (connectedChannel && connectedChannel !== name) {
      showToast(`Connected to ${connectedChannel} — click Connect to switch`, false);
    }
  }
}

function setupNav() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(`panel-${btn.dataset.panel}`).classList.add("active");
    });
  });
}

function setupToken() {
  const input = $("token-input");
  input.value = token();
  $("save-token-btn").addEventListener("click", () => {
    localStorage.setItem(TOKEN_KEY, input.value.trim());
    refreshChannels();
    loadPresence();
  });
}

async function checkHealth() {
  try {
    const r = await fetch("/healthz");
    const d = await r.json();
    $("health-badge").textContent = d.ok ? "healthy" : "degraded";
    $("health-badge").className = `badge ${d.ok ? "ok" : "err"}`;
    $("port-badge").textContent = `port ${location.port || d.port || "8111"}`;
  } catch {
    $("health-badge").textContent = "offline";
    $("health-badge").className = "badge err";
  }
}

async function refreshChannels() {
  const grid = $("channel-grid");
  const select = $("ws-channel");
  const filter = $("channel-filter")?.value || "all";
  try {
    const [catalogue, presence] = await Promise.all([
      fetch("/v1/channels/catalogue", { headers: authHeaders() }).then((r) => r.json()),
      fetch("/v1/control/presence", { headers: authHeaders() }).catch(() => ({ channels: [], paired_users: [], uptime_s: null })),
    ]);
    const live = new Set(presence.channels || []);
    const paired = presence.paired_users || [];
    channelData = catalogue.channels || [];

    const enabledCount = channelData.filter((c) => c.enabled).length;
    const liveCount = channelData.filter((c) => live.has(c.name)).length;
    $("stat-total").textContent = channelData.length;
    $("stat-enabled").textContent = enabledCount;
    $("stat-live").textContent = liveCount;
    $("stat-paired").textContent = paired.length;
    $("presence-summary").textContent =
      `uptime ${presence.uptime_s ?? "—"}s · ${liveCount} live · ${paired.length} paired`;

    const filtered = channelData.filter((ch) => {
      const isLive = live.has(ch.name);
      if (filter === "enabled") return ch.enabled;
      if (filter === "disabled") return !ch.enabled;
      if (filter === "live") return isLive;
      return true;
    });

    grid.innerHTML = "";
    select.innerHTML = "";
    if (!filtered.length) {
      grid.innerHTML = '<p class="muted">No channels match this filter.</p>';
    }

    filtered.forEach((ch) => {
      const isLive = live.has(ch.name);
      const accent = CHANNEL_COLORS[ch.name] || "#2dd4bf";
      const card = document.createElement("div");
      card.className = `card channel-card ${ch.enabled ? "enabled" : "disabled"} ${isLive ? "live" : ""}`;
      card.dataset.channel = ch.name;
      card.style.setProperty("--ch-accent", accent);
      card.innerHTML = `
        <div class="channel-accent-bar"></div>
        <div class="channel-card-inner">
          <div class="channel-card-header">
            <div class="channel-avatar" style="--avatar-color:${accent}">${CHANNEL_ICONS[ch.name] || ch.name.slice(0, 2).toUpperCase()}</div>
            <div class="channel-info">
              <div class="name">${ch.name}</div>
              <div class="channel-badges">
                <span class="pill ${ch.enabled ? "ok" : "off"}">${ch.enabled ? "enabled" : "disabled"}</span>
                ${isLive ? '<span class="pill live">live ws</span>' : '<span class="pill">catalogue</span>'}
              </div>
            </div>
            <div class="channel-actions">
              <label class="toggle" title="${ch.enabled ? "Disable channel" : "Enable channel"}">
                <input type="checkbox" data-channel="${ch.name}" ${ch.enabled ? "checked" : ""}>
                <span class="toggle-slider"></span>
              </label>
            </div>
          </div>
          <div class="adapter-path" title="${ch.adapter}">${shortAdapter(ch.adapter)}</div>
        </div>
      `;
      grid.appendChild(card);

      const opt = document.createElement("option");
      opt.value = ch.name;
      opt.textContent = ch.name;
      if (!ch.enabled) {
        opt.disabled = true;
        opt.textContent = `${ch.name} (enable first)`;
      }
      select.appendChild(opt);
    });

    grid.querySelectorAll(".channel-card").forEach((card) => {
      card.addEventListener("click", (ev) => {
        if (ev.target.closest(".toggle")) return;
        selectWsChannel(card.dataset.channel);
      });
    });

    grid.querySelectorAll('.toggle input[type="checkbox"]').forEach((input) => {
      input.addEventListener("change", () => toggleChannel(input.dataset.channel, input.checked, input));
    });

    if (select.querySelector('option[value="signal"]:not([disabled])')) select.value = "signal";
    else {
      const firstEnabled = [...select.options].find((o) => !o.disabled);
      if (firstEnabled) select.value = firstEnabled.value;
    }
    if (connectedChannel) selectWsChannel(connectedChannel);
  } catch (e) {
    grid.textContent = `Failed to load channels: ${e.message}`;
  }
}

async function toggleChannel(name, enabled, inputEl) {
  if (!token()) {
    showToast("Save install token first", false);
    if (inputEl) inputEl.checked = !enabled;
    return;
  }
  if (inputEl) inputEl.disabled = true;
  try {
    const r = await fetch(`/v1/channels/${name}/enabled`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ enabled }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail));
    showToast(`${name} ${enabled ? "enabled" : "disabled"}`);
    await refreshChannels();
  } catch (e) {
    showToast(`Failed: ${e.message}`, false);
    if (inputEl) inputEl.checked = !enabled;
  } finally {
    if (inputEl) inputEl.disabled = false;
  }
}

function wsLog(msg) {
  const el = $("ws-log");
  const line = typeof msg === "string" ? msg : JSON.stringify(msg, null, 2);
  el.textContent = `${el.textContent === "—" ? "" : el.textContent + "\n\n"}${line}`;
  el.scrollTop = el.scrollHeight;
}

function clearWsThread() {
  const thread = $("ws-chat-thread");
  thread.innerHTML = '<p class="msg-empty">Connect and send a message — replies appear here as a chat thread.</p>';
  $("ws-log").textContent = "—";
}

function addChatBubble(kind, payload) {
  const thread = $("ws-chat-thread");
  const empty = thread.querySelector(".msg-empty");
  if (empty) empty.remove();

  const bubble = document.createElement("div");
  bubble.className = `msg-bubble msg-${kind}`;

  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  if (kind === "system") {
    bubble.innerHTML = `<span class="msg-meta">${time}</span><span class="msg-text">${payload}</span>`;
  } else if (kind === "error") {
    const err = typeof payload === "string" ? payload : payload.error || JSON.stringify(payload);
    bubble.innerHTML = `
      <span class="msg-meta">${time} · blocked</span>
      <span class="msg-text">${err.replace(/^dropped:\s*/i, "")}</span>`;
  } else if (kind === "sent") {
    bubble.innerHTML = `
      <span class="msg-meta">${time} · you → ${payload.channel_user_id} · ${payload.trust_level}</span>
      <span class="msg-text">${escapeHtml(payload.text || "")}</span>`;
  } else if (kind === "received") {
    bubble.innerHTML = `
      <span class="msg-meta">${time} · gateway reply</span>
      <span class="msg-text">${escapeHtml(payload.text || "")}</span>`;
  }

  thread.appendChild(bubble);
  thread.scrollTop = thread.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function setWsStatus(text, ok) {
  const el = $("ws-status");
  el.textContent = text;
  el.className = `pill ${ok ? "ok" : "err"}`;
}

function setupWsTester() {
  $("ws-channel")?.addEventListener("change", () => {
    if (connectedChannel && $("ws-channel").value !== connectedChannel) {
      showToast(`Dropdown changed — reconnect to test ${$("ws-channel").value}`, false);
    }
  });

  $("ws-connect-btn").addEventListener("click", async () => {
    const t = token();
    if (!t) { wsLog("Set install token first."); showToast("Save install token first", false); return; }
    const ch = $("ws-channel").value;
    const entry = channelData.find((c) => c.name === ch);
    if (!entry?.enabled) {
      showToast(`Enable ${ch} in the grid above before connecting`, false);
      return;
    }
    let ticket;
    try {
      ticket = await fetchWsTicket();
    } catch (e) {
      showToast(`WS ticket failed: ${e.message}`, false);
      return;
    }
    const uri = wsBaseUri(ch);
    if (ws) ws.close();
    ws = new WebSocket(uri, [`glc.ticket.${ticket}`]);
    setWsStatus("connecting…", false);
    ws.onopen = () => {
      connectedChannel = ch;
      setWsStatus(`connected · ${ch}`, true);
      $("ws-send-btn").disabled = false;
      $("ws-disconnect-btn").disabled = false;
      wsLog(`connected → ${uri} (short-lived ticket)`);
      addChatBubble("system", `Connected to ${ch} — messages will use channel "${ch}"`);
    };
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      wsLog({ received: data });
      if (data.error) addChatBubble("error", data);
      else addChatBubble("received", data);
    };
    ws.onerror = () => { wsLog("WebSocket error (check token + gateway)"); setWsStatus("error", false); };
    ws.onclose = () => {
      setWsStatus("disconnected", false);
      $("ws-send-btn").disabled = true;
      $("ws-disconnect-btn").disabled = true;
      ws = null;
      connectedChannel = null;
    };
  });

  $("ws-send-btn").addEventListener("click", () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!connectedChannel) {
      showToast("Connect to a channel first", false);
      return;
    }
    const env = {
      channel: connectedChannel,
      channel_user_id: $("ws-user-id").value.trim(),
      user_handle: "dashboard",
      text: $("ws-text").value,
      attachments: [],
      voice_audio_ref: null,
      thread_id: $("ws-thread-id").value.trim() || null,
      trust_level: $("ws-trust").value,
      arrived_at: new Date().toISOString(),
      metadata: {},
    };
    ws.send(JSON.stringify(env));
    wsLog({ sent: env });
    addChatBubble("sent", env);
  });

  $("ws-disconnect-btn").addEventListener("click", () => { if (ws) ws.close(); });
  $("ws-clear-btn").addEventListener("click", clearWsThread);
}

async function loadPresence() {
  const out = $("presence-json");
  try {
    const r = await fetch("/v1/control/presence", { headers: authHeaders() });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || JSON.stringify(d));
    log(out, d);
  } catch (e) {
    log(out, `Error: ${e.message}`);
  }
}

async function issuePair() {
  const out = $("pair-out");
  try {
    const r = await fetch("/v1/control/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        channel: $("pair-channel").value.trim(),
        channel_user_id: $("pair-user-id").value.trim(),
        user_handle: $("pair-handle").value.trim(),
        trust_level: $("pair-trust").value,
      }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail));
    log(out, d);
  } catch (e) {
    log(out, `Error: ${e.message}`);
  }
}

async function confirmPair() {
  const out = $("pair-out");
  try {
    const r = await fetch("/v1/control/pair/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ code: $("pair-code").value.trim() }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail));
    log(out, d);
    refreshChannels();
  } catch (e) {
    log(out, `Error: ${e.message}`);
  }
}

async function killGateway() {
  const out = $("kill-out");
  if (!confirm("Terminate gateway process?")) return;
  try {
    const r = await fetch("/v1/control/kill", { method: "POST", headers: authHeaders() });
    const d = await r.json();
    log(out, d);
  } catch (e) {
    log(out, `Error: ${e.message}`);
  }
}

async function loadCaps() {
  CAPS = await fetch("/v1/capabilities", { headers: authHeaders() }).then((r) => r.json());
}

async function refreshProviders() {
  const r = await fetch("/v1/status", { headers: authHeaders() }).then((x) => x.json());
  $("order").textContent = r.order.join(" → ");
  const grid = $("providers");
  const provSelect = $("test-prov");
  grid.innerHTML = "";
  Object.keys(r.live).forEach((name) => {
    const s = r.live[name];
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="name">${name}</div>
      <div class="muted">${s.model}</div>
      <div class="row"><span>RPM</span><b>${s.rpm_used} / ${s.rpm_limit}</b></div>
      <div class="bar"><div style="width:${Math.min(100, (s.rpm_used / s.rpm_limit) * 100)}%"></div></div>
      <div class="row"><span>Last</span><b>${fmtAgo(s.last_call)}</b></div>
    `;
    grid.appendChild(card);
    if (![...provSelect.options].some((o) => o.value === name)) {
      const o = document.createElement("option");
      o.value = name;
      o.textContent = name;
      provSelect.appendChild(o);
    }
  });
}

async function refreshRouters() {
  try {
    const r = await fetch("/v1/routers", { headers: authHeaders() }).then((x) => x.json());
    $("router-order").textContent = `failover: ${r.order.join(" → ")}`;
    const grid = $("routers");
    grid.innerHTML = "";
    Object.keys(r.live).forEach((name) => {
      const s = r.live[name];
      const card = document.createElement("div");
      card.className = "card";
      card.style.borderLeft = "3px solid var(--accent)";
      card.innerHTML = `<div class="name">${name}</div><div class="muted">${s.model}</div>`;
      grid.appendChild(card);
    });
  } catch { /* optional */ }
}

async function loadCalls() {
  const rows = await fetch("/v1/calls?limit=30", { headers: authHeaders() }).then((r) => r.json());
  const tb = $("calls-table").querySelector("tbody");
  tb.innerHTML = "";
  rows.forEach((c) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${new Date(c.ts * 1000).toLocaleTimeString()}</td>
      <td>${c.provider}</td>
      <td>${c.model}</td>
      <td class="${c.status === "ok" ? "ok" : "err"}">${c.status}</td>
      <td>${c.latency_ms}ms</td>
      <td>${c.error || "—"}</td>
    `;
    tb.appendChild(tr);
  });
}

async function runChatTest() {
  const out = $("test-out");
  out.textContent = "sending…";
  try {
    const r = await fetch("/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        prompt: $("test-prompt").value,
        provider: $("test-prov").value || null,
        max_tokens: 120,
      }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(JSON.stringify(d.detail || d));
    log(out, `[${d.provider} · ${d.latency_ms}ms]\n\n${d.text}`);
  } catch (e) {
    log(out, `Error: ${e.message}`);
  }
  refreshProviders();
  loadCalls();
}

async function runSpeak() {
  const out = $("speak-out");
  out.textContent = "synthesizing…";
  try {
    const r = await fetch(`/v1/speak?prefer=${$("speak-prefer").value}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ text: $("speak-text").value }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(JSON.stringify(d.detail || d));
    log(out, { provider: d.provider, mime: d.mime, sample_rate: d.sample_rate, audio_b64_len: (d.audio_b64 || "").length });
  } catch (e) {
    log(out, `Error: ${e.message}`);
  }
}

async function runTranscribe() {
  const out = $("transcribe-out");
  const file = $("transcribe-file").files[0];
  if (!file) { log(out, "Choose an audio file first."); return; }
  out.textContent = "transcribing…";
  try {
    const b64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const r = await fetch(`/v1/transcribe?prefer=${$("transcribe-prefer").value}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ audio_b64: b64, mime: file.type || "audio/wav" }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(JSON.stringify(d.detail || d));
    log(out, d);
  } catch (e) {
    log(out, `Error: ${e.message}`);
  }
}

function bindControls() {
  $("refresh-channels-btn").addEventListener("click", refreshChannels);
  $("channel-filter")?.addEventListener("change", refreshChannels);
  $("load-presence-btn").addEventListener("click", loadPresence);
  $("pair-issue-btn").addEventListener("click", issuePair);
  $("pair-confirm-btn").addEventListener("click", confirmPair);
  $("kill-btn").addEventListener("click", killGateway);
  $("run-test-btn").addEventListener("click", runChatTest);
  $("speak-btn").addEventListener("click", runSpeak);
  $("transcribe-btn").addEventListener("click", runTranscribe);
}

async function init() {
  setupNav();
  setupToken();
  setupWsTester();
  bindControls();
  await checkHealth();
  await loadCaps();
  await refreshChannels();
  await refreshProviders();
  await refreshRouters();
  await loadCalls();
  setInterval(() => {
    checkHealth();
    refreshChannels();
    refreshProviders();
    loadCalls();
  }, 8000);
}

init();
