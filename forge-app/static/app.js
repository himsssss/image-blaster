// Scene Forge UI — polls /api/p/<slug>/state and renders the pipeline. Vanilla JS, no build step.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const api = async (path, body) => {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const file = (p) => `/files/${slug}/${p}?t=${Date.now() >> 12}`;
const fileOf = (sl, p) => `/files/${sl}/${p}`;
const ago = (t) => { const d = (Date.now() / 1000 - t); return d < 90 ? "just now" : d < 5400 ? `${Math.round(d / 60)} min ago` : d < 129600 ? `${Math.round(d / 3600)} h ago` : `${Math.round(d / 86400)} d ago`; };
const mb = (b) => b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`;

let slug = localStorage.getItem("forge.slug") || "";
let S = null;            // last server state
let an = null;           // analysis being edited
let dirty = false;       // unsaved analysis edits
let sel = -1;            // selected object index
let step = localStorage.getItem("forge.step") || "objects";
// page links (#library, #library/models, #models, #check, …): the bookmarks above Claude's chat open these
const STEPS = ["new", "library", "objects", "views", "models", "blender", "check", "final"];
function fromHash() {
  const [h, sub] = location.hash.replace(/^#\/?/, "").split("/");
  if (!STEPS.includes(h)) return null;
  if (h === "library" && (sub === "models" || sub === "projects")) { try { localStorage.setItem("forge.libtab", sub); } catch (e) {} }
  return h;
}
step = fromHash() || step;

// ---------- projects ----------
async function loadProjects() {
  const ps = await api("/api/projects");
  const sel = $("#project");
  sel.innerHTML = ps.map((p) => `<option value="${p.slug}">${p.slug} · ${p.objects} objects</option>`).join("");
  if (!ps.find((p) => p.slug === slug)) slug = ps[0]?.slug || "";
  sel.value = slug;
  if (!slug) show("new"); else show(step);
}
$("#project").onchange = (e) => { slug = e.target.value; localStorage.setItem("forge.slug", slug); an = null; dirty = false; sel = -1; refresh(); };
$("#newBtn").onclick = () => show("new");
$("#libBtn").onclick = () => show("library");

let upload = null;
$("#drop").onclick = () => $("#file").click();
$("#drop").ondragover = (e) => e.preventDefault();
$("#drop").ondrop = (e) => { e.preventDefault(); pick(e.dataTransfer.files[0]); };
$("#file").onchange = (e) => pick(e.target.files[0]);
function pick(f) {
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => { upload = { filename: f.name, data: rd.result }; $("#preview").src = rd.result; };
  rd.readAsDataURL(f);
  if (!$("#slug").value) $("#slug").value = f.name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
}
$("#create").onclick = async () => {
  if (!upload) return alert("Choose an image first");
  try {
    const r = await api("/api/projects", { slug: $("#slug").value, ...upload });
    slug = r.slug; localStorage.setItem("forge.slug", slug);
    await loadProjects(); show("objects");
    await job("analyze");
  } catch (e) { alert(e.message); }
};

// ---------- navigation ----------
function show(name) {
  if (name !== "new") { step = name; localStorage.setItem("forge.step", name); }
  const want = "#" + name + (name === "library" && localStorage.getItem("forge.libtab") === "models" ? "/models" : "");
  if (location.hash !== want) history.replaceState(null, "", want);
  $$(".step").forEach((s) => s.classList.toggle("active", s.id === "s-" + name));
  $("#libBtn").classList.toggle("active", name === "library");
  $$("#steps button").forEach((b) => b.classList.toggle("active", b.dataset.step === name));
  render();
}
$$("#steps button").forEach((b) => (b.onclick = () => show(b.dataset.step)));

// ---------- jobs ----------
async function job(type, params = {}) {
  if (dirty) await saveAnalysis();
  await api(`/api/p/${slug}/job`, { type, params });
  refresh();
}
$$("[data-job]").forEach((b) => (b.onclick = () => job(b.dataset.job, b.dataset.custom ? { task: b.dataset.custom } : {})));
$("#verifyBtn").onclick = () => job("verify", { iterations: +$("#iters").value || 6 });
$("#viewsAll").onclick = () => job("views", { objects: meshyObjects().map((o) => o.name), angles: +$("#angles").value });
$("#meshyAll").onclick = async () => {
  const c = S?.meshy_credits || {};
  if (!c.pending) return alert("Every object already has a 3D model.");
  const short = c.balance != null && c.total > c.balance;
  const msg = `Generate ${c.pending} object${c.pending > 1 ? "s" : ""} with Meshy?\n\n` +
    `${c.pending} × ${c.per_object} credits = ${c.total} credits` +
    (c.balance != null ? `\nBalance: ${c.balance} credits → ${c.balance - c.total} left` : "") +
    (short ? `\n\nNot enough credits: Meshy will stop with "402" when the balance runs out.` : "");
  if (!confirm(msg)) return;
  await api(`/api/p/${slug}/meshy`, {}); refresh();
};
$("#crops").onclick = async () => { if (dirty) await saveAnalysis(); const r = await api(`/api/p/${slug}/crops`, {}); if (r.err) alert(r.err); refresh(); };

function renderJobs() {
  const js = (S?.jobs || []).slice().reverse();
  $("#jobList").innerHTML = js.map((j) => `
    <li><div class="jt"><span>${esc(j.type)}${j.params?.objects ? ` · ${j.params.objects.length} obj` : ""}${j.params?.object ? ` · ${esc(j.params.object)}` : ""}</span>
      <span class="st-${j.status}">${j.status}</span></div>
      <div class="small muted">${esc(j.created.slice(11))}${j.status === "pending" ? ` · <a href="#" data-cancel="${j.id}">cancel</a>` : ""}</div>
      ${j.notes?.length ? `<div class="notes">${j.notes.slice(-6).map((n) => `<div>${esc(n.t.slice(11))} ${esc(n.text)}</div>`).join("")}</div>` : ""}
      ${j.result ? `<div class="notes"><b>${esc(j.result)}</b></div>` : ""}
    </li>`).join("") || `<li class="small" style="color:var(--muted-foreground)">queue idle — no jobs yet</li>`;
  $$("[data-cancel]").forEach((a) => (a.onclick = async (e) => { e.preventDefault(); await api(`/api/p/${slug}/cancel`, { id: a.dataset.cancel }); refresh(); }));
  const c = S?.claude || "offline";
  const pill = $("#claudeState");
  pill.textContent = { working: "Claude · working", listening: "Claude · online", offline: "Claude · offline — run /scene-forge-app" }[c];
  pill.className = "pill " + ({ working: "run", listening: "ok", offline: "bad" }[c]);
}

// ---------- step 1: objects ----------
const meshyObjects = () => (an?.objects || S?.objects || []).filter((o) => o.source === "meshy");
// box palette per theme: neon in cyber; paper keeps ink-on-paper (ink boxes, orange = selected)
const NEON = ["#00ff88", "#ff00ff", "#00d4ff", "#ffd60a", "#ff3366", "#a78bfa", "#5eead4", "#fb923c"];
const theme = () => document.documentElement.dataset.theme || "cyber";
const boxColor = (i) => (theme() === "paper" ? (i === sel ? "#F54E00" : "#26251E") : NEON[i % NEON.length]);
function drawBoxes() {
  const img = $("#ref"), cv = $("#boxes");
  if (!img.naturalWidth || !an) return;
  cv.width = img.naturalWidth; cv.height = img.naturalHeight;
  const g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height);
  const lw = Math.max(2, cv.width / 500);
  (an.objects || []).forEach((o, i) => {
    if (!o.bbox) return;
    const [x0, y0, x1, y1] = o.bbox, c = boxColor(i), paper = theme() === "paper";
    g.strokeStyle = c; g.lineWidth = i === sel ? lw * 2.2 : lw; g.setLineDash(o.source === "procedural" ? [lw * 4, lw * 3] : []);
    g.shadowColor = c; g.shadowBlur = paper ? 0 : (i === sel ? lw * 8 : lw * 3); // neon glow (cyber only)
    g.strokeRect(x0, y0, x1 - x0, y1 - y0);
    g.shadowBlur = 0; g.setLineDash([]);
    const fs = Math.max(14, cv.width / 90), lh = fs + 6;
    g.font = paper ? `${fs}px Inter, sans-serif` : `${fs}px "Share Tech Mono", monospace`;
    const label = paper ? o.name : o.name.toUpperCase(), tw = g.measureText(label).width + 12;
    g.fillStyle = c; g.beginPath();                                          // chamfered tag
    g.moveTo(x0, y0 - lh); g.lineTo(x0 + tw - 6, y0 - lh); g.lineTo(x0 + tw, y0 - lh + 6); g.lineTo(x0 + tw, y0); g.lineTo(x0, y0); g.fill();
    g.fillStyle = paper ? "#F7F7F4" : "#0a0a0f"; g.fillText(label, x0 + 6, y0 - 5);
  });
  (an.ignore || []).forEach(([x0, y0, x1, y1]) => { g.strokeStyle = "#888"; g.setLineDash([6, 6]); g.strokeRect(x0, y0, x1 - x0, y1 - y0); });
}
let drag = null;
$("#boxes").onmousedown = (e) => { if (sel < 0) return; const p = toImg(e); drag = { x: p.x, y: p.y }; };
$("#boxes").onmousemove = (e) => {
  if (!drag || sel < 0) return; const p = toImg(e);
  an.objects[sel].bbox = [Math.round(Math.min(drag.x, p.x)), Math.round(Math.min(drag.y, p.y)), Math.round(Math.max(drag.x, p.x)), Math.round(Math.max(drag.y, p.y))];
  dirty = true; drawBoxes();
};
window.addEventListener("mouseup", () => { if (drag) { drag = null; renderObjList(); } });
function toImg(e) { const cv = $("#boxes"), r = cv.getBoundingClientRect(); return { x: (e.clientX - r.left) * cv.width / r.width, y: (e.clientY - r.top) * cv.height / r.height }; }

function renderObjList() {
  if (!an) return;
  $("#objList").innerHTML = (an.objects || []).map((o, i) => `
    <li data-i="${i}" class="${i === sel ? "sel" : ""}"><span class="swatch" style="color:${boxColor(i)}"></span>
      <span style="flex:1">${esc(o.name)}</span>
      ${o.source === "meshy" && !o.structure ? `<span class="warn">no structure</span>` : `<span class="tag">${esc(o.source || "")}</span>`}</li>`).join("");
  $$("#objList li").forEach((li) => (li.onclick = () => { sel = +li.dataset.i; renderObjList(); drawBoxes(); fillEditor(); }));
}
function fillEditor() {
  const o = an?.objects?.[sel]; $("#objEdit").classList.toggle("hidden", !o); if (!o) return;
  $$("#objEdit [data-f]").forEach((el) => (el.value = o[el.dataset.f] ?? ""));
}
$$("#objEdit [data-f]").forEach((el) => (el.oninput = () => {
  const o = an.objects[sel]; const v = el.value;
  if (v === "" && el.dataset.f === "mount") delete o.mount; else o[el.dataset.f] = v;
  dirty = true; renderObjList(); drawBoxes();
}));
$("#addObj").onclick = () => {
  const n = $("#newName").value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-"); if (!n || !an) return;
  an.objects.push({ name: n, source: "meshy", bbox: [10, 10, 120, 120], desc: "", structure: "" });
  sel = an.objects.length - 1; dirty = true; $("#newName").value = ""; renderObjList(); drawBoxes(); fillEditor();
};
$("#delObj").onclick = () => { if (sel < 0) return; an.objects.splice(sel, 1); sel = -1; dirty = true; renderObjList(); drawBoxes(); fillEditor(); };
async function saveAnalysis() { await api(`/api/p/${slug}/analysis`, { analysis: an }); dirty = false; }
$("#saveAn").onclick = async () => { await saveAnalysis(); refresh(); };

// ---------- step 2: views ----------
function renderViews() {
  const objs = (S?.objects || []).filter((o) => o.source === "meshy");
  $("#viewGrid").innerHTML = objs.map((o) => `
    <div class="card"><h4>${esc(o.name)} <span class="pill ${o.views.length >= 3 ? "ok" : ""}">${o.views.length} views</span></h4>
      <div class="thumbs">${o.crop ? `<img class="crop" src="${file(`objects/${o.name}/0-crop.png`)}" title="crop">` : ""}
        ${o.views.slice(0, 7).map((v) => `<img src="${file(`objects/${o.name}/views/${v}`)}" title="${esc(v)}">`).join("")}</div>
      <div class="cardbar"><button class="ghost" data-views="${esc(o.name)}">${o.views.length ? "Regenerate" : "Generate"} views</button></div></div>`).join("")
    || `<p class="muted">No objects yet — run the analysis first.</p>`;
  $$("[data-views]").forEach((b) => (b.onclick = () => job("views", { objects: [b.dataset.views], angles: +$("#angles").value, regenerate: true })));
}

// ---------- step 3: models ----------
const mvCache = {};
function renderModels() {
  const c = S?.meshy_credits || {};
  const short = c.balance != null && c.total > c.balance;
  $("#meshyKey").textContent = !S?.meshy_key ? "MESHY_API_KEY missing in .env"
    : c.balance != null ? `Balance ${c.balance} credits` : `Balance unavailable${c.balance_error ? ` (${c.balance_error})` : ""}`;
  $("#meshyKey").className = "pill " + (!S?.meshy_key || short ? "bad" : "ok");
  const btn = $("#meshyAll");
  btn.textContent = c.pending ? `Generate all · Meshy · ${c.total} credits` : "All models ready";
  btn.disabled = !c.pending || !S?.meshy_key;
  btn.title = c.pending ? `${c.pending} object${c.pending > 1 ? "s" : ""} × ${c.per_object} credits` +
    (c.priced_from ? ` (average of ${c.priced_from} past Meshy jobs)` : " (default estimate)") +
    (short ? " — more than your balance" : "") : "";
  const objs = (S?.objects || []).filter((o) => o.source === "meshy");
  const grid = $("#modelGrid");
  const want = objs.map((o) => o.name).join("|");
  if (grid.dataset.k !== want) { grid.innerHTML = objs.map((o) => `<div class="card" id="m-${o.name}"></div>`).join(""); grid.dataset.k = want; }
  objs.forEach((o) => {
    const el = $(`#m-${CSS.escape(o.name)}`); const m = o.meshy || {};
    const key = `${o.glb}|${m.status}|${m.progress}|${o.versions}|${o.model_source}`;
    if (mvCache[o.name] === key) return; mvCache[o.name] = key;
    el.classList.add("clickable"); el.tabIndex = 0; el.setAttribute("role", "button"); el.setAttribute("aria-label", `Edit model ${o.name}`);
    el.innerHTML = `<h4>${esc(o.name)} <span class="pill ${o.glb ? "ok" : m.status === "failed" ? "bad" : m.status === "running" ? "run" : ""}">${o.glb ? (o.model_source !== "meshy" ? esc(o.model_source) : "ready") : esc(m.status || "none")}</span></h4>
      ${o.glb ? `<model-viewer src="${file(`objects/${o.name}/1-${o.name}.glb`)}" camera-controls auto-rotate shadow-intensity="0.6" exposure="1.1"></model-viewer>`
        : `<div class="progress"><div style="width:${m.progress || 0}%"></div></div><div class="small muted">${esc(m.last || (o.views.length ? `${o.views.length} views ready` : "needs views first"))}</div>`}
      <div class="cardbar">${!o.glb ? `<button class="ghost" data-meshy="${esc(o.name)}" ${o.views.length ? "" : "disabled"}>Start</button>` : ""}
        <span class="hint">${o.versions ? `${o.versions} older version${o.versions > 1 ? "s" : ""} · ` : ""}click to replace / regenerate</span></div>`;
    const b = $("[data-meshy]", el); if (b) b.onclick = async (e) => { e.stopPropagation(); await api(`/api/p/${slug}/meshy`, { objects: [o.name] }); refresh(); };
    let down = null;   // a drag on the 3D viewer rotates it; only a plain click opens the editor
    el.onpointerdown = (e) => (down = [e.clientX, e.clientY]);
    el.onclick = (e) => { if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return; openModel(o.name); };
    el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openModel(o.name); } };
  });
  if (!objs.length) grid.innerHTML = `<p class="muted">No objects yet.</p>`;
}

