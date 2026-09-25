// No build step, no framework: one module, fetch + WebSocket.
const $ = (sel) => document.querySelector(sel);
const state = { catalog: null, profiles: [], mine: new Set(), live: null };

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : d?.message ?? `HTTP ${res.status}`);
  }
  return body;
}

function showError(err) {
  const el = $("#error");
  el.textContent = err ? err.message ?? String(err) : "";
  el.hidden = !err;
}

const el = (tag, attrs = {}, ...children) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  n.append(...children.filter((c) => c !== null && c !== undefined));
  return n;
};

const duration = (seconds) => {
  const s = Math.round(seconds);
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`;
};
const ago = (t) => duration(Date.now() / 1000 - t);
const until = (t) => (t ? `${Math.max(0, Math.round((t - Date.now() / 1000) / 60))} min left` : "");

// ---- tabs
document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
    document.querySelectorAll("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== tab.dataset.view));
    refresh();
  }),
);

// ---- devices
function slotCard(s) {
  const busy = s.state !== "free";
  return el("article", { class: "card" },
    el("div", { class: "card-row" },
      el("h2", { class: "card-title" }, busy ? s.profile ?? "…" : `Slot ${s.slot}`),
      el("span", { class: "badge", "data-state": s.state }, el("span", { class: "dot" }), s.state)),
    el("div", { class: "screen" },
      s.state === "leased"
        ? el("img", { src: `/api/leases/${s.lease_id}/snapshot?t=${Date.now()}`, alt: `${s.profile} screen` })
        : s.state === "booting" ? "Booting…" : "Idle"),
    el("div", {},
      el("div", { class: "mono" }, s.holder ?? "—"),
      el("div", { class: "meta" }, busy ? `slot ${s.slot} · ${until(s.expires_at)}` : "Free")),
    busy
      ? el("div", { class: "card-actions" },
          s.state === "leased" ? el("button", { class: "btn btn-secondary", onclick: () => openLive(s) }, "Open live view") : null,
          s.state === "leased" ? el("button", { class: "btn btn-tertiary", onclick: () => act(() => api(`/api/leases/${s.lease_id}/heartbeat`, { method: "POST" })) }, "Extend") : null,
          el("button", { class: "btn btn-tertiary", onclick: () => release(s) }, "Release"))
      : null);
}

async function release(s) {
  const other = !s.holder?.startsWith("ui:");
  if (other && !confirm(`${s.holder} is using this device. Force-release it?`)) return;
  await act(() => api(`/api/leases/${s.lease_id}`, { method: "DELETE" }));
}

async function renderDevices() {
  const st = await api("/api/status");
  const used = st.slots.filter((s) => s.state !== "free").length;
  $("#summary").textContent = `${used} of ${st.slots.length} in use` + (st.queue_depth ? ` · ${st.queue_depth} waiting` : "");
  $("#slots").replaceChildren(...st.slots.map(slotCard));
}

$("#boot-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.submitter;
  btn.disabled = true;
  btn.textContent = "Booting…";
  await act(() => api("/api/leases", { method: "POST", body: JSON.stringify({ profile: $("#boot-profile").value }) }));
  btn.disabled = false;
  btn.textContent = "Boot device";
});

// ---- profiles
function fillSelect(sel, values, current) {
  sel.replaceChildren(...values.map((v) => el("option", { value: v }, v)));
  if (current && values.includes(current)) sel.value = current;
}

function syncProfileForm() {
  const f = $("#profile-form");
  const ff = f.form_factor.value;
  const images = Object.entries(state.catalog.system_images).filter(([, v]) => v.form_factors.includes(ff)).map(([k]) => k);
  fillSelect(f.system_image, images, f.system_image.value);
  fillSelect(f.device, state.catalog.devices[ff], f.device.value);
}

async function renderProfiles() {
  state.profiles = await api("/api/profiles");
  fillSelect($("#boot-profile"), state.profiles.map((p) => p.name), $("#boot-profile").value);
  $("#profile-rows").replaceChildren(...state.profiles.map((p) =>
    el("tr", {},
      el("td", {}, p.name), el("td", {}, p.form_factor), el("td", { class: "mono" }, p.system_image),
      el("td", { class: "mono" }, p.device), el("td", {}, `${p.ram_mb} MB`), el("td", {}, String(p.cores)),
      el("td", {},
        el("button", { class: "btn btn-tertiary", onclick: () => editProfile(p) }, "Edit"),
        el("button", { class: "btn btn-tertiary", onclick: () => act(() => api(`/api/profiles/${p.name}`, { method: "DELETE" })) }, "Delete")))));
}

function editProfile(p) {
  const f = $("#profile-form");
  for (const k of ["name", "ram_mb", "cores"]) f[k].value = p[k];
  f.form_factor.value = p.form_factor;
  syncProfileForm();
  f.system_image.value = p.system_image;
  f.device.value = p.device;
  f.name.focus();
}

$("#profile-form").form_factor.addEventListener("change", syncProfileForm);
$("#profile-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { form_factor: f.form_factor.value, system_image: f.system_image.value, device: f.device.value,
                 ram_mb: Number(f.ram_mb.value), cores: Number(f.cores.value) };
  await act(() => api(`/api/profiles/${encodeURIComponent(f.name.value)}`, { method: "PUT", body: JSON.stringify(body) }));
});

// ---- history
async function renderHistory() {
  const rows = await api("/api/leases");
  $("#history-rows").replaceChildren(...(rows.length ? rows.map((l) =>
    el("tr", {},
      el("td", { class: "meta" }, `${ago(l.created_at)} ago`), el("td", {}, l.profile), el("td", {}, String(l.slot)),
      el("td", { class: "mono" }, l.holder),
      el("td", { class: "meta" }, l.ended_at ? duration(l.ended_at - l.created_at) : "running"),
      el("td", {}, el("span", { class: "badge", "data-state": l.state === "ended" ? "free" : l.state }, el("span", { class: "dot" }), l.end_reason ?? l.state))))
    : [el("tr", {}, el("td", { class: "empty", colspan: "6" }, "No leases yet."))]));
}

// ---- live view
function openLive(s) {
  const dlg = $("#live-dialog");
  const canvas = $("#live-canvas");
  const ctx = canvas.getContext("2d");
  $("#live-title").textContent = `${s.profile} · slot ${s.slot}`;
  $("#live-sub").textContent = s.holder;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/leases/${s.lease_id}/live`);
  ws.binaryType = "blob";
  ws.onmessage = async (ev) => {
    const bmp = await createImageBitmap(ev.data);
    if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
      canvas.width = bmp.width;
      canvas.height = bmp.height;
    }
    ctx.drawImage(bmp, 0, 0);
    bmp.close();
  };
  ws.onclose = (ev) => {
    if (dlg.open && ev.code !== 1000) $("#live-sub").textContent = "Disconnected. The lease may have ended.";
  };
  const send = (m) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(m));
  const point = (ev, down) => {
    const r = canvas.getBoundingClientRect();
    send({ t: "touch", x: (ev.clientX - r.left) / r.width, y: (ev.clientY - r.top) / r.height, down });
  };
  let dragging = false;
  const handlers = {
    pointerdown: (ev) => { dragging = true; canvas.setPointerCapture(ev.pointerId); point(ev, true); },
    pointermove: (ev) => { if (dragging) point(ev, true); },
    pointerup: (ev) => { dragging = false; point(ev, false); },
  };
  for (const [k, fn] of Object.entries(handlers)) canvas.addEventListener(k, fn);
  const onKey = (ev) => {
    if (ev.key.length === 1) send({ t: "text", text: ev.key });
    else if (ev.key === "Enter" || ev.key === "Backspace" || ev.key.startsWith("Arrow")) send({ t: "key", key: ev.key });
    else return;
    ev.preventDefault();
  };
  document.addEventListener("keydown", onKey);
  dlg.querySelectorAll("[data-key]").forEach((b) => (b.onclick = () => send({ t: "key", key: b.dataset.key })));
  state.live = () => {
    ws.close(1000);
    for (const [k, fn] of Object.entries(handlers)) canvas.removeEventListener(k, fn);
    document.removeEventListener("keydown", onKey);
  };
  dlg.showModal();
}

$("#live-close").addEventListener("click", () => $("#live-dialog").close());
$("#live-dialog").addEventListener("close", () => { state.live?.(); state.live = null; });

// ---- refresh loop
async function act(fn) {
  try { await fn(); showError(null); } catch (err) { showError(err); }
  await refresh();
}

async function refresh() {
  try {
    const view = document.querySelector('.tab[aria-selected="true"]').dataset.view;
    await renderProfiles();
    if (view === "devices") await renderDevices();
    if (view === "history") await renderHistory();
  } catch (err) { showError(err); }
}

(async () => {
  try {
    const [me, catalog] = await Promise.all([api("/api/me"), api("/api/catalog")]);
    state.catalog = catalog;
    $("#whoami").textContent = me.user;
    const f = $("#profile-form");
    fillSelect(f.form_factor, Object.keys(catalog.devices));
    syncProfileForm();
  } catch (err) { showError(err); }
  await refresh();
  setInterval(() => { if (!state.live) refresh(); }, 3000);
})();
