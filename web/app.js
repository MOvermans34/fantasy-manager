/* Fantasy Manager: frontend (vanilla JS, geen build-stap) */
"use strict";

const S = { state: null, live: null, news: null, cache: { player: {}, defense: {} }, ui: {} };
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = v => typeof v === "number" && isFinite(v);
const f0 = v => num(v) ? Math.round(v).toLocaleString("nl-NL") : "–";
const f1 = v => num(v) ? v.toFixed(1) : "–";
const f2 = v => num(v) ? v.toFixed(2) : "–";
const sg = (v, d = 2) => num(v) ? (v > 0 ? "+" : "") + v.toFixed(d) : "–";
const pc = (v, d = 0) => num(v) ? (v * 100).toFixed(d) + "%" : "–";
const POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"];
const BENCH = ["Bank", "IR"];

/* ---------------- toegang & team ---------------- */
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { } },
};
const AUTH = { code: store.get("fm-code") || "", team: null, teams: null, needsCode: false };
(() => {
  const q = new URLSearchParams(location.search);
  if (q.get("team")) AUTH.team = +q.get("team");
  else if (store.get("fm-team")) AUTH.team = +store.get("fm-team");
})();
class AuthError extends Error { }

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  const sep = path.includes("?") ? "&" : "?";
  const url = path.startsWith("/api/") && AUTH.team ? `${path}${sep}team=${AUTH.team}` : path;
  const headers = Object.assign({}, opts.headers || {}, AUTH.code ? { "X-Access-Code": AUTH.code } : {});
  const r = await fetch(url, Object.assign({}, opts, { headers }));
  if (r.status === 401) { showGate("code", "De toegangscode klopt niet (meer)."); throw new AuthError("geen toegang"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}
async function loadState() {
  if (!AUTH.team) return;
  try {
    const s = await api("/api/state");
    if (s.status !== "ok") { setStatus("Data wordt geladen…"); setTimeout(loadState, 3000); return; }
    const first = !S.state;
    const analyticsChanged = S.state && S.state.analytics.ready !== s.analytics.ready;
    S.state = s;
    if (analyticsChanged) S.cache.player = {};
    if (first) { loadLive(); loadNews(); }
    renderChrome();
    if (first || analyticsChanged || ["overzicht", "selectie", "vergelijken", "scouting"].includes(route().name)) render();
    if (!s.analytics.ready) setTimeout(loadState, 5000);
  } catch (e) { if (e instanceof AuthError) return; setStatus("Server niet bereikbaar: " + e.message); setTimeout(loadState, 5000); }
}
async function loadLive() {
  if (!S.state) return;
  try {
    S.live = await api("/api/live");
    renderChrome();
    const r = route().name;
    if (r === "live" || r === "overzicht") renderLiveParts();
    if (r === "league") render();
  } catch (e) { /* stil */ }
}
async function loadNews() {
  if (!S.state) return;
  try { S.news = await api("/api/news"); if (route().name === "nieuws") render(); } catch (e) { }
}
function setStatus(t) { $("#statusText").textContent = t; }
setInterval(loadState, 120000);
setInterval(() => loadLive(), 15000);
setInterval(loadNews, 120000);

/* ---------------- tooltip & thema ---------------- */
const tip = $("#tip");
const NO_HOVER = matchMedia("(hover: none)").matches;  // touchscreens: geen zwevende tooltips
document.addEventListener("mouseover", e => {
  if (NO_HOVER) return;
  const t = e.target.closest("[data-tip]");
  if (!t) { tip.style.opacity = 0; return; }
  tip.textContent = t.dataset.tip; tip.style.opacity = 1;
});
document.addEventListener("mousemove", e => {
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.max(8, Math.min(e.clientX + 14, innerWidth - w - 8)) + "px";
  tip.style.top = (e.clientY - h - 10 < 8 ? e.clientY + 18 : e.clientY - h - 10) + "px";
});
(() => {
  let saved = null;
  try { saved = localStorage.getItem("fm-theme"); } catch (e) { }
  if (saved) document.documentElement.dataset.theme = saved;
  $("#themeBtn").onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("fm-theme", next); } catch (e) { }
  };
  $("#refreshBtn").onclick = async () => {
    setStatus("Verversen…"); S.cache = { player: {}, defense: {} };
    const r = await api("/api/refresh", { method: "POST" }).catch(() => ({}));
    if (r && r.msg) { setStatus(r.msg); return; }
    setTimeout(() => { loadState(); loadLive(); loadNews(); }, 6000);
  };
})();

/* ---------------- helpers ---------------- */
const P = id => S.state.players[id];
const myRoster = () => S.state.roster.map(P).filter(Boolean);
const oppRoster = () => S.state.oppRoster.map(P).filter(Boolean);
const W = () => S.state.meta.week;
const short = n => (n || "").replace(/\s+(Jr\.?|Sr\.?|II|III|IV|V)$/i, "").split(" ").slice(-1)[0];
/* Initialen: "C.J. Stroud" -> "CS", "Kenneth Walker III" -> "KW" */
const initials = n => {
  const parts = (n || "").replace(/\s+(Jr\.?|Sr\.?|II|III|IV|V)$/i, "").split(/\s+/).filter(Boolean);
  return parts.length ? (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() : "?";
};
/* Klikbare initialen-chips naar de spelerprofielen */
const playerChips = ps => ps.map(p => `<a class="pinit" href="#/speler/${p.id}" onclick="event.stopPropagation()" title="${esc(p.name)} (${esc(p.pos)})" aria-label="${esc(p.name)}, ${esc(p.pos)}" data-tip="${esc(p.name)} · ${esc(p.pos)} · ${esc(p.slot || "")}">${esc(initials(p.name))}</a>`).join("");
const isStarter = p => p.slot && !BENCH.includes(p.slot);

const INJ = {
  QUESTIONABLE: ["Twijfelachtig", "var(--warning)", "▲", 2], DOUBTFUL: ["Onzeker", "var(--serious)", "▲", 3],
  OUT: ["Out", "var(--critical)", "■", 4], INJURY_RESERVE: ["IR", "var(--critical)", "■", 4],
  SUSPENSION: ["Geschorst", "var(--critical)", "■", 4], DAY_TO_DAY: ["Dag-tot-dag", "var(--warning)", "▲", 2],
  INJURED: ["Geblesseerd", "var(--serious)", "▲", 3],
};
function inj(p) {
  const i = INJ[p.injury]; if (!i) return "";
  return `<span class="inj" data-tip="Blessurestatus ESPN: ${esc(p.injury)}"><span style="color:${i[1]}">${i[2]}</span>${i[0]}</span>`;
}
function attr(score, lg) {
  if (!num(score)) return `<span class="attr na${lg ? " lg" : ""}">–</span>`;
  const b = score <= 5 ? 1 : score <= 10 ? 2 : score <= 15 ? 3 : 4;
  return `<span class="attr b${b}${lg ? " lg" : ""}">${Math.round(score)}</span>`;
}
function gradeCls(score) { return score >= 58 ? "pos" : score < 42 ? "neg" : "mid"; }
function grade(edge, withScore) {
  if (!edge) return `<span class="muted">–</span>`;
  const t = `Scheme-matchup ${edge.score}/100${edge.top ? ": " + edge.top : ""}`;
  return `<span class="grade ${gradeCls(edge.score)}" data-tip="${esc(t)}">${edge.grade}${withScore ? ` <span style="font-weight:600;opacity:.8">&nbsp;${edge.score}</span>` : ""}</span>`;
}
function oppStr(p) {
  if (p.bye) return `<span class="chip mid">Bye</span>`;
  if (!p.opp) return `<span class="muted">–</span>`;
  return `${p.home ? "vs" : "@"} <a href="#/scouting/${esc(p.opp)}" onclick="event.stopPropagation()">${esc(p.opp)}</a>`;
}
function fpChip(p) {
  const m = p.fpAllowed; if (!m || p.bye) return "";
  const third = m.of / 3;
  const cls = m.rank <= third ? "neg" : m.rank > m.of - third ? "pos" : "mid";
  const word = cls === "neg" ? "Zwaar" : cls === "pos" ? "Gunstig" : "Neutraal";
  return `<span class="chip ${cls}" data-tip="${esc(`${p.opp} geeft ${p.pos}'s gem. ${f1(m.avg)} fantasy-ptn per week (league-scoring); nr. ${m.of - m.rank + 1} meest van ${m.of}`)}"><span class="dot"></span>${word}</span>`;
}
function kickoff(p) {
  if (!p.kickoff) return "";
  const d = new Date(p.kickoff);
  return d.toLocaleDateString("nl-NL", { weekday: "short" }) + " " + d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
}
function form(p, n = 5) {
  const wk = p.weekly.filter(w => !w.bye).slice(-n);
  return `<span class="form">${wk.map(w => {
    if (w.pts == null) return `<i class="na" data-tip="Week ${w.wk}: niet gespeeld">–</i>`;
    const d = w.proj != null ? w.pts - w.proj : null;
    const c = d == null ? "mid" : d >= 3 ? "pos" : d <= -3 ? "neg" : "mid";
    return `<i class="${c}" data-tip="Week ${w.wk}${w.opp ? " vs " + w.opp : ""}: ${f1(w.pts)} ptn${w.proj != null ? ` (projectie ${f1(w.proj)}, ${sg(d, 1)})` : ""}">${Math.round(w.pts)}</i>`;
  }).join("")}</span>`;
}
function usage(p) {
  const a = p.adv; if (!a) return "–";
  if (p.pos === "QB") return `<span data-tip="EPA per dropback">${sg(a.epa_db)} EPA</span>`;
  if (p.pos === "RB") return `<span data-tip="Aandeel team-carries / team-targets">${pc(a.rush_share)} car · ${pc(a.tshare)} tgt</span>`;
  if (p.pos === "WR" || p.pos === "TE") return `<span data-tip="Aandeel team-targets / WOPR">${pc(a.tshare)} tgt · ${f2(a.wopr)} WOPR</span>`;
  return "–";
}
function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 60) return "zojuist";
  if (s < 3600) return Math.round(s / 60) + " min";
  if (s < 86400) return Math.round(s / 3600) + " uur";
  if (s < 86400 * 7) return Math.round(s / 86400) + " d";
  return new Date(iso).toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
}
function ownerLabel(p) {
  if (p.mine) return "<strong>Mijn team</strong>";
  if (p.oppTeam) return "<span class='muted'>Tegenstander</span>";
  if (p.onTeamId) { const t = S.state.fantasyTeams[p.onTeamId]; return esc(t ? t.abbrev : "Team " + p.onTeamId); }
  return p.status === "WAIVERS" ? "<span class='up'>Waivers</span>" : "<span class='up'>Vrij</span>";
}
const isFree = p => !p.mine && !p.oppTeam && !p.onTeamId;