// ---------- step 4: blender ----------
function renderBlender() {
  const sc = S?.scores || {};
  const rows = Object.entries(sc).slice(-8);
  $("#scoreTable").innerHTML = rows.length ? `<table><tr><th>render</th><th>SSIM</th><th>edges</th><th>colour Δ</th><th>brightness (ref/render)</th><th>warmth (ref/render)</th></tr>
    ${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.ssim ?? ""}</td><td>${v.edge_iou ?? ""}</td><td>${v.color_de ?? ""}</td><td>${(v.luma || []).join(" / ")}</td><td>${(v.warmth_b || []).join(" / ")}</td></tr>`).join("")}</table>` : "";
  const loop = (S?.loop || []).slice(-6).reverse();
  $("#loopStrip").innerHTML = loop.map((l) => `<figure><img src="${file(l.compare)}" loading="lazy"><figcaption>${esc(l.tag)} — reference | render | edges (red = reference, cyan = render)</figcaption></figure>`).join("")
    || `<p class="muted">No renders yet.</p>`;
  const fp = S?.files?.["loop/basis/fit-preview.png"]; $("#fitPreview").classList.toggle("hidden", !fp); if (fp) $("#fitPreview").src = file("loop/basis/fit-preview.png");
}

// ---------- step 5: check ----------
function renderCheck() {
  const rs = S?.renders || []; const cur = $("#renderSrc").value;
  $("#renderSrc").innerHTML = rs.slice().reverse().map((r) => `<option ${r === cur ? "selected" : ""}>${esc(r)}</option>`).join("");
  const src = $("#renderSrc").value;
  const pl = S?.placement || {};
  const objs = (S?.objects || []).filter((o) => o.bbox && o.source === "meshy");
  $("#checkGrid").innerHTML = src ? objs.map((o) => {
    const p = pl[o.name] || {}; const bb = o.bbox.join(",");
    return `<div class="card"><h4>${esc(o.name)} ${p.status ? `<span class="pill ${p.status === "ok" ? "ok" : "bad"}">${esc(p.status)}</span>` : ""}</h4>
      <div class="pair"><figure><img src="/api/p/${slug}/crop?src=reference.png&bbox=${bb}"><figcaption>reference</figcaption></figure>
        <figure><img src="/api/p/${slug}/crop?src=${encodeURIComponent(src)}&bbox=${bb}&t=${Date.now() >> 14}"><figcaption>${esc(src)}</figcaption></figure></div>
      ${p.yaw != null || p.note ? `<div class="small muted">${p.yaw != null ? `yaw ${p.yaw}° · ` : ""}${p.size_m ? `size ${p.size_m.join("×")} m · ` : ""}${esc(p.note || "")}</div>` : ""}
      <div class="row"><span class="field"><input placeholder="what's wrong? e.g. turned the wrong way" aria-label="Problem with ${esc(o.name)}" data-fixnote="${esc(o.name)}"></span><button class="secondary" data-fix="${esc(o.name)}">Fix</button></div></div>`;
  }).join("") : `<p class="muted">No render yet — run Place + pose in step 4.</p>`;
  $$("[data-fix]").forEach((b) => (b.onclick = () => {
    const note = $(`[data-fixnote="${CSS.escape(b.dataset.fix)}"]`).value;
    job("custom", { task: "fix-object", object: b.dataset.fix, note });
  }));
  const qc = S?.files?.["qc-sheet.jpg"]; $("#qcSheet").classList.toggle("hidden", !qc); if (qc) $("#qcSheet").src = file("qc-sheet.jpg");
}
$("#renderSrc").onchange = () => renderCheck();



// ---------- step 6: final project ----------
let finalKey = "";
// tiny markdown for problems.md: headings, bullets, tables, bold — escaped first
function md(text) {
  const inline = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const out = []; let table = null, list = null;
  const flush = () => { if (table) { out.push(`<table>${table.join("")}</table>`); table = null; } if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; } };
  for (const line of text.split("\n")) {
    if (/^\|/.test(line)) {
      if (/^\|\s*-/.test(line)) continue;
      const cells = line.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      if (!table) { flush(); table = [`<tr>${cells.map((c) => `<th>${c}</th>`).join("")}</tr>`]; } else table.push(`<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`);
      continue;
    }
    if (/^\s*[-*] /.test(line)) { if (table) flush(); (list ||= []).push(`<li>${inline(line.replace(/^\s*[-*] /, ""))}</li>`); continue; }
    flush();
    const h = line.match(/^(#{1,3}) (.*)/);
    if (h) out.push(`<h${h[1].length + 2}>${inline(h[2])}</h${h[1].length + 2}>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  flush(); return out.join("");
}
function renderFinal() {
  const F = S?.final || {};
  const key = JSON.stringify([slug, F, Object.keys(S?.scores || {}).slice(-1)]);
  if (key === finalKey) return; finalKey = key;
  // newest actual render (final-render*.png or a loop iteration), not the comparison sheets
  const hero = (F.outputs || []).filter((o) => /final-render|^loop\//.test(o.path)).sort((a, b) => b.mtime - a.mtime)[0] || F.outputs?.[0];
  $("#finalHero").src = hero ? file(hero.path) : ""; $("#finalHero").classList.toggle("hidden", !hero);
  $("#finalHeroCap").textContent = hero ? `${hero.path} · ${ago(hero.mtime)}` : "No render yet — run Render final.";
  const b = F.blend;
  $("#blendPill").textContent = b ? "saved" : "missing"; $("#blendPill").className = "pill " + (b ? "ok" : "bad");
  $("#blendInfo").innerHTML = b ? `<code>worlds/${esc(slug)}/forge/${esc(b.path)}</code><br>${mb(b.bytes)} · saved ${ago(b.mtime)}` : "No Blender file yet — it is written when Claude places the scene.";
  $("#blendOpen").disabled = !b || !F.blender_app; $("#blendOpen").title = F.blender_app ? "" : "Blender.app not found in Applications";
  $("#blendReveal").disabled = !b;
  $("#blendDl").classList.toggle("hidden", !b); if (b) $("#blendDl").href = `/files/${slug}/${b.path}`;
  $("#snapBlends").innerHTML = (F.snapshot_blends || []).length ? `<div class="label" style="margin-top:12px">Saved versions</div><ul class="snaps">${F.snapshot_blends.map((sb, i) => `
      <li><span></span><div><b>${esc(sb.name)}</b><div class="small meta">${mb(sb.bytes)} · ${ago(sb.mtime)}</div></div>
      <button class="ghost" data-openblend="${i}">Open</button></li>`).join("")}</ul>` : "";
  $$("[data-openblend]").forEach((bt) => (bt.onclick = () => openBlend(F.snapshot_blends[+bt.dataset.openblend].path)));
  const sc = Object.entries(S?.scores || {}), last = sc[sc.length - 1], first = sc[0];
  $("#finalScore").innerHTML = last ? `<table><tr><th></th><th>SSIM</th><th>edges</th><th>colour Δ</th></tr>
    ${first && first !== last ? `<tr><td>first · ${esc(first[0])}</td><td>${first[1].ssim}</td><td>${first[1].edge_iou}</td><td>${first[1].color_de}</td></tr>` : ""}
    <tr><td>latest · ${esc(last[0])}</td><td>${last[1].ssim}</td><td>${last[1].edge_iou}</td><td>${last[1].color_de}</td></tr></table>` : "";
  $("#finalOuts").innerHTML = (F.outputs || []).map((o) => `<figure class="card out"><a href="${file(o.path)}" target="_blank" rel="noopener"><img src="${file(o.path)}" alt="${esc(o.path)}" loading="lazy"></a>
      <figcaption>${esc(o.path)} · ${mb(o.bytes)}</figcaption><a class="dl" href="/files/${slug}/${o.path}" download>download</a></figure>`).join("") || `<p class="muted">No outputs yet.</p>`;
  $("#finalProblems").innerHTML = F.problems ? md(F.problems) : `<p class="muted">No problem list yet — Claude writes problems.md after each matching pass.</p>`;
}
async function openBlend(path) {
  try { await api(`/api/p/${slug}/open-blend`, { path }); } catch (e) { return alert(e.message); }
}
$("#blendOpen").onclick = () => openBlend(S.final.blend.path);
$("#blendReveal").onclick = async () => { try { await api(`/api/p/${slug}/open-blend`, { path: S.final.blend.path, how: "reveal" }); } catch (e) { alert(e.message); } };
$("#finalSave").onclick = () => { show("library"); setTimeout(() => $("#snapName").focus(), 50); };

// ---------- library ----------
const MODEL_CATS = ["Seating", "Tables", "Lighting", "Storage", "Beds", "Plants", "Textiles", "Decor", "Fixtures", "Other"];
const ROOM_CATS = ["Living room", "Bedroom", "Kitchen", "Dining", "Bathroom", "Office", "Outdoor", "Other"];
const catFilter = { proj: "All", lib: "All", md: "All" };
// chip row: "All" + every category present (with counts) + any base category; click filters
function chips(el, items, base, key, onPick) {
  const counts = {}; items.forEach((it) => (counts[it.category] = (counts[it.category] || 0) + 1));
  const cats = ["All", ...base.filter((c) => counts[c]), ...Object.keys(counts).filter((c) => !base.includes(c)).sort()];
  if (!cats.includes(catFilter[key])) catFilter[key] = "All";
  el.innerHTML = cats.map((c) => `<button class="chip ${c === catFilter[key] ? "active" : ""}" aria-pressed="${c === catFilter[key]}" data-chip="${esc(c)}">${esc(c)} <span>${c === "All" ? items.length : counts[c]}</span></button>`).join("");
  $$("[data-chip]", el).forEach((b) => (b.onclick = () => { catFilter[key] = b.dataset.chip; onPick(); }));
}
const inCat = (it, key) => catFilter[key] === "All" || it.category === catFilter[key];
// category picker for a card: base list + anything already used + "new…"
function catSelect(cur, base, used, attrs) {
  const all = [...new Set([...base, ...used, cur])];
  return `<select class="catsel" ${attrs} aria-label="Category">${all.map((c) => `<option ${c === cur ? "selected" : ""}>${esc(c)}</option>`).join("")}<option value="__new">New category…</option></select>`;
}
async function pickCategory(sel, save) {
  let v = sel.value;
  if (v === "__new") { v = (prompt("New category name") || "").trim(); if (!v) { libKey = ""; return renderLibrary(); } }
  await save(v); libKey = ""; await loadLibrary(true);
}
let libTab = localStorage.getItem("forge.libtab") || "projects";
let LP = null, LM = null, libKey = "", libT = 0;
$$("[data-lib]").forEach((b) => (b.onclick = () => { libTab = b.dataset.lib; localStorage.setItem("forge.libtab", libTab); history.replaceState(null, "", libTab === "models" ? "#library/models" : "#library"); libKey = ""; loadLibrary(true); }));
window.addEventListener("hashchange", () => {
  const h = fromHash(); if (!h) return;
  libTab = localStorage.getItem("forge.libtab") || libTab; libKey = "";
  show(h);
});
async function loadLibrary(force) {
  if (!force && Date.now() - libT < 8000) return;      // library scans disk: refresh every 8 s, not 3 s
  libT = Date.now();
  [LP, LM] = await Promise.all([api("/api/library/projects"), api("/api/library/models")]);
  renderLibrary();
}
function viewerOrThumb(m, cls = "") {
  return m.thumb ? `<img class="lib-thumb ${cls}" src="${fileOf(m.slug, m.thumb)}" alt="${esc(m.object)} model" loading="lazy">`
    : `<model-viewer class="${cls}" src="${fileOf(m.slug, m.path)}" loading="lazy" camera-controls auto-rotate shadow-intensity="0.5" exposure="1.1" alt="${esc(m.object)} model"></model-viewer>`;
}
function renderLibrary() {
  $$("[data-lib]").forEach((b) => { b.classList.toggle("active", b.dataset.lib === libTab); b.setAttribute("aria-selected", b.dataset.lib === libTab); });
  $("#libProjects").classList.toggle("hidden", libTab !== "projects");
  $("#libModels").classList.toggle("hidden", libTab !== "models");
  $("#saveSlug").textContent = slug || "no project";
  $("#blendSize").textContent = S?.blend_bytes ? `(${mb(S.blend_bytes)})` : "(no .blend yet)";
  const key = JSON.stringify([libTab, LP, LM, $("#libSearch").value, $("#libFilter").value, slug]);
  if (key === libKey) return; libKey = key;
  if (libTab === "projects") {
    chips($("#projCats"), LP || [], ROOM_CATS, "proj", () => { libKey = ""; renderLibrary(); });
    const projUsed = (LP || []).map((p) => p.category);
    $("#projGrid").innerHTML = (LP || []).filter((p) => inCat(p, "proj")).map((p) => `
      <div class="card proj ${p.slug === slug ? "current" : ""}">
        <div class="proj-imgs">${p.reference ? `<img src="${fileOf(p.slug, "reference.png")}" alt="reference" loading="lazy">` : `<div class="noimg">no image</div>`}
          ${p.render ? `<img src="${fileOf(p.slug, p.render)}" alt="latest render" loading="lazy">` : `<div class="noimg">no render yet</div>`}</div>
        <h4>${esc(p.slug)} ${p.slug === slug ? `<span class="pill ok">open</span>` : ""}</h4>
        <div class="catline">${catSelect(p.category, ROOM_CATS, projUsed, `data-pcat="${esc(p.slug)}"`)}</div>
        <div class="small meta">${p.objects} objects · ${p.models}/${p.meshy_objects} 3D models · ${p.blend ? ".blend ✓ · " : ""}updated ${ago(p.updated)}</div>
        ${p.score ? `<div class="small meta">last score ${esc(p.score.tag)}: SSIM ${p.score.ssim} · edges ${p.score.edge_iou} · colour Δ ${p.score.color_de}</div>` : ""}
        <div class="cardbar"><button class="${p.slug === slug ? "ghost" : "primary"}" data-open="${esc(p.slug)}">${p.slug === slug ? "Go to objects" : "Open project"}</button></div>
        ${p.snapshots.length ? `<details><summary>${p.snapshots.length} saved snapshot${p.snapshots.length > 1 ? "s" : ""}</summary><ul class="snaps">
          ${p.snapshots.map((sn) => `<li>${sn.render ? `<img src="${fileOf(p.slug, `library/${sn.id}/${sn.render}`)}" alt="" loading="lazy">` : ""}
            <div><b>${esc(sn.name)}</b><div class="small meta">${new Date(sn.created * 1000).toLocaleString()} · ${sn.files.length} files${sn.files.includes("scene-forge.blend") ? " incl. .blend" : ""}</div>
            ${sn.note ? `<div class="small">${esc(sn.note)}</div>` : ""}</div>
            <button class="ghost" data-restore="${esc(p.slug)}|${esc(sn.id)}">Restore</button></li>`).join("")}</ul></details>` : ""}
      </div>`).join("") || `<p class="muted">No projects yet.</p>`;
    $$("[data-pcat]").forEach((sel) => (sel.onchange = () => pickCategory(sel, (v) => api(`/api/p/${sel.dataset.pcat}/category`, { category: v }))));
    $$("[data-open]").forEach((b) => (b.onclick = () => { slug = b.dataset.open; localStorage.setItem("forge.slug", slug); $("#project").value = slug; an = null; dirty = false; sel = -1; show("objects"); refresh(); }));
    $$("[data-restore]").forEach((b) => (b.onclick = async () => {
      const [sl, id] = b.dataset.restore.split("|");
      if (!confirm(`Restore snapshot ${id} into ${sl}?\n\nThe current state is saved as an automatic snapshot first. If the snapshot has a .blend, reopen it in Blender afterwards.`)) return;
      const r = await api(`/api/p/${sl}/restore`, { id }); alert(`Restored: ${r.restored.join(", ") || "nothing"}`); loadLibrary(true); refresh();
    }));
  } else {
    const q = $("#libSearch").value.trim().toLowerCase(), f = $("#libFilter").value;
    const base = (LM || []).filter((m) => (!q || `${m.object} ${m.slug} ${m.label} ${m.category}`.toLowerCase().includes(q)) && (f === "all" || (f === "current") === m.current));
    chips($("#libCats"), base, MODEL_CATS, "lib", () => { libKey = ""; renderLibrary(); });
    const ms = base.filter((m) => inCat(m, "lib"));
    const used = (LM || []).map((m) => m.category);
    const targets = (S?.objects || []).filter((o) => o.source === "meshy").map((o) => o.name);
    $("#libGrid").innerHTML = ms.map((m, i) => `
      <div class="card lib-card">${viewerOrThumb(m)}
        <h4>${esc(m.object)} <span class="pill ${m.current ? "ok" : ""}">${m.current ? "in use" : "older"}</span></h4>
        <div class="small meta">${esc(m.slug)} · ${esc(m.source)}${m.label ? ` · ${esc(m.label)}` : ""} · ${mb(m.bytes)} · ${ago(m.mtime)}</div>
        <div class="catline">${catSelect(m.category, MODEL_CATS, used, `data-mcat="${i}"`)}</div>
        <div class="row use-row">${targets.length ? `<span class="field"><select data-target="${i}" aria-label="Object to replace">${targets.map((t) => `<option ${t === m.object ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></span>
          <button class="ghost" data-use="${i}">Use in ${esc(slug)}</button>` : ""}<a class="dl" href="${fileOf(m.slug, m.path)}" download>.glb</a></div>
      </div>`).join("") || `<p class="muted">No 3D models match.</p>`;
    $$("[data-mcat]").forEach((sel) => (sel.onchange = () => { const m = ms[+sel.dataset.mcat];
      pickCategory(sel, (v) => api("/api/library/category", { slug: m.slug, path: m.path, category: v })); }));
    $$("[data-use]").forEach((b) => (b.onclick = () => { const m = ms[+b.dataset.use]; useModel($(`[data-target="${b.dataset.use}"]`).value, m); }));
  }
}
$("#libSearch").oninput = () => renderLibrary();
$("#libFilter").onchange = () => renderLibrary();
$("#snapSave").onclick = async () => {
  if (!slug) return;
  const r = await api(`/api/p/${slug}/snapshot`, { name: $("#snapName").value.trim(), note: $("#snapNote").value.trim(), blend: $("#snapBlend").checked });
  $("#snapName").value = ""; $("#snapNote").value = ""; $("#snapBlend").checked = false;
  alert(`Saved "${r.name}" (${r.files.length} files)`); loadLibrary(true);
};
async function useModel(target, m) {
  const cur = (S?.objects || []).find((o) => o.name === target);
  if (!confirm(`Use ${m.slug}/${m.object}${m.current ? "" : " (older version)"} as "${target}" in ${slug}?` + (cur?.glb ? `\n\nThe current ${target} model is kept as an older version.` : ""))) return;
  await api(`/api/p/${slug}/model`, { object: target, action: "use", from_slug: m.slug, from_path: m.path, label: `${m.slug}/${m.object}` });
  Object.keys(mvCache).forEach((k) => delete mvCache[k]); libKey = ""; await loadLibrary(true); refresh();
  if (mdObj) openModel(mdObj);
}

// ---------- model editor (click a model card) ----------
const mdlg = $("#modelDlg");
let mdObj = null;
async function openModel(name) {
  if (mdObj !== name) catFilter.md = "All";
  mdObj = name;
  if (!LM || Date.now() - libT > 3000) { libT = Date.now(); LM = await api("/api/library/models"); }
  const o = (S?.objects || []).find((x) => x.name === name) || {};
  const c = S?.meshy_credits || {};
  $("#mdTitle").textContent = name;
  $("#mdViewer").innerHTML = o.glb ? `<model-viewer src="${file(`objects/${name}/1-${name}.glb`)}" camera-controls auto-rotate shadow-intensity="0.6" exposure="1.1" alt="${esc(name)} current model"></model-viewer>`
    : `<div class="noimg">no model yet${o.meshy?.status ? ` · ${esc(o.meshy.status)}` : ""}</div>`;
  $("#mdInfo").innerHTML = o.glb ? `Current: <b>${esc(o.model_source || "meshy")}</b>${o.versions ? ` · ${o.versions} older version${o.versions > 1 ? "s" : ""}` : ""}` : "No model yet.";
  $("#mdRegen").textContent = `${o.glb ? "Generate again" : "Generate"} · Meshy · ~${c.per_object || 30} credits`;
  $("#mdRegen").disabled = !S?.meshy_key || !o.views?.length || o.meshy?.status === "running";
  $("#mdRegen").title = !o.views?.length ? "needs views first" : o.meshy?.status === "running" ? "already running" : "";
  $("#mdPlace").disabled = !o.glb;
  const vers = (LM || []).filter((m) => m.slug === slug && m.object === name && !m.current);
  $("#mdVersions").innerHTML = vers.map((m, i) => `<div class="card mini">${viewerOrThumb(m)}
      <div class="small meta">${esc(m.version || "")} · ${esc(m.source)}${m.label ? ` · ${esc(m.label)}` : ""}</div>
      <button class="ghost" data-mdrestore="${i}">Restore</button></div>`).join("") || `<p class="small meta">None yet — replacing or regenerating keeps the old model here.</p>`;
  $$("[data-mdrestore]").forEach((b) => (b.onclick = async () => {
    const m = vers[+b.dataset.mdrestore];
    await api(`/api/p/${slug}/model`, { object: name, action: "restore", path: m.path });
    Object.keys(mvCache).forEach((k) => delete mvCache[k]); LM = null; await refresh(); openModel(name);
  }));
  if (!mdlg.open) { const mine = (LM || []).find((m) => m.slug === slug && m.object === name); if (mine) catFilter.md = mine.category; }
  renderMdLib();
  if (!mdlg.open) mdlg.showModal();
}
function renderMdLib() {
  const q = $("#mdSearch").value.trim().toLowerCase();
  const pool = (LM || []).filter((m) => !(m.slug === slug && m.object === mdObj && m.current))
    .filter((m) => !q || `${m.object} ${m.slug} ${m.label} ${m.category}`.toLowerCase().includes(q));
  chips($("#mdCats"), pool, MODEL_CATS, "md", renderMdLib);
  const ms = pool.filter((m) => inCat(m, "md"))
    .sort((a, b) => (b.object === mdObj) - (a.object === mdObj));   // same object name first
  $("#mdLib").innerHTML = ms.map((m, i) => `<div class="card mini">${viewerOrThumb(m)}
      <div class="small meta"><b>${esc(m.object)}</b> · ${esc(m.category)} · ${esc(m.slug)}${m.current ? "" : " · older"}</div>
      <button class="ghost" data-mduse="${i}">Use this</button></div>`).join("") || `<p class="small meta">Nothing in the library yet.</p>`;
  $$("[data-mduse]").forEach((b) => (b.onclick = () => useModel(mdObj, ms[+b.dataset.mduse])));
}
$("#mdSearch").oninput = () => renderMdLib();
$("#mdClose").onclick = () => mdlg.close();
mdlg.addEventListener("close", () => { mdObj = null; });
mdlg.addEventListener("click", (e) => { if (e.target === mdlg) mdlg.close(); });
$("#mdRegen").onclick = async () => {
  const c = S?.meshy_credits || {};
  if (!confirm(`Generate "${mdObj}" again with Meshy?\n\n~${c.per_object || 30} credits` + (c.balance != null ? ` · balance ${c.balance}` : "") + `\nThe current model is kept as an older version.`)) return;
  await api(`/api/p/${slug}/model`, { object: mdObj, action: "regenerate" });
  Object.keys(mvCache).forEach((k) => delete mvCache[k]); mdlg.close(); refresh();
};
$("#mdUpload").onchange = (e) => {
  const f = e.target.files[0]; if (!f) return;
  const rd = new FileReader();
  rd.onload = async () => {
    try { await api(`/api/p/${slug}/model`, { object: mdObj, action: "upload", filename: f.name, data: rd.result }); }
    catch (err) { return alert(err.message); }
    e.target.value = ""; Object.keys(mvCache).forEach((k) => delete mvCache[k]); LM = null; await refresh(); openModel(mdObj);
  };
  rd.readAsDataURL(f);
};
$("#mdPlace").onclick = async () => { await job("custom", { task: "replace-model", object: mdObj }); mdlg.close(); };

// ---------- settings: theme ----------
const dlg = $("#settings");
$("#settingsBtn").onclick = () => { $$('input[name="theme"]', dlg).forEach((r) => (r.checked = r.value === theme())); dlg.showModal(); };
$$('input[name="theme"]', dlg).forEach((r) => (r.onchange = () => {
  document.documentElement.dataset.theme = r.value;
  try { localStorage.setItem("forge.theme", r.value); } catch (e) { /* private mode: theme just won't persist */ }
  drawBoxes(); renderObjList(); Object.keys(mvCache).forEach((k) => delete mvCache[k]); render();
}));
dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });   // click backdrop to close

// ---------- main loop ----------
function render() {
  if (!S) return;
  renderJobs();
  $$("#steps button").forEach((b) => {
    const objs = S.objects.filter((o) => o.source === "meshy");
    const done = { objects: objs.length > 0 && objs.every((o) => o.crop), views: objs.length > 0 && objs.every((o) => o.views.length >= 2),
      models: objs.length > 0 && objs.every((o) => o.glb), blender: (S.loop || []).length > 0, check: !!S.files["final-render.png"],
      final: !!S.final?.blend }[b.dataset.step];
    b.classList.toggle("done", !!done);
  });
  if (step === "objects") {
    if (!dirty) { an = JSON.parse(JSON.stringify(S.analysis || { objects: [] })); an.objects = an.objects || []; }
    const img = $("#ref"); const want = S.reference ? file("reference.png") : "";
    if (img.dataset.src !== want) { img.dataset.src = want; img.src = want; img.onload = drawBoxes; }
    renderObjList(); drawBoxes();
  }
  if (step === "views") renderViews();
  if (step === "models") renderModels();
  if (step === "blender") renderBlender();
  if (step === "check" && document.activeElement?.dataset?.fixnote === undefined) renderCheck();
  if (step === "library") loadLibrary();
  if (step === "final") renderFinal();
}
async function refresh() {
  if (!slug) return;
  try { S = await api(`/api/p/${slug}/state`); render(); } catch (e) { console.warn(e); }
}
loadProjects().then(refresh);
setInterval(refresh, 3000);