/* ---------------- grafieken (SVG) ---------------- */
function spark(p, w = 120, h = 28) {
  const wk = p.weekly; const n = wk.length + 1;
  const vals = wk.map(x => x.pts).filter(num).concat(num(p.proj) ? [p.proj] : []);
  const max = Math.max(10, ...vals);
  const x = i => 3 + i * (w - 6) / Math.max(1, n - 1), y = v => h - 3 - v / max * (h - 6);
  let segs = [], d = "";
  wk.forEach((q, i) => { if (q.pts == null) { if (d) segs.push(d); d = ""; return; } d += (d ? "L" : "M") + x(i).toFixed(1) + " " + y(q.pts).toFixed(1); });
  if (d) segs.push(d);
  let s = `<svg class="chart" width="${w}" height="${h}" role="img" aria-label="Punten per week">`;
  if (num(p.avg)) s += `<line x1="0" x2="${w}" y1="${y(p.avg)}" y2="${y(p.avg)}" stroke="var(--border)"/>`;
  segs.forEach(sd => s += `<path d="${sd}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`);
  wk.forEach((q, i) => {
    if (q.pts != null) s += `<circle cx="${x(i)}" cy="${y(q.pts)}" r="1.8" fill="var(--series-1)"/>`;
    s += `<rect x="${x(i) - 5}" y="0" width="10" height="${h}" fill="transparent" data-tip="Week ${q.wk}: ${q.pts != null ? f1(q.pts) + " ptn" : q.bye ? "bye" : "niet gespeeld"}"/>`;
  });
  if (num(p.proj) && !p.bye) {
    s += `<circle cx="${x(n - 1)}" cy="${y(p.proj)}" r="3.2" fill="var(--surface-1)" stroke="var(--text-muted)" stroke-width="1.5" stroke-dasharray="2 1.5"/>`;
    s += `<rect x="${x(n - 1) - 6}" y="0" width="12" height="${h}" fill="transparent" data-tip="Week ${W()} projectie: ${f1(p.proj)}"/>`;
  }
  return s + "</svg>";
}
function weeklyChart(p, snaps) {
  const wk = p.weekly.concat(num(p.proj) && !p.bye ? [{ wk: W(), pts: null, proj: p.proj, future: true, opp: p.opp }] : []);
  const w = 640, h = 190, pl = 30, pb = 26, pt = 10;
  const max = Math.max(10, ...wk.map(q => Math.max(q.pts ?? 0, q.proj ?? 0))) * 1.1;
  const bw = (w - pl) / wk.length;
  const y = v => pt + (h - pt - pb) * (1 - v / max);
  let s = `<svg class="chart" viewBox="0 0 ${w} ${h}" width="100%" role="img" aria-label="Punten per week">`;
  const step = max > 40 ? 10 : 5;
  for (let v = 0; v <= max; v += step) s += `<line x1="${pl}" x2="${w}" y1="${y(v)}" y2="${y(v)}" stroke="var(--border)" stroke-width="${v === 0 ? 1 : .6}"/><text x="${pl - 6}" y="${y(v) + 3}" text-anchor="end" font-size="10" fill="var(--text-muted)">${v}</text>`;
  wk.forEach((q, i) => {
    const cx = pl + i * bw + bw / 2, bwid = Math.min(26, bw * .58);
    if (q.pts != null) {
      const top = y(Math.max(q.pts, 0));
      s += `<path d="M${cx - bwid / 2} ${y(0)} V${top + 4} q0 -4 4 -4 h${bwid - 8} q4 0 4 4 V${y(0)} Z" fill="var(--series-1)"/>`;
    }
    if (q.proj != null) s += `<line x1="${cx - bwid / 2 - 3}" x2="${cx + bwid / 2 + 3}" y1="${y(q.proj)}" y2="${y(q.proj)}" stroke="var(--text-primary)" stroke-width="2" ${q.future ? 'stroke-dasharray="3 2"' : ""}/>`;
    if (snaps && snaps[q.wk] != null) s += `<text x="${cx}" y="${y(0) - 4}" text-anchor="middle" font-size="9" fill="#fff" font-weight="700">${Math.round(snaps[q.wk] * 100)}</text>`;
    s += `<text x="${cx}" y="${h - 12}" text-anchor="middle" font-size="10" fill="var(--text-muted)">${q.wk}</text>`;
    s += `<text x="${cx}" y="${h - 1}" text-anchor="middle" font-size="9" fill="var(--text-muted)">${q.bye ? "bye" : esc(q.opp || "")}</text>`;
    const label = q.bye ? `Week ${q.wk}: bye` : `Week ${q.wk}${q.opp ? " vs " + q.opp : ""}: ${q.pts != null ? f1(q.pts) + " ptn" : q.future ? "nog te spelen" : "niet gespeeld"}${q.proj != null ? " · projectie " + f1(q.proj) : ""}${snaps && snaps[q.wk] != null ? " · " + Math.round(snaps[q.wk] * 100) + "% snaps" : ""}`;
    s += `<rect x="${pl + i * bw}" y="0" width="${bw}" height="${h - pb}" fill="transparent" data-tip="${esc(label)}"/>`;
  });
  return s + "</svg>";
}
function divBar(v, maxAbs, w = 110) {
  if (!num(v)) return "";
  const half = w / 2, len = Math.min(half, Math.abs(v) / maxAbs * half);
  const col = v >= 0 ? "var(--div-pos)" : "var(--div-neg)";
  const x = v >= 0 ? half : half - len;
  return `<svg class="chart" width="${w}" height="12"><rect x="0" y="5" width="${w}" height="2" fill="var(--surface-3)"/><rect x="${x}" y="1" width="${Math.max(2, len)}" height="10" rx="2" fill="${col}"/><rect x="${half - .5}" y="0" width="1" height="12" fill="var(--text-muted)"/></svg>`;
}
function pairBar(a, b, max, w = 120) {
  // speler (a, serie 1) vs league (b, neutraal)
  const sc = v => num(v) ? Math.max(1, Math.min(w, v / max * w)) : 0;
  return `<svg class="chart" width="${w}" height="16"><rect x="0" y="1" width="${sc(a)}" height="6" rx="2" fill="var(--series-1)"/><rect x="0" y="9" width="${sc(b)}" height="6" rx="2" fill="var(--neutral-mark)"/></svg>`;
}

/* ---------------- router ---------------- */
function route() {
  const h = location.hash.replace(/^#\/?/, "") || "overzicht";
  const [name, ...args] = h.split("/").map(decodeURIComponent);
  return { name, args };
}
window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });

const TITLES = { league: "League", overzicht: "Overzicht", selectie: "Selectie", speler: "Spelerprofiel", live: "Wedstrijdcentrum", vergelijken: "Spelersmarkt", scouting: "Scouting defenses", nieuws: "Nieuws" };
function renderChrome() {
  const s = S.state; if (!s) return;
  renderTeamSel();
  const m = s.meta, t = m.team || {};
  $("#brandTeam").textContent = t.name || "Fantasy Manager";
  $("#brandSub").textContent = `${t.wins ?? 0}-${t.losses ?? 0}${t.ties ? "-" + t.ties : ""} · Week ${m.week}${m.demo ? " · demo" : ""}`;
  const live = S.live && S.live.anyLive;
  $("#navLive").hidden = !live;
  const parts = [`ESPN ${new Date(s.generated).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" })}`];
  parts.push(s.analytics.ready ? `nflverse t/m wk ${s.analytics.maxWeek}` : "analytics laden…");
  if (S.live && S.live.updated) parts.push((live ? "LIVE " : "live ") + new Date(S.live.updated).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
  setStatus(parts.join(" · "));
}
function render() {
  if (!S.state) return;
  const r = route();
  $$("#nav a").forEach(a => a.classList.toggle("active", a.dataset.route === r.name || (r.name === "speler" && a.dataset.route === "selectie")));
  $("#pageTitle").textContent = TITLES[r.name] || "Fantasy Manager";
  $("#crumbs").textContent = `${S.state.meta.leagueName || ""} · Seizoen ${S.state.meta.season} · Week ${S.state.meta.week}`;
  const view = $("#view");
  const errs = (S.state.errors || []).slice(-2).map(e => `<div class="err">${esc(e.msg)}</div>`).join("");
  const fn = { league: viewLeague, overzicht: viewHome, selectie: viewSquad, speler: viewPlayer, live: viewLive, vergelijken: viewMarket, scouting: viewScouting, nieuws: viewNews }[r.name] || viewHome;
  const out = fn(r.args);
  if (out instanceof Promise) { view.innerHTML = errs + `<div class="loading">Laden…</div>`; out.then(h => { view.innerHTML = errs + h; bind(view); }); }
  else { view.innerHTML = errs + out; bind(view); }
}
function bind(root) {
  $$("[data-go]", root).forEach(el => el.addEventListener("click", e => { if (e.target.closest("a")) return; location.hash = el.dataset.go; }));
  (S.ui.after || []).forEach(f => f(root)); S.ui.after = [];
}
const after = f => (S.ui.after = S.ui.after || []).push(f);
const analyticsNote = () => S.state.analytics.ready ? "" : `<div class="note" style="margin-bottom:14px">Advanced analytics (nflverse) worden nog geladen; attributen en scheme-matchups verschijnen zo.</div>`;

/* ================= OVERZICHT ================= */
function matchupHeader() {
  const m = S.state.meta, L = S.live;
  const me = L && L.me, op = L && L.opp;
  const anyStarted = L && [...(me ? me.rows : []), ...(op ? op.rows : [])].some(r => r.game && r.game.state !== "pre");
  const t = m.team || {}, o = m.opponent;
  const wp = L && num(L.winProb) ? L.winProb : null;
  return `<div class="panel" id="muHeader">
    <div class="mu">
      <div class="side"><div class="tn">${esc(t.name || "Mijn team")}</div><div class="rec">${t.wins ?? 0}-${t.losses ?? 0}${t.ties ? "-" + t.ties : ""}</div>
        <div class="score">${anyStarted ? f1(me.total) : f1(myProjTotal())}</div><div class="proj">${anyStarted ? "verwacht " + f1(me.projFinal) : "projectie"}</div></div>
      <div class="vs">${L && L.anyLive ? '<span class="livepill">Live</span>' : "VS"}</div>
      <div class="side r"><div class="tn">${esc(o ? o.name : "Geen tegenstander")}</div><div class="rec">${o ? `${o.wins ?? 0}-${o.losses ?? 0}` : ""}</div>
        <div class="score">${op ? (anyStarted ? f1(op.total) : f1(op.projFinal)) : "–"}</div><div class="proj">${op ? (anyStarted ? "verwacht " + f1(op.projFinal) : "projectie") : ""}</div></div>
    </div>
    ${wp != null ? `<div class="wp"><div class="wp-bar" role="img" aria-label="Winkans ${Math.round(wp * 100)}%"><i style="width:${wp * 100}%;background:var(--series-1)"></i><i style="flex:1;background:var(--series-2)"></i></div>
      <div class="wp-l"><span><span class="sw" style="background:var(--series-1)"></span> Winkans ${Math.round(wp * 100)}%</span><span>${Math.round((1 - wp) * 100)}% <span class="sw" style="background:var(--series-2)"></span></span></div></div>` : ""}
  </div>`;
}
function myProjTotal() { return myRoster().filter(isStarter).reduce((s, p) => s + (p.bye ? 0 : p.proj || 0), 0); }

function inboxItems() {
  const items = [];
  const ro = myRoster(), starters = ro.filter(isStarter), bench = ro.filter(p => p.slot === "Bank");
  starters.forEach(p => {
    const i = INJ[p.injury];
    if (p.bye) items.push({ pri: 5, ic: "⏸", subj: `${p.name} heeft een bye`, body: `Hij staat in je basisopstelling (${p.slot}) maar speelt niet deze week.`, go: `#/speler/${p.id}` });
    else if (i && i[3] >= 3) items.push({ pri: 5, ic: "✚", subj: `${p.name}: ${i[0]}`, body: `Starter op ${p.slot}. Overweeg een vervanger.`, go: `#/speler/${p.id}` });
    else if (i) items.push({ pri: 3, ic: "✚", subj: `${p.name}: ${i[0]}`, body: `Houd het nieuws in de gaten voor de aftrap (${kickoff(p)}).`, go: `#/speler/${p.id}` });
  });
  const elig = (slot, q) => slot === "FLEX" ? ["RB", "WR", "TE"].includes(q.pos) : q.pos === slot;
  starters.forEach(p => {
    const best = bench.filter(q => elig(p.slot, q) && !q.bye && !(INJ[q.injury] && INJ[q.injury][3] >= 3)).sort((a, b) => (b.proj || 0) - (a.proj || 0))[0];
    const pp = p.bye || (INJ[p.injury] && INJ[p.injury][3] >= 3) ? 0 : (p.proj || 0);
    if (best && (best.proj || 0) - pp >= 2) items.push({ pri: 4, ic: "⇄", subj: `Opstelling: ${best.name} i.p.v. ${p.name}?`, body: `${best.name} staat op ${f1(best.proj)} ptn geprojecteerd, ${p.name} op ${f1(pp)} (${p.slot}).`, go: `#/speler/${best.id}` });
  });
  ["QB", "RB", "WR", "TE"].forEach(pos => {
    // waivers op basis van projectie rest-seizoen (niet alleen deze week)
    const mine = ro.filter(p => p.pos === pos).sort((a, b) => (a.ros || 0) - (b.ros || 0));
    if (!mine.length) return;
    const worst = mine[0];
    const fa = Object.values(S.state.players).filter(p => p.pos === pos && isFree(p)).sort((a, b) => (b.ros || 0) - (a.ros || 0))[0];
    if (fa && (fa.ros || 0) - (worst.ros || 0) >= 8)
      items.push({ pri: 2, ic: "＋", subj: `Waiver-tip: ${fa.name} (${pos}, ${fa.team})`, body: `Projectie rest seizoen ${f1(fa.ros)} vs ${f1(worst.ros)} voor ${worst.name}; deze week ${fa.bye ? "bye" : f1(fa.proj)}. ${f1(fa.owned)}% eigendom${num(fa.ownedChange) && fa.ownedChange > 0 ? `, +${f1(fa.ownedChange)}% deze week` : ""}.`, go: `#/speler/${fa.id}` });
  });
  starters.forEach(p => {
    const e = p.adv && p.adv.edge; if (!e) return;
    if (e.score >= 75) items.push({ pri: 1, ic: "▲", subj: `Gunstige matchup: ${p.name} vs ${p.opp} (${e.grade})`, body: e.top, go: `#/speler/${p.id}` });
    if (e.score <= 25) items.push({ pri: 1, ic: "▼", subj: `Lastige matchup: ${p.name} vs ${p.opp} (${e.grade})`, body: e.top, go: `#/speler/${p.id}` });
  });
  const ids = new Set(S.state.roster);
  ((S.news && S.news.mine) || []).slice(0, 6).forEach(n => {
    const pid = (n.player_ids || []).find(i => ids.has(i));
    const p = pid && P(pid);
    items.push({ pri: 0, ic: "✉", subj: n.headline, body: `${p ? p.name + " · " : ""}${n.source}${n.kind ? " " + n.kind.toLowerCase() : ""}`, when: n.published, go: p ? `#/speler/${p.id}` : "#/nieuws" });
  });
  return items.sort((a, b) => b.pri - a.pri);
}
function lineupRows(rows) {
  const L = S.live, lr = {};
  ((L && L.me && L.me.rows) || []).forEach(r => lr[r.id] = r);
  let group = null, h = "";
  rows.forEach(p => {
    const g = isStarter(p) ? "Basis" : "Bank";
    if (g !== group) { group = g; h += `<tr class="grp"><td colspan="7">${g === "Basis" ? "Basisopstelling" : "Bank"}</td></tr>`; }
    const l = lr[p.id];
    const started = l && l.game && l.game.state !== "pre";
    h += `<tr class="click" data-go="#/speler/${p.id}" data-live="${p.id}">
      <td><span class="slot">${esc(p.slot)}</span></td>
      <td><div class="pn">${esc(p.name)} ${inj(p)}</div><div class="pm">${esc(p.pos)} · ${esc(p.team)}</div></td>
      <td>${oppStr(p)}</td>
      <td class="c">${grade(p.adv && p.adv.edge)}</td>
      <td class="n big" data-live-pts>${started ? f1(l.pts) : p.bye ? "–" : f1(p.proj)}</td>
      <td class="pm" data-live-line>${started ? esc(l.line || (l.game ? l.game.detail : "")) : (p.bye ? "bye" : kickoff(p))}</td>
      <td>${form(p, 4)}</td></tr>`;
  });
  return h;
}
const SLOT_ORDER = { QB: 0, RB: 1, WR: 2, TE: 3, FLEX: 4, "D/ST": 5, K: 6, Bank: 7, IR: 8 };
const bySlot = (a, b) => (SLOT_ORDER[a.slot] ?? 9) - (SLOT_ORDER[b.slot] ?? 9) || (b.proj || 0) - (a.proj || 0);

function viewHome() {
  const ro = myRoster().sort(bySlot);
  const starters = ro.filter(isStarter);
  const inbox = inboxItems();
  const edges = starters.filter(p => p.adv && p.adv.edge).sort((a, b) => b.adv.edge.score - a.adv.edge.score);
  const injured = ro.filter(p => INJ[p.injury]);
  const kpi = (l, v, n) => `<div class="kpi"><div class="l">${esc(l)}</div><div class="v">${v}</div><div class="n" title="${esc(n)}">${esc(n)}</div></div>`;
  const avgOverall = starters.map(p => p.adv && p.adv.overall).filter(num);
  return `${analyticsNote()}
  <div class="stack">
    <div id="muSlot">${matchupHeader()}</div>
    <div class="kpis">
      ${kpi("Projectie basisopstelling", f1(myProjTotal()), `${starters.length} starters`)}
      ${kpi("Gem. kwaliteit starters", avgOverall.length ? f1(avgOverall.reduce((a, b) => a + b, 0) / avgOverall.length) : "–", "attribuut-gemiddelde, schaal 1-20")}
      ${kpi("Beste matchup", edges[0] ? edges[0].adv.edge.grade : "–", edges[0] ? `${edges[0].name} vs ${edges[0].opp}` : "")}
      ${kpi("Blessuremeldingen", injured.length, injured.map(p => short(p.name)).join(", ") || "Iedereen fit")}
    </div>
    <div class="grid g-side">
      <div class="panel"><div class="panel-h"><h2>Inbox</h2><span class="sub">${inbox.length} berichten</span></div>
        <ul class="inbox">${inbox.slice(0, 14).map(it => `<li data-go="${esc(it.go)}"><div class="ic">${it.ic}</div><div><div class="subj">${esc(it.subj)}</div>${it.body ? `<div class="body">${esc(it.body)}</div>` : ""}</div><div class="when">${it.when ? ago(it.when) : ""}</div></li>`).join("") || `<li><div></div><div class="muted">Geen meldingen.</div></li>`}</ul>
      </div>
      <div class="panel"><div class="panel-h"><h2>Opstelling week ${W()}</h2><a href="#/live" class="small">Wedstrijdcentrum →</a></div>
        <div class="scroll"><table class="t compact"><tbody id="homeLineup">${lineupRows(ro)}</tbody></table></div>
      </div>
    </div>
    <div class="panel"><div class="panel-h"><h2>Scheme-matchups van je starters</h2><span class="sub">Spelerprofiel × tendensen van de tegenstander (nflverse t/m week ${S.state.analytics.maxWeek ?? "–"})</span></div>
      <div class="panel-b">${edges.length ? edges.map(p => `<div class="factor" data-go="#/speler/${p.id}" style="cursor:pointer"><div><div class="fl">${esc(p.name)}</div><div class="pm">${esc(p.pos)} ${oppStr(p)}</div></div><div>${grade(p.adv.edge, true)}</div><div class="ft">${esc(p.adv.edge.top || "")}</div></div>`).join("") : `<div class="muted">Nog geen matchup-data.</div>`}</div>
    </div>
  </div>`;
}
function renderLiveParts() {
  const r = route().name;
  if (r === "overzicht") {
    const slot = $("#muSlot"); if (slot) slot.innerHTML = matchupHeader();
    const lu = $("#homeLineup"); if (lu) { lu.innerHTML = lineupRows(myRoster().sort(bySlot)); bind(lu); }
  } else if (r === "live") { $("#view").innerHTML = viewLive(); bind($("#view")); }
}

/* ================= SELECTIE ================= */
function viewSquad() {
  const mode = S.ui.squadMode || "overzicht";
  const ro = myRoster().sort(bySlot);
  let head, row;
  if (mode === "overzicht") {
    head = `<th>Slot</th><th>Speler</th><th class="c" data-tip="Gemiddelde van de attributen (1-20)">Kwal.</th><th>Vorm</th><th>Wedstrijd</th><th class="c">Matchup</th><th class="n">Proj.</th><th class="n">Gem.</th><th class="n">L3</th><th class="n">Snap%</th><th>Gebruik</th><th>Seizoen</th><th class="n">Rang</th>`;
    row = p => `<td><span class="slot">${esc(p.slot)}</span></td>
      <td><div class="pn">${esc(p.name)} ${inj(p)}</div><div class="pm">${esc(p.pos)} · ${esc(p.team)}</div></td>
      <td class="c">${attr(p.adv && p.adv.overall)}</td><td>${form(p)}</td>
      <td>${oppStr(p)} ${fpChip(p)}<div class="pm">${p.bye ? "" : kickoff(p)}</div></td>
      <td class="c">${grade(p.adv && p.adv.edge)}</td>
      <td class="n big">${p.bye ? "–" : f1(p.proj)}</td><td class="n">${f1(p.avg)}</td><td class="n">${f1(p.last3)}</td>
      <td class="n">${p.adv ? pc(p.adv.snap3) : "–"}</td><td class="small">${usage(p)}</td><td>${spark(p)}</td>
      <td class="n"><span data-tip="Rang op seizoenspunten / op projectie deze week">${p.pos}${p.rankTotal ?? "–"} <span class="muted">/ ${p.rankProj ?? "–"}</span></span></td>`;
  } else if (mode === "attributen") {
    head = `<th>Slot</th><th>Speler</th><th class="c">Kwal.</th><th colspan="12">Attributen (1-20, percentiel binnen positie)</th>`;
    row = p => `<td><span class="slot">${esc(p.slot)}</span></td><td><div class="pn">${esc(p.name)}</div><div class="pm">${esc(p.pos)}</div></td>
      <td class="c">${attr(p.adv && p.adv.overall)}</td>
      ${p.adv ? p.adv.attrs.map(a => `<td class="c"><div class="pm" style="font-size:9.5px">${esc(a.n)}</div>${attr(a.s)}</td>`).join("") : `<td class="muted" colspan="12">Geen nflverse-profiel (K/D-ST of te weinig snaps)</td>`}`;
  } else {
    head = `<th>Slot</th><th>Speler</th><th class="n">Snap%</th><th class="n">Tgt%</th><th class="n">WOPR</th><th class="n">aDOT</th><th class="n">EPA/tgt</th><th class="n">Car%</th><th class="n">EPA/car</th><th class="n">RYOE</th><th class="n">GL%</th><th class="n">EPA/db</th><th class="n">CPOE</th><th class="n">PPR/g</th>`;
    row = p => { const a = p.adv || {}; return `<td><span class="slot">${esc(p.slot)}</span></td><td><div class="pn">${esc(p.name)}</div><div class="pm">${esc(p.pos)} · ${esc(p.team)}</div></td>
      <td class="n">${pc(a.snap)}</td><td class="n">${pc(a.tshare, 1)}</td><td class="n">${f2(a.wopr)}</td><td class="n">${f1(a.adot)}</td><td class="n">${sg(a.epa_tgt)}</td>
      <td class="n">${pc(a.rush_share, 1)}</td><td class="n">${sg(a.epa_rush)}</td><td class="n">${sg(a.ryoe)}</td><td class="n">${pc(a.gl_share)}</td>
      <td class="n">${sg(a.epa_db)}</td><td class="n">${sg(a.cpoe, 1)}</td><td class="n">${f1(a.ppr_pg)}</td>`; };
  }
  after(root => $$("[data-mode]", root).forEach(b => b.onclick = () => { S.ui.squadMode = b.dataset.mode; render(); }));
  let group = null;
  const body = ro.map(p => {
    const g = isStarter(p) ? "Basisopstelling" : "Bank en IR";
    const gh = g !== group ? `<tr class="grp"><td colspan="15">${g}</td></tr>` : ""; group = g;
    return gh + `<tr class="click" data-go="#/speler/${p.id}">${row(p)}</tr>`;
  }).join("");
  return `${analyticsNote()}<div class="panel">
    <div class="panel-h"><h2>Selectie</h2>
      <div class="seg">${[["overzicht", "Overzicht"], ["attributen", "Attributen"], ["gebruik", "Gebruik & efficiëntie"]].map(([k, l]) => `<button data-mode="${k}" aria-pressed="${mode === k}">${l}</button>`).join("")}</div>
      <div class="legend"><span>Vorm: punten t.o.v. projectie</span><span><i class="sw" style="background:var(--div-pos)"></i>≥ +3</span><span><i class="sw" style="background:var(--neutral-mark)"></i>±3</span><span><i class="sw" style="background:var(--div-neg)"></i>≤ −3</span></div>
    </div>
    <div class="scroll"><table class="t"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
  </div>
  <footer class="foot">Attributen zijn percentielen binnen de positie (min. volume), op basis van nflverse play-by-play, FTN-charting en Next Gen Stats. Matchup = scheme-model (spelerprofiel × tendensen van de defense); hover voor de belangrijkste factor.</footer>`;
}

/* ================= SPELER ================= */
async function viewPlayer(args) {
  const id = +args[0];
  const tab = args[1] || "profiel";
  let d = S.cache.player[id];
  if (!d || Date.now() - d._t > 60000) {
    try { d = await api("/api/player/" + id); d._t = Date.now(); S.cache.player[id] = d; }
    catch (e) { return `<div class="empty">Speler niet gevonden (${esc(e.message)}).</div>`; }
  }
  const p = d.espn, pr = d.profile, sp = P(id) || p;
  const ovr = pr && pr.overall;
  const role = pr ? (pr.rec && ["WR", "TE"].includes(p.pos) ? `${pc(pr.rec.tshare)} targetshare · ${f1(pr.rec.adot)} aDOT` :
    p.pos === "RB" && pr.rush ? `${pc(pr.rush.rush_share)} van de carries · ${pr.rec ? pc(pr.rec.tshare) + " targets" : ""}` :
      p.pos === "QB" && pr.pass ? `${sg(pr.pass.epa_db)} EPA/dropback · CPOE ${sg(pr.pass.cpoe, 1)}` : "") : "";
  const tabs = [["profiel", "Profiel"], ["splits", "Splits"], ["matchup", "Matchup"], ["log", "Wedstrijdlog"], ["nieuws", `Nieuws (${d.news.length})`], ["vergelijk", "Vergelijk"]];
  const header = `<div class="panel"><div class="ph">
      ${pr && pr.headshot ? `<img src="${esc(pr.headshot)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'noimg'}))">` : `<div class="noimg"></div>`}
      <div><h2>${esc(p.name)}</h2>
        <div class="meta"><span class="slot">${esc(sp.slot || p.pos)}</span><span>${esc(p.pos)} · ${esc(p.team)}</span>${inj(p)}<span>${ownerLabel(sp)}</span><span class="muted">${f1(p.owned)}% eigendom</span></div>
        <div class="meta" style="margin-top:6px"><span>Week ${W()}: ${oppStr(p)} ${fpChip(sp)}</span><span>Projectie <strong>${p.bye ? "–" : f1(p.proj)}</strong></span><span>${role}</span>${pr && pr.low_sample ? `<span class="chip mid" data-tip="Weinig volume: attributen minder betrouwbaar">klein sample</span>` : ""}</div>
      </div>
      <div class="ovr">${attr(ovr, true)}<div class="lab">Kwaliteit</div>${d.matchup ? `<div style="margin-top:8px">${grade({ score: d.matchup.score, grade: d.matchup.grade, top: d.matchup.factors[0] && d.matchup.factors[0].text }, false)}</div><div class="lab">Matchup ${d.matchup.score}</div>` : ""}</div>
    </div></div>`;
  const tabbar = `<div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button class="tab" role="tab" aria-selected="${tab === k}" onclick="location.hash='#/speler/${id}/${k}'">${l}</button>`).join("")}</div>`;
  const body = { profiel: plProfile, splits: plSplits, matchup: plMatchup, log: plLog, nieuws: plNews, vergelijk: plCompare }[tab](d);
  return `<div class="stack">${header}<div>${tabbar}${body}</div></div>`;
}
function plProfile(d) {
  const p = d.espn, pr = d.profile;
  const meta = (S.state.analytics.attrMeta || {})[p.pos] || [];
  const attrs = pr && pr.attrs ? `<div class="attrs">${pr.attrs.map((a, i) => `<div class="row" data-tip="${esc((meta[i] || {}).desc || "")}${num(a.raw) ? " · waarde: " + a.raw : ""}"><span>${esc(a.name)}</span>${attr(a.score)}</div>`).join("")}</div>` : `<div class="muted">Geen attributen voor deze positie of te weinig data.</div>`;
  const st = [];
  const add = (l, v, c) => st.push(`<div class="stat"><div class="l">${l}</div><div class="v">${v}</div>${c ? `<div class="c">${c}</div>` : ""}</div>`);
  add("Fantasy totaal", f1(p.total), `${p.games} wedstr. · gem. ${f1(p.avg)}`);
  add("Laatste 3", f1(p.last3), `rang ${p.pos}${p.rankTotal ?? "–"}`);
  add("Proj. rest seizoen", f1(p.ros));
  if (pr) {
    add("Snaps", pc(pr.snap_pct), `laatste 3: ${pc(pr.snap_last3)}`);
    const r = pr.rec, u = pr.rush, q = pr.pass;
    if (q) { add("EPA/dropback", sg(q.epa_db), `CPOE ${sg(q.cpoe, 1)}`); add("Yards / TD / INT", `${f0(q.yds)}`, `${q.td} TD · ${q.int} INT`); add("aDOT", f1(q.adot), `diep ${pc(q.deep_rate)}`); add("Sack% / druk%", pc(q.sack_rate, 1), `druk ${pc(q.pressure_rate)}`); if (q.ttt) add("Time to throw", f2(q.ttt) + "s", "NGS"); }
    if (r && p.pos !== "QB") { add("Targets", r.targets, `${pc(r.tshare, 1)} share · WOPR ${f2(r.wopr)}`); add("Rec / yds / TD", `${r.rec} / ${f0(r.yds)}`, `${r.td} TD`); add("aDOT", f1(r.adot), `diep ${pc(r.deep_share)}`); add("EPA/target", sg(r.epa_tgt), `succes ${pc(r.succ)}`); add("YAC boven verw.", sg(r.yacoe, 1), `YAC/rec ${f1(r.yac_pr)}`); if (r.separation) add("Separatie", f2(r.separation) + " yd", `cushion ${f1(r.cushion)}`); add("Red zone", `${r.rz_tgt} tgt`, `${r.ez_tgt} end zone · ${pc(r.rz_share)} share`); add("Vangbaar / drops", pc(r.catchable_rate), `${r.drops} drops · ${pc(r.contested_rate)} contested`); }
    if (u && (p.pos === "RB" || (u.carries || 0) > 20)) { add("Carries", u.carries, `${pc(u.rush_share, 1)} share`); add("Yds / YPC", `${f0(u.yds)}`, `${f1(u.ypc)} per carry · ${u.td} TD`); add("EPA/carry", sg(u.epa_rush), `succes ${pc(u.succ)}`); if (u.ryoe_att != null) add("RYOE/att", sg(u.ryoe_att), `${f1(u.pct_8box)}% vs 8+ box`); add("Goal line", `${u.gl_att} car`, `${pc(u.gl_share)} share binnen de 5`); add("Explosief", pc(u.expl_rate), "carries 10+ yards"); }
  }
  return `<div class="grid g-side-r">
    <div class="panel"><div class="panel-h"><h2>Attributen</h2><span class="sub">1-20 · percentiel binnen ${esc(p.pos)}</span></div><div class="panel-b">${attrs}</div></div>
    <div class="stack">
      <div class="panel"><div class="panel-h"><h2>Punten per week</h2>
        <div class="legend"><span><i class="sw" style="background:var(--series-1)"></i>Gescoord (league)</span><span><svg width="16" height="8"><line x1="0" x2="16" y1="4" y2="4" stroke="var(--text-primary)" stroke-width="2"/></svg>ESPN-projectie</span>${pr ? "<span>cijfer in balk = snap%</span>" : ""}</div></div>
        <div class="panel-b">${weeklyChart(p, pr && pr.snaps_wk)}</div></div>
      <div class="panel"><div class="panel-h"><h2>Seizoensstatistieken</h2></div><div class="panel-b"><div class="statgrid">${st.join("")}</div></div></div>
    </div></div>`;
}
function splitTable(title, sub, rows, cols) {
  return `<div class="panel"><div class="panel-h"><h2>${title}</h2><span class="sub">${sub}</span></div><div class="scroll"><table class="t compact">
    <thead><tr>${cols.map(c => `<th class="${c.n ? "n" : ""}">${c.l}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr>${cols.map(c => `<td class="${c.n ? "n" : ""}">${c.f(r)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`;
}
const DEPTH_L = { achter: "Achter LOS", kort: "Kort (0-9)", middel: "Middel (10-19)", diep: "Diep (20+)" };
const LOC_L = { left: "Links", middle: "Midden", right: "Rechts" };
const BOX_L = { licht: "Licht (≤6)", normaal: "Normaal (7)", stacked: "Stacked (8+)" };
function plSplits(d) {
  const pr = d.profile, L = S.state.analytics.league;
  if (!pr || !L) return `<div class="empty">Geen nflverse-splits voor deze speler.</div>`;
  const out = [];
  const legend = `<span class="legend"><span><i class="sw" style="background:var(--series-1)"></i>speler</span><span><i class="sw" style="background:var(--neutral-mark)"></i>league</span></span>`;
  const r = pr.rec;
  if (r && d.espn.pos !== "QB") {
    out.push(splitTable("Targetdiepte", legend, ["achter", "kort", "middel", "diep"].map(b => ({ b, p: r.depth[b], l: L.depth[b] })), [
      { l: "Diepte", f: x => DEPTH_L[x.b] }, { l: "Targets", n: 1, f: x => x.p.n },
      { l: "Aandeel", n: 1, f: x => pc(x.p.share) }, { l: "Speler vs league (aandeel)", f: x => pairBar(x.p.share, x.l.share, .7) },
      { l: "EPA/tgt", n: 1, f: x => sg(x.p.epa) }, { l: "League", n: 1, f: x => `<span class="muted">${sg(x.l.epa)}</span>` }, { l: "Yds/tgt", n: 1, f: x => f1(x.p.ypt) }]));
    out.push(splitTable("Richting", legend, ["left", "middle", "right"].map(b => ({ b, p: r.loc[b], l: L.loc[b] })), [
      { l: "Kant", f: x => LOC_L[x.b] }, { l: "Targets", n: 1, f: x => x.p.n }, { l: "Aandeel", n: 1, f: x => pc(x.p.share) },
      { l: "Speler vs league", f: x => pairBar(x.p.share, x.l.share, .7) }, { l: "EPA/tgt", n: 1, f: x => sg(x.p.epa) }, { l: "League", n: 1, f: x => `<span class="muted">${sg(x.l.epa)}</span>` }]));
    const sp = r.splits;
    const rows = [["Blitz (≥1 blitzer)", sp.blitz.ja], ["Geen blitz", sp.blitz.nee], ["Play-action", sp.pa.ja], ["Geen play-action", sp.pa.nee], ["Pre-snap motion", sp.motion.ja], ["Geen motion", sp.motion.nee]];
    out.push(splitTable("Situaties (FTN-charting)", "targetshare = aandeel van de team-targets in die situatie", rows.map(([n, v]) => ({ n, v })), [
      { l: "Situatie", f: x => x.n }, { l: "Targets", n: 1, f: x => x.v.n }, { l: "Targetshare", n: 1, f: x => pc(x.v.tshare, 1) },
      { l: "EPA/tgt", n: 1, f: x => sg(x.v.epa) }, { l: "Yds/tgt", n: 1, f: x => f1(x.v.ypt) }, { l: "Catch%", n: 1, f: x => pc(x.v.catch) }]));
  }
  const u = pr.rush;
  if (u && d.espn.pos === "RB") {
    out.push(splitTable("Boxcount (FTN-charting)", legend, ["licht", "normaal", "stacked"].map(b => ({ b, p: u.box[b], l: L.box[b] })), [
      { l: "Box", f: x => BOX_L[x.b] }, { l: "Carries", n: 1, f: x => x.p.n }, { l: "Frequentie", n: 1, f: x => pc(x.p.freq) },
      { l: "Speler vs league", f: x => pairBar(x.p.freq, x.l.freq, .8) }, { l: "YPC", n: 1, f: x => f1(x.p.ypc) }, { l: "League YPC", n: 1, f: x => `<span class="muted">${f1(x.l.ypc)}</span>` },
      { l: "EPA/car", n: 1, f: x => sg(x.p.epa) }, { l: "League", n: 1, f: x => `<span class="muted">${sg(x.l.epa)}</span>` }]));
  }
  const q = pr.pass;
  if (q) {
    const sp = q.splits;
    const rows = [["Blitz", sp.blitz.ja, L.epa_blitz], ["Geen blitz", sp.blitz.nee, L.epa_noblitz], ["Play-action", sp.pa.ja, L.epa_pa], ["Geen play-action", sp.pa.nee, L.epa_nopa], ["Onder druk (hit/sack)", sp.druk.ja, null], ["Schone pocket", sp.druk.nee, null], ["Buiten de pocket", sp.buiten_pocket.ja, null]];
    out.push(splitTable("Situaties (FTN-charting)", "per dropback", rows.map(([n, v, l]) => ({ n, v, l })), [
      { l: "Situatie", f: x => x.n }, { l: "Dropbacks", n: 1, f: x => x.v.n }, { l: "EPA/db", n: 1, f: x => sg(x.v.epa) },
      { l: "League", n: 1, f: x => `<span class="muted">${sg(x.l)}</span>` }, { l: "Cmp%", n: 1, f: x => pc(x.v.cmp) }, { l: "Yds/poging", n: 1, f: x => f1(x.v.ypa) }, { l: "Sack%", n: 1, f: x => pc(x.v.sack, 1) }]));
    out.push(splitTable("Passdiepte", legend, ["achter", "kort", "middel", "diep"].map(b => ({ b, p: q.depth[b], l: L.depth[b] })), [
      { l: "Diepte", f: x => DEPTH_L[x.b] }, { l: "Pogingen", n: 1, f: x => x.p.n }, { l: "Aandeel", n: 1, f: x => pc(x.p.share) },
      { l: "Speler vs league", f: x => pairBar(x.p.share, x.l.share, .7) }, { l: "EPA", n: 1, f: x => sg(x.p.epa) }, { l: "League", n: 1, f: x => `<span class="muted">${sg(x.l.epa)}</span>` }]));
  }
  return `<div class="grid g2">${out.join("") || `<div class="empty">Geen splits beschikbaar.</div>`}</div>
  <footer class="foot">Gratis FTN-charting bevat geen man/zone-coverage. Blitz, play-action, motion en boxcount zijn de beschikbare scheme-signalen. EPA = expected points added per play; league = gemiddelde van alle plays.</footer>`;
}
function defSummary(D, L, nT) {
  if (!D) return "";
  const cell = (m, v, f, lowGood) => { const rk = D.rank && D.rank[m]; const cls = rk ? (rk <= nT / 3 ? "neg" : rk > nT * 2 / 3 ? "pos" : "") : ""; return `<span class="def-cell ${cls}" data-tip="${rk ? `Rang ${rk}/${nT} (1 = lastigst voor de aanval)` : ""}">${f(v)}</span>`; };
  const rows = [
    ["EPA/dropback toegestaan", cell("epa_pass", D.epa_pass, sg), sg(L.epa_pass)],
    ["EPA/carry toegestaan", cell("epa_rush", D.epa_rush, sg), sg(L.epa_rush)],
    ["Yards per carry", cell("ypc", D.ypc, f1), f1(L.ypc)],
    ["Blitz-percentage", cell("blitz_rate", D.blitz_rate, v => pc(v)), pc(L.blitz_rate)],
    ["Druk (hit/sack)", cell("pressure_rate", D.pressure_rate, v => pc(v)), pc(L.pressure_rate)],
    ["Gem. pass rushers", f1(D.rushers), f1(L.rushers)],
    ["Gem. box (runs)", f1(D.box_avg), f1(L.box_avg)],
    ["Stacked box (8+)", pc(D.box.stacked.freq), pc(L.box.stacked.freq)],
    ["Diep EPA/target", cell("epa_diep", D.depth.diep.epa, sg), sg(L.depth.diep.epa)],
    ["Explosieve passes", cell("expl_pass", D.expl_pass, v => pc(v, 1)), pc(L.expl_pass, 1)],
  ];
  return `<table class="t compact"><thead><tr><th>${esc(D.team)} defense</th><th class="n">Waarde</th><th class="n">League</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r[0]}</td><td class="n">${r[1]}</td><td class="n muted">${r[2]}</td></tr>`).join("")}</tbody></table>`;
}
function defendersTable(D) {
  if (!D || !D.defenders || !D.defenders.length) return `<div class="empty">Geen coverage-data per verdediger.</div>`;
  return `<table class="t compact"><thead><tr><th>Verdediger</th><th>Pos</th><th class="n">Tgt</th><th class="n">Tgt/g</th><th class="n">Cmp%</th><th class="n">Yds/tgt</th><th class="n">TD</th><th class="n">INT</th><th class="n" data-tip="Passer rating toegestaan">Rating</th><th class="n">Missed tkl</th></tr></thead><tbody>
    ${D.defenders.map(x => `<tr><td class="pn">${esc(x.name)}</td><td>${esc(x.pos)}</td><td class="n">${x.targets}</td><td class="n">${f1(x.tgt_pg)}</td><td class="n">${pc(x.cmp_pct)}</td><td class="n">${f1(x.ypt)}</td><td class="n">${x.td}</td><td class="n">${x.int}</td><td class="n">${f1(x.rating)}</td><td class="n">${pc(x.missed_tkl_pct)}</td></tr>`).join("")}</tbody></table>`;
}
function plMatchup(d) {
  const p = d.espn, m = d.matchup, D = d.defense, L = S.state.analytics.league, nT = S.state.analytics.nTeams || 32;
  if (p.bye) return `<div class="empty">Bye-week: geen wedstrijd deze week.</div>`;
  const maxAbs = m ? Math.max(.05, ...m.factors.map(f => Math.abs(f.value))) : 1;
  const outlook = p.outlook ? `<p class="outlook">${esc(p.outlook)}</p>${p.outlookWeek !== W() ? `<div class="muted small">ESPN-outlook van week ${p.outlookWeek}; die van week ${W()} is nog niet gepubliceerd.</div>` : ""}` : `<div class="muted">Nog geen ESPN-outlook.</div>`;
  const ps = p.projStats || {};
  const proj = (S.state.keyStats[p.pos] || []).filter(k => ps[k[0]] != null).map(k => `${k[1]}: <strong>${f1(ps[k[0]])}</strong>`).join(" · ");
  return `<div class="grid g2">
    <div class="stack">
      <div class="panel"><div class="panel-h"><h2>Scheme-matchup vs ${esc(p.opp || "")}</h2><span class="sub">${p.home ? "thuis" : "uit"} · ${kickoff(p)}</span></div>
        <div class="panel-b">${m ? `<div class="gauge"><div class="num">${m.score}</div>${grade({ score: m.score, grade: m.grade }, false)}<div class="muted small">0-100 · 50 = neutraal<br>som van de factoren: ${sg(m.total, 3)} EPA/play</div></div>
          <div style="margin-top:10px">${m.factors.map(f => `<div class="factor"><div class="fl">${esc(f.label)}</div><div data-tip="${sg(f.value, 3)} EPA/play">${divBar(f.value, maxAbs)}</div><div class="ft">${esc(f.text)}</div></div>`).join("")}</div>
          <div class="legend" style="margin-top:8px"><span><i class="sw" style="background:var(--div-pos)"></i>in zijn voordeel</span><span><i class="sw" style="background:var(--div-neg)"></i>in zijn nadeel</span></div>` : `<div class="muted">Geen scheme-model voor deze positie (K/D-ST) of te weinig data.</div>`}</div></div>
      <div class="panel"><div class="panel-h"><h2>ESPN-outlook & projectie</h2></div><div class="panel-b">${proj ? `<p style="margin-top:0">${proj}</p>` : ""}${outlook}</div></div>
    </div>
    <div class="stack">
      <div class="panel"><div class="panel-h"><h2>Scouting: ${esc(p.opp || "")}</h2><a class="small" href="#/scouting/${esc(p.opp || "")}">Volledig rapport →</a></div><div class="scroll">${D ? defSummary(D, L, nT) : `<div class="empty">Laden…</div>`}</div></div>
      ${D && ["WR", "TE", "QB"].includes(p.pos) ? `<div class="panel"><div class="panel-h"><h2>Coverage per verdediger</h2><span class="sub">PFR advanced stats, dit seizoen</span></div><div class="scroll">${defendersTable(D)}</div></div>` : ""}
      ${D && D.fp_allowed ? `<div class="panel"><div class="panel-h"><h2>PPR-punten toegestaan per wedstrijd</h2></div><div class="panel-b"><div class="statgrid">${["QB", "RB", "WR", "TE"].map(q => `<div class="stat"><div class="l">${q}</div><div class="v">${f1(D.fp_allowed[q])}</div><div class="c">gem. ${f1(L.fp_allowed && L.fp_allowed[q])} · rang ${D.rank["fp_" + q] ?? "–"}/${nT}</div></div>`).join("")}</div></div></div>` : ""}
    </div></div>`;
}
function plLog(d) {
  const p = d.espn, pr = d.profile;
  const ppr = {}; ((pr && pr.weekly_ppr) || []).forEach(w => ppr[w.wk] = w.ppr);
  const snaps = (pr && pr.snaps_wk) || {};
  return `<div class="panel"><div class="scroll"><table class="t"><thead><tr><th>Week</th><th>Tegen</th><th class="n">Punten</th><th class="n">Projectie</th><th class="n">Verschil</th><th class="n">PPR (nflverse)</th><th class="n">Snap%</th></tr></thead><tbody>
    ${p.weekly.slice().reverse().map(w => { const dlt = w.pts != null && w.proj != null ? w.pts - w.proj : null; return `<tr><td>${w.wk}</td><td>${w.bye ? '<span class="chip mid">Bye</span>' : esc(w.opp || "–")}</td><td class="n big">${f1(w.pts)}</td><td class="n">${f1(w.proj)}</td><td class="n ${dlt > 0 ? "up" : dlt < 0 ? "down" : ""}">${sg(dlt, 1)}</td><td class="n">${f1(ppr[w.wk])}</td><td class="n">${snaps[w.wk] != null ? pc(snaps[w.wk]) : "–"}</td></tr>`; }).join("")}
  </tbody></table></div></div>`;
}
function newsList(items, showPlayers) {
  if (!items.length) return `<div class="empty">Geen nieuws gevonden.</div>`;
  return `<ul class="news">${items.map(n => {
    const ps = showPlayers ? (n.player_ids || []).map(P).filter(Boolean) : [];
    return `<li><div class="top"><span class="chip ${n.source === "Rotowire" ? "src-rw" : "src-espn"}">${esc(n.source)}${n.via ? " via " + esc(n.via) : ""}</span>${n.kind ? `<span>${esc(n.kind)}</span>` : ""}<span>${ago(n.published)}</span>${n.author ? `<span>${esc(n.author)}</span>` : ""}${ps.map(p => `<span class="ptag" data-go="#/speler/${p.id}">${esc(p.name)}</span>`).join("")}</div>
      <a class="hl" href="${esc(n.link || "#")}" target="_blank" rel="noopener">${esc(n.headline)}</a>${n.description && n.description !== n.headline ? `<div class="ds">${esc(n.description)}</div>` : ""}</li>`;
  }).join("")}</ul>`;
}
function plNews(d) { return `<div class="panel">${newsList(d.news, false)}</div>`; }
function plCompare(d) {
  const p = d.espn, pr = d.profile;
  const comps = d.competitors;
  const sel = S.ui.cmpWith && S.ui.cmpWith[p.id] || (comps.find(c => c.id !== p.id) || {}).id;
  const other = comps.find(c => c.id === sel);
  after(root => { const s = $("#cmpSel", root); if (s) s.onchange = () => { S.ui.cmpWith = S.ui.cmpWith || {}; S.ui.cmpWith[p.id] = +s.value; render(); }; });
  const mine = pr && pr.attrs ? pr.attrs : [];
  const theirs = other && other.adv ? other.adv.attrs : [];
  const attrRows = mine.map((a, i) => { const b = theirs[i] || {}; const dlt = num(a.score) && num(b.s) ? a.score - b.s : null; return `<tr><td>${esc(a.name)}</td><td class="c">${attr(a.score)}</td><td class="c">${attr(b.s)}</td><td class="n ${dlt > 0 ? "up" : dlt < 0 ? "down" : ""}">${dlt == null ? "–" : sg(dlt, 0)}</td></tr>`; }).join("");
  return `<div class="grid g2">
    <div class="panel"><div class="panel-h"><h2>Directe concurrenten op ${esc(p.pos)}</h2><span class="sub">gesorteerd op projectie week ${W()}</span></div><div class="scroll"><table class="t compact">
      <thead><tr><th class="n">#</th><th>Speler</th><th>Tegen</th><th class="c">Matchup</th><th class="n">Proj.</th><th class="n">Gem.</th><th class="n">L3</th><th class="c">Kwal.</th><th>Status</th></tr></thead><tbody>
      ${comps.map(c => { const cp = P(c.id) || c; return `<tr class="click ${c.id === p.id || cp.mine ? "mine" : ""}" data-go="#/speler/${c.id}"><td class="n muted">${c.rank}</td><td class="pn">${esc(c.name)} <span class="pm">${esc(c.team)}</span></td><td>${esc(c.opp || "–")}</td><td class="c">${grade(c.adv && c.adv.edge)}</td><td class="n big">${f1(c.proj)}</td><td class="n">${f1(c.avg)}</td><td class="n">${f1(c.last3)}</td><td class="c">${attr(c.adv && c.adv.overall)}</td><td>${P(c.id) ? ownerLabel(P(c.id)) : ""}</td></tr>`; }).join("")}
      </tbody></table></div></div>
    <div class="panel"><div class="panel-h"><h2>Attributen naast elkaar</h2>
      <select id="cmpSel" aria-label="Vergelijk met">${comps.filter(c => c.id !== p.id).map(c => `<option value="${c.id}" ${c.id === sel ? "selected" : ""}>${esc(c.name)} (${esc(c.team)})</option>`).join("")}</select></div>
      <div class="scroll">${mine.length ? `<table class="t compact"><thead><tr><th>Attribuut</th><th class="c">${esc(short(p.name))}</th><th class="c">${esc(other ? short(other.name) : "–")}</th><th class="n">Verschil</th></tr></thead><tbody>${attrRows}</tbody></table>` : `<div class="empty">Geen attributen voor deze positie.</div>`}</div></div>
  </div>`;
}

/* ================= WEDSTRIJDCENTRUM ================= */
function liveSide(side, title) {
  if (!side) return `<div class="panel"><div class="empty">Geen tegenstander deze week.</div></div>`;
  const rows = side.rows.slice().sort((a, b) => (SLOT_ORDER[a.slot] ?? 9) - (SLOT_ORDER[b.slot] ?? 9));
  let group = null;
  return `<div class="panel"><div class="panel-h"><h2>${esc(title)}</h2><span class="sub">${f1(side.total)} ptn · verwacht ${f1(side.projFinal)}</span></div><div class="scroll"><table class="t compact"><tbody>
    ${rows.map(r => {
      const g = BENCH.includes(r.slot) ? "Bank" : "Basis"; const gh = g !== group ? `<tr class="grp"><td colspan="5">${g === "Basis" ? "Basisopstelling" : "Bank"}</td></tr>` : ""; group = g;
      const gm = r.game; const state = gm ? gm.state : null;
      const localKick = gm && gm.date ? new Date(gm.date).toLocaleString("nl-NL", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "";
      const status = !gm ? (r.frac >= 1 ? "bye" : "–") : state === "pre" ? esc(localKick) : state === "in" ? `<span class="livepill">${esc(gm.detail || "live")}</span>${gm.redzone ? ' <span class="chip neg" data-tip="Team in de red zone"><span class="dot"></span>RZ</span>' : ""}` : esc(gm.detail || "");
      return gh + `<tr class="click" data-go="#/speler/${r.id}"><td><span class="slot">${esc(r.slot)}</span></td>
        <td><div class="pn">${esc(r.name)}</div><div class="pm">${esc(r.pos)} · ${esc(r.team)}${r.line ? " · " + esc(r.line) : ""}</div></td>
        <td class="small">${status}<div><span class="progress"><i style="width:${Math.round(r.frac * 100)}%"></i></span></div></td>
        <td class="n big">${f1(r.pts)}</td><td class="n muted" data-tip="Projectie / verwachte eindstand">${f1(r.proj)}<div class="small">→ ${f1(r.projFinal)}</div></td></tr>`;
    }).join("")}</tbody></table></div></div>`;
}
function viewLive() {
  const L = S.live;
  if (!L || !L.me) return `<div class="empty">Live-data laden…</div>`;
  const m = S.state.meta;
  const games = L.games || [];
  return `<div class="stack">${matchupHeader()}
    <div class="grid g2">${liveSide(L.me, (m.team || {}).name || "Mijn team")}${liveSide(L.opp, m.opponent ? m.opponent.name : "Tegenstander")}</div>
    <div class="grid g2">
      <div class="panel"><div class="panel-h"><h2>Live-ticker</h2><span class="sub">puntwijzigingen sinds de vorige verversing (elke 30 s tijdens wedstrijden)</span></div>
        ${L.events && L.events.length ? `<ul class="ticker">${L.events.map(e => `<li><span class="d ${e.delta > 0 ? "up" : "down"}">${sg(e.delta, 1)}</span><span><span class="pn">${esc(e.name)}</span> ${e.mine ? "" : '<span class="muted">(tegenstander)</span>'}<div class="pm">${esc(e.line || "")}</div></span><span class="muted small">${new Date(e.at).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" })}</span></li>`).join("")}</ul>` : `<div class="empty">Nog geen live-gebeurtenissen. Tijdens de wedstrijden verschijnen hier de puntwijzigingen van jouw spelers en die van je tegenstander.</div>`}</div>
      <div class="panel"><div class="panel-h"><h2>Wedstrijden met jouw spelers</h2><span class="sub">${games.length} wedstrijden</span></div>
        ${games.map(g => `<div class="gamecard"><div>${g.teams.map(t => `<div class="tm"><span class="sc">${esc(t.score ?? "")}</span><span class="${t.possession ? "pn" : ""}">${esc(t.abbrev)}${t.possession ? " ●" : ""}</span></div>`).join("")}</div>
          <div class="small" style="text-align:right">${g.state === "in" ? `<span class="livepill">${esc(g.detail)}</span>` : g.state === "pre" && g.date ? esc(new Date(g.date).toLocaleString("nl-NL", { weekday: "short", hour: "2-digit", minute: "2-digit" })) : esc(g.detail || "")}${g.downDistance ? `<div class="muted">${esc(g.downDistance)}</div>` : ""}${g.lastPlay ? `<div class="muted" style="max-width:240px;white-space:normal">${esc(g.lastPlay)}</div>` : ""}</div></div>`).join("") || `<div class="empty">Geen wedstrijden gevonden.</div>`}</div>
    </div>
    <footer class="foot">Verwachte eindstand = huidige punten + projectie × resterende speeltijd. Winkans: normale benadering met onzekerheid per speler die afneemt naarmate de wedstrijd vordert. Bijgewerkt ${L.updated ? new Date(L.updated).toLocaleTimeString("nl-NL") : "–"}.</footer></div>`;
}

/* ================= SPELERSMARKT ================= */
function viewMarket(args) {
  const pos = args[0] || S.ui.mktPos || "WR"; S.ui.mktPos = pos;
  const filt = S.ui.mktFilt || "all", q = (S.ui.mktQ || "").toLowerCase();
  const sortKey = S.ui.mktSort || "proj", asc = !!S.ui.mktAsc;
  const A = p => p.adv || {};
  const base = [
    { k: "rankProj", l: "#", n: 1, v: p => p.rankProj, f: p => `<span class="muted">${p.rankProj ?? "–"}</span>` },
    { k: "name", l: "Speler", v: p => p.name, f: p => `<div class="pn">${esc(p.name)} ${inj(p)}</div><div class="pm">${esc(p.team)}${p.mine ? " · " + esc(p.slot) : ""}</div>` },
    { k: "opp", l: "Wedstrijd", v: p => p.adv && p.adv.edge ? p.adv.edge.score : -1, f: p => `${oppStr(p)}` },
    { k: "edge", l: "Matchup", c: 1, v: p => p.adv && p.adv.edge ? p.adv.edge.score : null, f: p => grade(p.adv && p.adv.edge) },
    { k: "proj", l: `Proj.`, n: 1, v: p => p.bye ? null : p.proj, f: p => `<span class="big">${p.bye ? "–" : f1(p.proj)}</span>` },
    { k: "avg", l: "Gem.", n: 1, v: p => p.avg, f: p => f1(p.avg) },
    { k: "last3", l: "L3", n: 1, v: p => p.last3, f: p => f1(p.last3) },
    { k: "ros", l: "Proj. rest", n: 1, v: p => p.ros, f: p => f1(p.ros) },
    { k: "ovr", l: "Kwal.", c: 1, v: p => A(p).overall, f: p => attr(A(p).overall) },
    { k: "snap", l: "Snap%", n: 1, v: p => A(p).snap3, f: p => pc(A(p).snap3) },
  ];
  const posCols = {
    WR: [["tshare", "Tgt%", a => a.tshare, a => pc(a.tshare, 1)], ["wopr", "WOPR", a => a.wopr, a => f2(a.wopr)], ["adot", "aDOT", a => a.adot, a => f1(a.adot)], ["epa_tgt", "EPA/tgt", a => a.epa_tgt, a => sg(a.epa_tgt)], ["yacoe", "YACOE", a => a.yacoe, a => sg(a.yacoe, 1)], ["sep", "Sep.", a => a.sep, a => f2(a.sep)], ["rz_tgt", "RZ tgt", a => a.rz_tgt, a => f0(a.rz_tgt)]],
    RB: [["rush_share", "Car%", a => a.rush_share, a => pc(a.rush_share, 1)], ["epa_rush", "EPA/car", a => a.epa_rush, a => sg(a.epa_rush)], ["ryoe", "RYOE", a => a.ryoe, a => sg(a.ryoe)], ["expl", "Expl%", a => a.expl, a => pc(a.expl)], ["gl_share", "GL%", a => a.gl_share, a => pc(a.gl_share)], ["tshare", "Tgt%", a => a.tshare, a => pc(a.tshare, 1)]],
    QB: [["epa_db", "EPA/db", a => a.epa_db, a => sg(a.epa_db)], ["cpoe", "CPOE", a => a.cpoe, a => sg(a.cpoe, 1)], ["sack", "Sack%", a => a.sack, a => pc(a.sack, 1)]],
  };
  posCols.TE = posCols.WR;
  const extra = (posCols[pos] || []).map(([k, l, v, f]) => ({ k, l, n: 1, v: p => v(A(p)), f: p => f(A(p)) }));
  const ks = (S.state.keyStats[pos] || []).map(([sid, l]) => ({ k: "s" + sid, l, n: 1, v: p => p.key[sid], f: p => f0(p.key[sid]) }));
  const cols = [...base, ...extra, ...(posCols[pos] ? [] : ks), { k: "owned", l: "% eig.", n: 1, v: p => p.owned, f: p => f1(p.owned) }, { k: "owner", l: "Status", v: p => p.mine ? 0 : isFree(p) ? 1 : 2, f: ownerLabel }];
  let rows = Object.values(S.state.players).filter(p => p.pos === pos);
  if (filt === "free") rows = rows.filter(p => p.mine || isFree(p));
  if (filt === "mine") rows = rows.filter(p => p.mine);
  if (q) rows = rows.filter(p => (p.name + " " + p.team).toLowerCase().includes(q));
  const col = cols.find(c => c.k === sortKey) || cols[4];
  rows.sort((a, b) => { const x = col.v(a), y = col.v(b); if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1; const r = typeof x === "string" ? x.localeCompare(y) : x - y; return asc ? r : -r; });
  after(root => {
    $$("[data-pos]", root).forEach(b => b.onclick = () => { location.hash = "#/vergelijken/" + encodeURIComponent(b.dataset.pos); });
    $$("[data-filt]", root).forEach(b => b.onclick = () => { S.ui.mktFilt = b.dataset.filt; render(); });
    const s = $("#mktQ", root); if (s) { s.oninput = () => { S.ui.mktQ = s.value; render(); const n = $("#mktQ"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }; }
    $$("th[data-k]", root).forEach(th => th.onclick = () => { if (S.ui.mktSort === th.dataset.k) S.ui.mktAsc = !S.ui.mktAsc; else { S.ui.mktSort = th.dataset.k; S.ui.mktAsc = ["name", "rankProj", "owner"].includes(th.dataset.k); } render(); });
  });
  return `${analyticsNote()}<div class="panel">
    <div class="panel-h"><div class="seg">${POSITIONS.map(x => `<button data-pos="${x}" aria-pressed="${x === pos}">${x}</button>`).join("")}</div>
      <div class="controls"><div class="seg">${[["all", "Alle"], ["free", "Vrij & waivers"], ["mine", "Mijn spelers"]].map(([k, l]) => `<button data-filt="${k}" aria-pressed="${filt === k}">${l}</button>`).join("")}</div>
      <input type="search" id="mktQ" placeholder="Zoek speler of team…" value="${esc(S.ui.mktQ || "")}" aria-label="Zoek"><span class="muted small">${rows.length} spelers</span></div></div>
    <div class="scroll"><table class="t"><thead><tr>${cols.map(c => `<th class="sortable ${c.n ? "n" : c.c ? "c" : ""} ${c.k === sortKey ? "sorted" + (asc ? " asc" : "") : ""}" data-k="${c.k}">${esc(c.l)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(p => `<tr class="click ${p.mine ? "mine" : ""}" data-go="#/speler/${p.id}">${cols.map(c => `<td class="${c.n ? "n" : c.c ? "c" : ""}">${c.f(p)}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${cols.length}" class="empty">Geen spelers.</td></tr>`}</tbody></table></div>
  </div>
  <footer class="foot">Tgt% = aandeel team-targets · WOPR = 1.5×targetshare + 0.7×air-yards-share · aDOT = gem. targetdiepte · YACOE = yards na de catch boven verwachting · Sep. = NGS-separatie · RYOE = rushing yards boven verwachting per carry · GL% = aandeel carries binnen de 5 · CPOE = completion % boven verwachting.</footer>`;
}

/* ================= SCOUTING ================= */
async function viewScouting(args) {
  if (args[0]) return viewDefense(args[0]);
  const defs = S.state.defenses || [];
  if (!defs.length) return `<div class="empty">Analytics worden nog geladen…</div>`;
  const nT = S.state.analytics.nTeams || 32, L = S.state.analytics.league;
  const oppMap = {};
  // eigen starters (geen D/ST: die speelt tegen de aanval, niet tegen deze defense)
  myRoster().filter(p => isStarter(p) && p.pos !== "D/ST").forEach(p => { if (p.opp) (oppMap[p.opp] = oppMap[p.opp] || []).push(p); });
  const sortKey = S.ui.defSort || "epa_pass", asc = S.ui.defAsc ?? false;
  const cols = [
    { k: "team", l: "Defense", v: d => d.team, f: d => `<span class="pn">${esc(d.team)}</span>${oppMap[d.team] ? ` <span class="pinits">${playerChips(oppMap[d.team])}</span>` : ""}` },
    { k: "epa_pass", l: "EPA/db", v: d => d.epa_pass, f: d => rc(d, "epa_pass", sg(d.epa_pass)) },
    { k: "epa_rush", l: "EPA/car", v: d => d.epa_rush, f: d => rc(d, "epa_rush", sg(d.epa_rush)) },
    { k: "ypc", l: "YPC", v: d => d.ypc, f: d => rc(d, "ypc", f1(d.ypc)) },
    { k: "blitz_rate", l: "Blitz%", v: d => d.blitz_rate, f: d => pc(d.blitz_rate) },
    { k: "pressure_rate", l: "Druk%", v: d => d.pressure_rate, f: d => rc(d, "pressure_rate", pc(d.pressure_rate)) },
    { k: "box_avg", l: "Box", v: d => d.box_avg, f: d => f1(d.box_avg) },
    { k: "stacked", l: "8+ box", v: d => d.box.stacked.freq, f: d => pc(d.box.stacked.freq) },
    { k: "deep", l: "Diep EPA", v: d => d.depth.diep.epa, f: d => rc(d, "epa_diep", sg(d.depth.diep.epa)) },
    ...["QB", "RB", "WR", "TE"].map(q => ({ k: "fp" + q, l: "PPR " + q, v: d => d.fp_allowed[q], f: d => rc(d, "fp_" + q, f1(d.fp_allowed[q])) })),
  ];
  function rc(d, m, txt) { const rk = d.rank && d.rank[m]; const cls = rk ? (rk <= nT / 3 ? "neg" : rk > nT * 2 / 3 ? "pos" : "") : ""; return `<span class="def-cell ${cls}" data-tip="Rang ${rk}/${nT} (1 = lastigst voor de aanval)">${txt}</span>`; }
  const col = cols.find(c => c.k === sortKey) || cols[1];
  const rows = defs.slice().sort((a, b) => { const x = col.v(a), y = col.v(b); const r = typeof x === "string" ? x.localeCompare(y) : (x ?? 0) - (y ?? 0); return asc ? r : -r; });
  after(root => $$("th[data-k]", root).forEach(th => th.onclick = () => { if (S.ui.defSort === th.dataset.k) S.ui.defAsc = !S.ui.defAsc; else { S.ui.defSort = th.dataset.k; S.ui.defAsc = th.dataset.k === "team"; } render(); }));
  return `<div class="panel"><div class="panel-h"><h2>Alle defenses</h2><div class="legend"><span><span class="def-cell pos">&nbsp;</span> gunstig voor de aanval (onderste derde)</span><span><span class="def-cell neg">&nbsp;</span> lastig (bovenste derde)</span></div></div>
    <div class="scroll"><table class="t"><thead><tr>${cols.map(c => `<th class="sortable ${c.k === "team" ? "" : "n"} ${c.k === sortKey ? "sorted" + (asc ? " asc" : "") : ""}" data-k="${c.k}">${c.l}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(d => `<tr class="click" data-go="#/scouting/${esc(d.team)}">${cols.map(c => `<td class="${c.k === "team" ? "" : "n"}">${c.f(d)}</td>`).join("")}</tr>`).join("")}</tbody>
    <tfoot><tr>${cols.map((c, i) => `<td class="${i ? "n" : ""} muted small">${i === 0 ? "League" : ""}</td>`).join("")}</tr></tfoot></table></div></div>
    <footer class="foot">EPA/db en EPA/car = expected points toegestaan per dropback/carry · Blitz% en box uit FTN-charting · Druk% = QB hits + sacks per dropback · PPR = gem. PPR-punten toegestaan per wedstrijd aan die positie (nflverse). League-gemiddelden: EPA/db ${sg(L.epa_pass)}, EPA/car ${sg(L.epa_rush)}, blitz ${pc(L.blitz_rate)}, druk ${pc(L.pressure_rate)}.</footer>`;
}
async function viewDefense(team) {
  let d = S.cache.defense[team];
  if (!d) { try { d = await api("/api/defense/" + encodeURIComponent(team)); S.cache.defense[team] = d; } catch (e) { return `<div class="empty">Geen data voor ${esc(team)} (${esc(e.message)}).</div>`; } }
  const D = d.defense, L = d.league, nT = d.nTeams;
  const legend = `<span class="legend"><span><i class="sw" style="background:var(--series-1)"></i>${esc(D.team)}</span><span><i class="sw" style="background:var(--neutral-mark)"></i>league</span></span>`;
  const mine = myRoster().filter(p => p.opp === D.team);
  const depthRows = ["achter", "kort", "middel", "diep"].map(b => `<tr><td>${DEPTH_L[b]}</td><td class="n">${pc(D.depth[b].share)}</td><td>${pairBar(D.depth[b].share, L.depth[b].share, .7)}</td><td class="n">${sg(D.depth[b].epa)}</td><td class="n muted">${sg(L.depth[b].epa)}</td><td class="n">${f1(D.depth[b].ypt)}</td></tr>`).join("");
  const locRows = ["left", "middle", "right"].map(b => `<tr><td>${LOC_L[b]}</td><td class="n">${pc(D.loc[b].share)}</td><td class="n">${sg(D.loc[b].epa)}</td><td class="n muted">${sg(L.loc[b].epa)}</td></tr>`).join("");
  const posRows = ["WR", "TE", "RB"].map(b => `<tr><td>${b}</td><td class="n">${pc(D.vs_pos[b].share)}</td><td>${pairBar(D.vs_pos[b].share, L.vs_pos[b].share, .8)}</td><td class="n">${f1(D.vs_pos[b].ypt)}</td><td class="n">${pc(D.vs_pos[b].catch)}</td><td class="n">${sg(D.vs_pos[b].epa)}</td><td class="n muted">${sg(L.vs_pos[b].epa)}</td></tr>`).join("");
  const boxRows = ["licht", "normaal", "stacked"].map(b => `<tr><td>${BOX_L[b]}</td><td class="n">${pc(D.box[b].freq)}</td><td>${pairBar(D.box[b].freq, L.box[b].freq, .8)}</td><td class="n">${f1(D.box[b].ypc)}</td><td class="n muted">${f1(L.box[b].ypc)}</td></tr>`).join("");
  return `<div class="stack">
    <div class="controls"><a href="#/scouting">← Alle defenses</a>${mine.length ? `<span class="muted">Jouw spelers tegen ${esc(D.team)} deze week: ${mine.map(p => `<a href="#/speler/${p.id}">${esc(p.name)}</a>`).join(", ")}</span>` : ""}</div>
    <div class="grid g2">
      <div class="panel"><div class="panel-h"><h2>${esc(D.team)}: kerncijfers</h2><span class="sub">${D.games} wedstrijden</span></div><div class="scroll">${defSummary(D, L, nT)}</div></div>
      <div class="panel"><div class="panel-h"><h2>Coverage per verdediger</h2><span class="sub">PFR advanced stats</span></div><div class="scroll">${defendersTable(D)}</div></div>
      <div class="panel"><div class="panel-h"><h2>Wat ze weggeven: passdiepte</h2>${legend}</div><div class="scroll"><table class="t compact"><thead><tr><th>Diepte</th><th class="n">Aandeel tgt</th><th>vs league</th><th class="n">EPA/tgt</th><th class="n">League</th><th class="n">Yds/tgt</th></tr></thead><tbody>${depthRows}</tbody></table></div></div>
      <div class="panel"><div class="panel-h"><h2>Targets toegestaan per positie</h2>${legend}</div><div class="scroll"><table class="t compact"><thead><tr><th>Positie</th><th class="n">Aandeel</th><th>vs league</th><th class="n">Yds/tgt</th><th class="n">Catch%</th><th class="n">EPA/tgt</th><th class="n">League</th></tr></thead><tbody>${posRows}</tbody></table></div></div>
      <div class="panel"><div class="panel-h"><h2>Run defense: boxcount</h2>${legend}</div><div class="scroll"><table class="t compact"><thead><tr><th>Box</th><th class="n">Frequentie</th><th>vs league</th><th class="n">YPC</th><th class="n">League</th></tr></thead><tbody>${boxRows}</tbody></table></div></div>
      <div class="panel"><div class="panel-h"><h2>Richting & situaties</h2></div><div class="scroll"><table class="t compact"><thead><tr><th>Kant</th><th class="n">Aandeel</th><th class="n">EPA/tgt</th><th class="n">League</th></tr></thead><tbody>${locRows}</tbody></table>
        <table class="t compact"><thead><tr><th>Situatie</th><th class="n">EPA toegestaan</th><th class="n">League</th></tr></thead><tbody>
        <tr><td>Wanneer ze blitzen</td><td class="n">${sg(D.epa_blitz)}</td><td class="n muted">${sg(L.epa_blitz)}</td></tr>
        <tr><td>Zonder blitz</td><td class="n">${sg(D.epa_noblitz)}</td><td class="n muted">${sg(L.epa_noblitz)}</td></tr>
        <tr><td>Tegen play-action</td><td class="n">${sg(D.epa_pa)}</td><td class="n muted">${sg(L.epa_pa)}</td></tr>
        <tr><td>Zonder play-action</td><td class="n">${sg(D.epa_nopa)}</td><td class="n muted">${sg(L.epa_nopa)}</td></tr></tbody></table></div></div>
    </div></div>`;
}

/* ================= NIEUWS ================= */
function viewNews() {
  if (!S.news) { loadNews(); return `<div class="loading">Nieuws laden…</div>`; }
  const scope = S.ui.newsScope || "mine", src = S.ui.newsSrc || "all";
  const sel = S.ui.newsSel || new Set(); S.ui.newsSel = sel;
  let items = scope === "mine" ? S.news.mine : scope === "opp" ? S.news.opp : S.news.latest;
  if (src !== "all") items = items.filter(n => n.source === src);
  if (sel.size) items = items.filter(n => (n.player_ids || []).some(i => sel.has(i)));
  const ro = scope === "opp" ? oppRoster() : myRoster();
  after(root => {
    $$("[data-scope]", root).forEach(b => b.onclick = () => { S.ui.newsScope = b.dataset.scope; S.ui.newsSel = new Set(); render(); });
    $$("[data-src]", root).forEach(b => b.onclick = () => { S.ui.newsSrc = b.dataset.src; render(); });
    $$("[data-pid]", root).forEach(b => b.onclick = () => { const i = +b.dataset.pid; sel.has(i) ? sel.delete(i) : sel.add(i); render(); });
  });
  return `<div class="panel"><div class="panel-h">
      <div class="controls"><div class="seg">${[["mine", "Mijn team"], ["opp", "Tegenstander"], ["all", "Alle spelers"]].map(([k, l]) => `<button data-scope="${k}" aria-pressed="${scope === k}">${l}</button>`).join("")}</div>
      <div class="seg">${[["all", "Alle bronnen"], ["ESPN", "ESPN"], ["Rotowire", "Rotowire"]].map(([k, l]) => `<button data-src="${k}" aria-pressed="${src === k}">${l}</button>`).join("")}</div></div>
      <span class="sub">${items.length} items</span></div>
    ${scope !== "all" ? `<div class="panel-b"><div class="pchips">${ro.map(p => `<button class="pchip" data-pid="${p.id}" aria-pressed="${sel.has(p.id)}">${esc(p.name)}</button>`).join("")}</div></div>` : ""}
    ${newsList(items.slice(0, 150), true)}</div>
    <footer class="foot">Bronnen: ESPN-artikelen en -analyses, Rotowire-spelersupdates (via ESPN en de Rotowire-RSS-feed). ${etlLine(S.news.etl)}</footer>`;
}
function etlLine(e) {
  if (!e) return "";
  const r = (e.runs || [])[0], t = e.totals || {};
  const where = e.backend === "postgres" ? "Postgres" : e.backend === "json" ? "lokaal JSON-bestand" : e.backend;
  let txt = `Opslag: ${esc(where)}${num(t.items) ? ` · ${f0(t.items)} artikelen${num(t.links) ? `, ${f0(t.links)} spelerkoppelingen` : ""}` : ""}.`;
  if (r) txt += ` Laatste ETL-run${r.started ? ` (${ago(r.started)})` : ""}: ${esc(r.status)}, ${r.extracted ?? "–"} opgehaald, ${r.loaded_items ?? 0} nieuw${num(r.seconds) ? ` (${r.seconds}s)` : ""}.`;
  if (r && r.message) txt += ` <span data-tip="${esc(r.message)}">⚠ waarschuwing</span>`;
  return txt;
}

/* ================= LEAGUE ================= */
async function viewLeague() {
  let L;
  try { L = await api("/api/league"); } catch (e) { return `<div class="empty">League laden mislukt (${esc(e.message)}).</div>`; }
  const T = S.state.fantasyTeams, me = S.state.meta.teamId;
  const tn = id => T[id] ? esc(T[id].name) : "Team " + id;
  const started = L.started;
  const mu = L.matchups.map(m => {
    const mine = m.a === me || m.b === me;
    const side = (id, tot, fin, wp) => `<div class="side ${id === m.b ? "r" : ""}"><div class="tn">${tn(id)}</div><div class="rec">${T[id] ? esc(T[id].owner || "") : ""}</div>
      <div class="score" style="font-size:26px">${started ? f1(tot) : f1(fin)}</div><div class="proj">${started ? "verwacht " + f1(fin) : "projectie"} · ${Math.round(wp * 100)}%</div></div>`;
    return `<div class="panel" style="${mine ? "box-shadow: inset 3px 0 0 var(--mine-edge)" : ""}"><div class="mu">${side(m.a, m.aTotal, m.aFinal, m.aWin)}<div class="vs">${L.anyLive ? '<span class="livepill">Live</span>' : "VS"}</div>${side(m.b, m.bTotal, m.bFinal, 1 - m.aWin)}</div>
      <div class="wp"><div class="wp-bar" role="img" aria-label="Winkans"><i style="width:${m.aWin * 100}%;background:var(--series-1)"></i><i style="flex:1;background:var(--series-2)"></i></div></div></div>`;
  }).join("");
  const rows = L.standings.map((t, i) => `<tr class="${t.id === me ? "mine" : ""} click" data-team="${t.id}"><td class="n muted">${i + 1}</td><td><div class="pn">${esc(t.name)}</div><div class="pm">${esc(t.owner || "")}</div></td><td class="n">${t.wins}-${t.losses}${t.ties ? "-" + t.ties : ""}</td><td class="n">${f1(t.pf)}</td><td class="n">${f1(t.pa)}</td><td class="n">${esc(t.streak || "")}</td></tr>`).join("");
  after(root => $$("[data-team]", root).forEach(tr => tr.onclick = () => { if (+tr.dataset.team !== me && confirm(`Bekijk de app als ${T[tr.dataset.team].name}?`)) switchTeam(+tr.dataset.team); }));
  return `<div class="grid g-side"><div class="stack"><h2 style="font-size:13px;margin:0">Matchups week ${L.week}</h2>${mu || `<div class="empty">Geen matchups gevonden.</div>`}</div>
    <div class="panel"><div class="panel-h"><h2>Stand</h2><span class="sub">klik op een team om de app als dat team te bekijken</span></div><div class="scroll"><table class="t"><thead><tr><th class="n">#</th><th>Team</th><th class="n">W-V</th><th class="n">Voor</th><th class="n">Tegen</th><th class="n">Reeks</th></tr></thead><tbody>${rows}</tbody></table></div></div></div>`;
}

/* ================= TOEGANG & TEAMKEUZE ================= */
function showGate(kind, msg) {
  S.state = null;
  document.body.classList.add("gated");
  const v = $("#view");
  $("#pageTitle").textContent = kind === "code" ? "Welkom" : "Kies je team";
  $("#crumbs").textContent = AUTH.leagueName || "";
  setStatus("");
  if (kind === "code") {
    v.innerHTML = `<div class="gate panel"><div class="panel-b">
      <div class="brand-mark" style="margin-bottom:12px">FM</div>
      <h2 style="margin:0 0 4px">Fantasy Manager</h2>
      <p class="muted" style="margin:0 0 14px">${esc(AUTH.leagueName || "Je league")}: vul de toegangscode in die je van de beheerder hebt gekregen.</p>
      ${msg ? `<div class="err">${esc(msg)}</div>` : ""}
      <form id="codeForm" class="controls"><input type="password" id="codeIn" placeholder="Toegangscode" autocomplete="current-password" required style="flex:1;min-width:0">
      <button class="btn primary" type="submit">Verder</button></form></div></div>`;
    $("#codeForm").onsubmit = e => { e.preventDefault(); AUTH.code = $("#codeIn").value.trim(); store.set("fm-code", AUTH.code); boot(); };
    setTimeout(() => $("#codeIn") && $("#codeIn").focus(), 50);
  } else {
    const teams = AUTH.teams || [];
    v.innerHTML = `<div class="gate panel" style="max-width:640px"><div class="panel-h"><h2>Welk team is van jou?</h2><span class="sub">${esc(AUTH.leagueName || "")}</span></div>
      <ul class="inbox">${teams.map(t => `<li data-pick="${t.id}"><div class="ic" style="font-size:11px;font-weight:800">${esc((t.abbrev || t.name || "").slice(0, 2).toUpperCase())}</div><div><div class="subj">${esc(t.name)}</div><div class="body">${esc(t.owner || "")} · ${t.wins}-${t.losses}${t.ties ? "-" + t.ties : ""} · team-ID ${t.id}</div></div><div class="when">Kies →</div></li>`).join("")}</ul></div>`;
    $$("[data-pick]", v).forEach(li => li.onclick = () => switchTeam(+li.dataset.pick));
  }
}
function switchTeam(tid) {
  AUTH.team = tid; store.set("fm-team", String(tid));
  const u = new URL(location.href); u.searchParams.set("team", tid); history.replaceState(null, "", u.pathname + u.search + (location.hash || "#/overzicht"));
  S.state = null; S.live = null; S.news = null; S.cache = { player: {}, defense: {} };
  document.body.classList.remove("gated");
  $("#view").innerHTML = `<div class="loading">Team laden…</div>`;
  loadState();
}
function renderTeamSel() {
  const sel = $("#teamSel"); if (!sel || !AUTH.teams) return;
  if (!sel.options.length) {
    sel.innerHTML = AUTH.teams.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
    sel.onchange = () => switchTeam(+sel.value);
    $("#shareBtn").onclick = async () => {
      const link = `${location.origin}/?team=${AUTH.team}`;
      try { await navigator.clipboard.writeText(link); setStatus("Link gekopieerd: " + link); } catch (e) { prompt("Kopieer deze link:", link); }
    };
  }
  sel.value = String(AUTH.team);
}
async function boot() {
  try {
    const cfg = await (await fetch("/api/config")).json();
    AUTH.needsCode = cfg.needsCode; AUTH.leagueName = cfg.leagueName;
    if (cfg.needsCode && !AUTH.code) return showGate("code");
    let t;
    for (let i = 0; i < 40; i++) {  // wachten tot de server de league heeft geladen
      t = await api("/api/teams");
      if (t.teams.length) break;
      $("#view").innerHTML = `<div class="loading">League laden: de eerste keer duurt dit ongeveer een halve minuut…</div>`;
      await new Promise(r => setTimeout(r, 3000));
    }
    AUTH.teams = t.teams; AUTH.leagueName = t.leagueName;
    const valid = AUTH.team && t.teams.some(x => x.id === AUTH.team);
    if (!valid) { AUTH.team = null; return showGate("team"); }
    switchTeam(AUTH.team);
  } catch (e) { if (!(e instanceof AuthError)) $("#view").innerHTML = `<div class="empty">Server niet bereikbaar (${esc(e.message)}).</div>`; }
}

/* ---------------- start ---------------- */
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => { });
boot();
