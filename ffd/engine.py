"""
Engine: haalt alle league-data op, combineert die en ververst op de achtergrond.

Eén engine bedient de hele league; elk API-verzoek kiest een team (team_id).
"""
import datetime as dt
import math
import os
import subprocess
import sys
import threading
import time
import traceback

from .espn import (KEY_STATS, POS, POS_SLOT, SLOT, AuthError, Espn, build_player, live_line,
                   parse_scoreboard, score_stats, scoring_table, stat_index)
from .model import AnalyticsResult
from .news import NewsStore, fetch_rotowire, match_rotowire, norm_name

BUILD_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_analytics.py")

POOL_DEPTH = {"QB": 36, "RB": 60, "WR": 75, "TE": 36, "K": 24, "D/ST": 32}
BENCH_SLOTS = ("Bank", "IR")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


class Engine:
    def __init__(self, cfg, demo=False, week=None, data_dir="data", log=print):
        self.cfg = cfg
        self.demo = demo
        self.week_override = week
        self.log = log
        self.season = int(cfg["season"])
        self.league_id = None if demo else int(cfg["league_id"])
        self.default_team = int(cfg["team_id"]) if cfg.get("team_id") and not demo else 1
        self.espn = Espn(self.season, cfg.get("espn_s2"), cfg.get("swid"))
        self.cache_dir = os.path.join(data_dir, "cache")
        self.analytics_path = os.path.join(data_dir, f"analytics_{self.season}.json")
        try:
            self.analytics = AnalyticsResult.load(self.analytics_path)
        except Exception as e:  # beschadigd bestand: opnieuw bouwen
            log(f"Analytics-cache onleesbaar ({e}); wordt opnieuw gebouwd.")
            self.analytics = AnalyticsResult()
        json_path = os.path.join(data_dir, "news.json")
        if cfg.get("database_url"):
            from .etl_news import PostgresNewsStore  # Polars/psycopg alleen laden als nodig
            self.news = PostgresNewsStore(cfg["database_url"], log=log, legacy_json=json_path)
        else:
            self.news = NewsStore(json_path)
        self.lock = threading.RLock()
        self.heavy = threading.Lock()   # zware taken (ESPN-pool, analytics) nooit tegelijk: geheugen
        self.players = {}        # id -> espn-speler (volledige pool)
        self.rosters = {}        # team_id -> [{id, slot}]
        self.pairs = {}          # team_id -> tegenstander team_id (huidige matchup)
        self.fantasy_teams = {}
        self.meta = {}
        self.lines, self.games = {}, {}
        self.live_updated = None
        self.any_live = False
        self.events = []
        self._last_pts = {}
        self._news_seen = {}     # speler-id -> lastNewsDate bij laatste ophaalbeurt
        self._summ = {}
        self.errors = []

    # ------------------------------------------------------------------
    def _err(self, where, e, level="error"):
        """level 'error' = zichtbaar in de app (bijv. cookie verlopen); 'warn' = alleen in de log."""
        msg = f"{where}: {e}"
        self.log(("FOUT " if level == "error" else "LET OP ") + msg)
        if level == "error":
            self.errors = (self.errors + [{"at": now_iso(), "msg": msg}])[-10:]

    def team_ok(self, tid):
        return tid in self.fantasy_teams

    def ctx(self, tid):
        """(eigen selectie, selectie tegenstander, tegenstander-id)."""
        opp = self.pairs.get(tid)
        return self.rosters.get(tid, []), self.rosters.get(opp, []) if opp else [], opp

    # ------------------------------------------------------------------
    # Fantasy (ESPN)
    # ------------------------------------------------------------------
    def refresh_fantasy(self):
        with self.heavy:
            self._refresh_fantasy()

    def _refresh_fantasy(self):
        self.log("ESPN: league, selecties en projecties ophalen…")
        week = self.week_override or self.espn.current_week()
        pro = self.espn.pro_teams()
        meta = {"season": self.season, "week": week, "demo": self.demo}
        fantasy_teams, rosters, pairs = {}, {}, {}

        if self.demo:
            raw = self.espn.players(None, week)
        else:
            ld = self.espn.league(self.league_id, week)
            meta["leagueName"] = ld.get("settings", {}).get("name") or f"League {self.league_id}"
            members = {m.get("id"): m for m in ld.get("members", [])}
            for t in ld.get("teams", []):
                name = t.get("name") or f'{t.get("location", "")} {t.get("nickname", "")}'.strip()
                rec = (t.get("record") or {}).get("overall") or {}
                owners = [members.get(o, {}) for o in (t.get("owners") or [])]
                owner = ", ".join(filter(None, [
                    (o.get("firstName", "") + " " + o.get("lastName", "")).strip() or o.get("displayName", "")
                    for o in owners]))
                fantasy_teams[t["id"]] = {
                    "id": t["id"], "name": name, "abbrev": t.get("abbrev", str(t["id"])), "owner": owner,
                    "logo": t.get("logo"), "wins": rec.get("wins", 0), "losses": rec.get("losses", 0),
                    "ties": rec.get("ties", 0), "pf": rec.get("pointsFor"), "pa": rec.get("pointsAgainst"),
                    "seed": t.get("playoffSeed"), "streak": f'{(rec.get("streakType") or "")[:1]}{rec.get("streakLength") or ""}',
                }
                rosters[t["id"]] = [{"id": e["playerId"], "slot": SLOT.get(e["lineupSlotId"], "Bank")}
                                    for e in (t.get("roster") or {}).get("entries", [])]
            mp = (ld.get("status") or {}).get("currentMatchupPeriod")
            for m in ld.get("schedule", []):
                if m.get("matchupPeriodId") != mp:
                    continue
                h, a = (m.get("home") or {}).get("teamId"), (m.get("away") or {}).get("teamId")
                if h and a:
                    pairs[h], pairs[a] = a, h
            ids = [r["id"] for ro in rosters.values() for r in ro]
            raw = self.espn.players(self.league_id, week, ids)
            table = scoring_table(ld.get("settings"))

        players = {}
        for e in raw:
            p = build_player(e, self.season, week, pro)
            if p["pos"]:
                players[p["id"]] = p

        if not self.demo:
            meta["projCheck"] = self._fill_past_projections(players, raw, table, week)

        if self.demo:
            fantasy_teams, rosters, pairs = self._demo_league(players)
            meta["leagueName"] = "Demo-league (openbare ESPN PPR-projecties)"

        # wie heeft welke speler (voor status-kolommen)
        owner_of = {r["id"]: tid for tid, ro in rosters.items() for r in ro}
        for pid, p in players.items():
            p["onTeamId"] = owner_of.get(pid, 0)

        # fantasy-punten toegestaan per positie (scoring van de league)
        allowed = {}
        for p in players.values():
            team = pro.get(p["proTeamId"])
            if not team:
                continue
            for w in p["weekly"]:
                g = team["games"].get(w["wk"])
                if w["pts"] is None or not g:
                    continue
                b = allowed.setdefault(p["pos"], {}).setdefault(pro[g["opp"]]["abbrev"], {})
                b[w["wk"]] = b.get(w["wk"], 0) + w["pts"]
        fp_allowed = {}
        for pos, opps in allowed.items():
            avgs = {o: sum(v.values()) / len(v) for o, v in opps.items() if v}
            ranked = sorted(avgs, key=lambda o: avgs[o])
            fp_allowed[pos] = {o: {"avg": round(avgs[o], 1), "rank": i + 1, "of": len(ranked)}
                               for i, o in enumerate(ranked)}
        for pos in {p["pos"] for p in players.values()}:
            grp = [p for p in players.values() if p["pos"] == pos]
            for key, rk in (("total", "rankTotal"), ("proj", "rankProj")):
                for i, p in enumerate(sorted(grp, key=lambda x: -(x[key] or 0))):
                    p[rk] = i + 1
            for p in grp:
                p["fpAllowed"] = fp_allowed.get(pos, {}).get(p["opp"])

        with self.lock:
            self.pro = pro
            self.players = players
            self.rosters, self.pairs = rosters, pairs
            self.fantasy_teams = fantasy_teams
            self.meta = meta
            self.week = week
            self._summ = {}
        self.log(f"ESPN: week {week}, {len(players)} spelers, {len(fantasy_teams)} teams.")

    def _fill_past_projections(self, players, raw, table, week):
        """Vul ontbrekende projecties van afgelopen weken aan.

        Het league-endpoint geeft voor een privé-league alleen de projectie van de
        huidige week. De openbare ESPN-data heeft de oude weekprojecties wél (als
        ruwe statregels); die rekenen we om met de scoringsregels van de league.
        Eerst controleren we de rekenregel op de échte weekpunten van de league:
        alleen als die (bijna) overal klopt, worden de projecties ingevuld.
        """
        if not table:
            return None
        diffs = []
        for e in raw:
            pl = e["player"]
            slot = POS_SLOT.get(POS.get(pl.get("defaultPositionId")))
            for (w, src, spl), st in stat_index(pl, self.season).items():
                if src == 0 and spl == 1 and w and st.get("stats") and st.get("appliedTotal") is not None:
                    diffs.append(abs(score_stats(st["stats"], table, slot) - st["appliedTotal"]))
        if len(diffs) < 30:
            self.log("Projecties: te weinig data om de league-scoring te controleren; niet ingevuld.")
            return None
        rate = sum(1 for d in diffs if d <= 0.2) / len(diffs)
        if rate < 0.9:
            self.log(f"Projecties: league-scoring niet betrouwbaar na te rekenen ({rate:.0%} klopt); niet ingevuld.")
            return {"rate": round(rate, 3), "filled": 0}
        need = [pid for pid, p in players.items()
                if any(w["proj"] is None and not w["bye"] for w in p["weekly"])]
        filled = 0
        for i in range(0, len(need), 150):
            try:
                pub = self.espn.players_by_id(None, week, need[i:i + 150])
            except Exception as e:
                self._err("Projecties", e, "warn")
                break
            for e in pub:
                p = players.get(e["player"]["id"])
                if not p:
                    continue
                idx, slot = stat_index(e["player"], self.season), POS_SLOT.get(p["pos"])
                for w in p["weekly"]:
                    if w["proj"] is None and not w["bye"]:
                        st = idx.get((w["wk"], 1, 1))
                        if st is not None:  # lege statregel = 0 geprojecteerd (bijv. geblesseerd)
                            w["proj"] = round(score_stats(st.get("stats") or {}, table, slot), 1)
                            filled += 1
        self.log(f"Projecties: {filled} weekprojecties omgerekend naar league-scoring "
                 f"(controle: {rate:.0%} van {len(diffs)} weekscores exact nagerekend).")
        return {"rate": round(rate, 3), "filled": filled}

    def _demo_league(self, players):
        """Snake-draft van 8 demoteams uit de openbare spelerspool."""
        names = ["Demoteam", "Gridiron Gang", "Red Zone Raiders", "Fourth & Long", "Blitz Brigade",
                 "Hail Mary FC", "Pick Six", "Two-Point Kings"]
        template = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "D/ST", "K", "Bank", "Bank", "Bank", "Bank", "Bank"]
        avail = sorted(players.values(), key=lambda x: -((x["ros"] or 0) + 3 * (x["proj"] or 0)))
        used = set()
        rosters = {i + 1: [] for i in range(len(names))}
        order = list(rosters)
        for rnd, slot in enumerate(template):
            for tid in (order if rnd % 2 == 0 else order[::-1]):
                ok = {"FLEX": ("RB", "WR", "TE"), "Bank": ("QB", "RB", "WR", "TE")}.get(slot, (slot,))
                pick = next((p for p in avail if p["id"] not in used and p["pos"] in ok
                             and (slot == "Bank" or not p.get("bye"))), None)
                if pick:
                    used.add(pick["id"])
                    rosters[tid].append({"id": pick["id"], "slot": slot})
        recs = [(7, 3), (6, 4), (6, 4), (5, 5), (5, 5), (4, 6), (4, 6), (3, 7)]
        teams = {tid: {"id": tid, "name": names[tid - 1], "abbrev": names[tid - 1][:4].upper(),
                       "owner": f"Speler {tid}", "wins": recs[tid - 1][0], "losses": recs[tid - 1][1],
                       "ties": 0, "pf": None, "pa": None} for tid in rosters}
        pairs = {}
        for a in range(1, len(names), 2):
            pairs[a], pairs[a + 1] = a + 1, a
        return teams, rosters, pairs

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    def refresh_analytics(self):
        """Bouw de analytics in een apart proces (houdt het servergeheugen laag)."""
        os.makedirs(self.cache_dir, exist_ok=True)
        cmd = [sys.executable, BUILD_SCRIPT, str(self.season), self.cache_dir, self.analytics_path,
               str(self.cfg.get("nflverse_max_age_hours", 12))]
        env = dict(os.environ, ARROW_DEFAULT_MEMORY_POOL="system")
        with self.heavy:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, env=env)
        for line in (proc.stdout or "").splitlines():
            self.log(line)
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-1:]
            raise RuntimeError("analytics-build mislukt: " + (tail[0] if tail else f"code {proc.returncode}"))
        a = AnalyticsResult.load(self.analytics_path)
        with self.lock:
            self.analytics = a
            self._summ = {}

    def _analytics_age(self):
        try:
            return time.time() - os.path.getmtime(self.analytics_path)
        except OSError:
            return float("inf")

    def _summary(self, p):
        """Compacte analytics-samenvatting voor tabellen (gecachet per verversing)."""
        if p["id"] in self._summ:
            return self._summ[p["id"]]
        a = self.analytics
        out = None
        prof = a.profile_for_espn(p["id"]) if a.ready else None
        if prof:
            rec, rush, pas = prof.get("rec") or {}, prof.get("rush") or {}, prof.get("pass") or {}
            out = {
                "overall": prof.get("overall"), "low": prof.get("low_sample"),
                "attrs": [{"n": x["name"], "s": x["score"]} for x in prof.get("attrs", [])],
                "snap": prof.get("snap_pct"), "snap3": prof.get("snap_last3"),
                "tshare": rec.get("tshare"), "wopr": rec.get("wopr"), "adot": rec.get("adot"),
                "epa_tgt": rec.get("epa_tgt"), "yacoe": rec.get("yacoe"), "sep": rec.get("separation"),
                "rz_tgt": rec.get("rz_tgt"), "deep": rec.get("deep_share"),
                "rush_share": rush.get("rush_share"), "epa_rush": rush.get("epa_rush"),
                "ryoe": rush.get("ryoe_att"), "gl_share": rush.get("gl_share"), "expl": rush.get("expl_rate"),
                "epa_db": pas.get("epa_db"), "cpoe": pas.get("cpoe"), "sack": pas.get("sack_rate"),
                "ppr_pg": prof.get("ppr_pg"), "headshot": prof.get("headshot"),
            }
            if p.get("opp") and not p.get("bye"):
                m = a.matchup(prof["gsis"], p["opp"])
                if m:
                    out["edge"] = {"score": m["score"], "grade": m["grade"],
                                   "top": m["factors"][0]["text"] if m["factors"] else None}
        self._summ[p["id"]] = out
        return out

    # ------------------------------------------------------------------
    # Nieuws
    # ------------------------------------------------------------------
    def refresh_news(self):
        with self.lock:
            rostered = {r["id"] for ro in self.rosters.values() for r in ro}
            players = dict(self.players)
        # Alleen spelers met nieuw nieuws sinds de vorige keer (ESPN lastNewsDate),
        # meest recente eerst en per ronde beperkt. Bij 403/429 respecteren we de
        # limiet van ESPN: stoppen en pas na een (oplopende) wachttijd opnieuw.
        todo = sorted([pid for pid in rostered if pid > 0 and players.get(pid)
                       and players[pid].get("lastNews") != self._news_seen.get(pid)],
                      key=lambda pid: -(players[pid].get("lastNews") or 0))
        if time.time() < getattr(self, "_news_backoff_until", 0):
            todo = []
        batch = int(self.cfg.get("news_batch", 20))
        limit = int(self.cfg.get("news_per_player", 8))
        items, done, seen, warns = [], 0, {}, []
        for pid in todo[:batch]:  # één voor één, met pauze
            try:
                res = self.espn.news(pid, limit)
            except Exception as e:
                code = getattr(e, "code", None)
                if code in (403, 429):
                    self._news_backoff = min(3600, getattr(self, "_news_backoff", 300) * 2)
                    self._news_backoff_until = time.time() + self._news_backoff
                    warns.append(f"ESPN limiet bereikt ({code}); opnieuw over {self._news_backoff // 60} min")
                    self._err("ESPN-nieuws", warns[-1], "warn")
                    break
                warns.append(f"ESPN {pid}: {e}")
                self._err("ESPN-nieuws", e, "warn")
                continue
            for it in res:
                it["player_ids"] = [pid]
                items.append(it)
            seen[pid] = players[pid].get("lastNews")
            done += 1
            time.sleep(1.0)
        else:
            if done:
                self._news_backoff = 300
        name_to_ids = {}
        for p in players.values():
            name_to_ids.setdefault(norm_name(p["name"]), []).append(p["id"])
        try:
            items += match_rotowire(fetch_rotowire(), name_to_ids)
        except Exception as e:
            warns.append(f"Rotowire: {e}")
            self._err("Rotowire", e, "warn")
        # Load (Postgres of JSON). Pas na een geslaagde load markeren we spelers als
        # bijgewerkt, zodat een mislukte load bij de volgende ronde opnieuw gaat.
        new = self.news.ingest(items, players=players, extracted=len(items),
                               message="; ".join(warns) or None)
        self._news_seen.update(seen)
        self.log(f"Nieuws: {done} spelers bijgewerkt ({max(0, len(todo) - done)} in de wachtrij), "
                 f"{new} nieuwe items.")

    # ------------------------------------------------------------------
    # Live (voor alle spelers in de league tegelijk)
    # ------------------------------------------------------------------
    def refresh_live(self):
        with self.lock:
            week = self.week
            ids = sorted({r["id"] for ro in self.rosters.values() for r in ro})
            players = self.players
        lines = {}
        for i in range(0, len(ids), 150):
            for e in self.espn.players_by_id(self.league_id, week, ids[i:i + 150]):
                lines[e["player"]["id"]] = live_line(e, self.season, week)
        try:
            games = parse_scoreboard(self.espn.scoreboard(week))
        except Exception as e:
            self._err("Scoreboard", e, "warn")
            games = {}
        stamp = now_iso()
        events = []
        for pid, ln in lines.items():
            prev = self._last_pts.get(pid)
            if prev is not None and abs((ln["pts"] or 0) - prev) >= 0.5:
                p = players.get(pid, {})
                events.append({"at": stamp, "id": pid, "name": p.get("name"),
                               "delta": round((ln["pts"] or 0) - prev, 1), "pts": ln["pts"], "line": ln["line"]})
            self._last_pts[pid] = ln["pts"] or 0
        teams = {players[i]["team"] for i in ids if i in players}
        any_live = any(g["state"] == "in" for t, g in games.items() if t in teams)
        with self.lock:
            self.lines, self.games = lines, games
            self.events = (events + self.events)[:400]
            self.live_updated = stamp
            self.any_live = any_live
        return any_live

    def _side(self, roster):
        out, total, final, var = [], 0.0, 0.0, 0.0
        for r in roster:
            p = self.players.get(r["id"], {})
            ln = self.lines.get(r["id"], {"pts": 0.0, "proj": p.get("proj"), "line": ""})
            g = self.games.get(p.get("team"))
            frac = g["frac"] if g else (1.0 if p.get("bye") else 0.0)
            proj = ln.get("proj") or 0.0
            pts = ln.get("pts") or 0.0
            fin = pts + proj * (1 - frac)
            out.append({"id": r["id"], "slot": r["slot"], "name": p.get("name"), "pos": p.get("pos"),
                        "team": p.get("team"), "pts": pts, "proj": proj, "projFinal": round(fin, 1),
                        "line": ln.get("line"), "frac": frac, "injury": p.get("injury"),
                        "game": {k: g[k] for k in ("state", "detail", "teams", "redzone", "downDistance", "date")} if g else None})
            if r["slot"] not in BENCH_SLOTS:
                total += pts
                final += fin
                var += (max(3.0, 0.45 * proj) ** 2) * (1 - frac)
        return out, round(total, 1), round(final, 1), var

    def live_out(self, tid):
        with self.lock:
            if not self.live_updated:
                return {"status": "nog niet geladen"}
            roster, opp, opp_id = self.ctx(tid)
            mine, my_tot, my_fin, my_var = self._side(roster)
            theirs, op_tot, op_fin, op_var = self._side(opp)
            wp = None
            if opp:
                sd = math.sqrt(my_var + op_var)
                wp = (1.0 if my_fin > op_fin else 0.0) if sd == 0 else phi((my_fin - op_fin) / sd)
            mine_ids = {r["id"] for r in roster}
            rel = mine_ids | {r["id"] for r in opp}
            events = [dict(e, mine=e["id"] in mine_ids) for e in self.events if e["id"] in rel][:40]
            teams = {self.players[i]["team"] for i in rel if i in self.players}
            games = {g["id"]: g for t, g in self.games.items() if t in teams}
            any_live = any(g["state"] == "in" for g in games.values())
            return {"updated": self.live_updated, "week": self.week, "anyLive": any_live,
                    "me": {"rows": mine, "total": my_tot, "projFinal": my_fin},
                    "opp": {"rows": theirs, "total": op_tot, "projFinal": op_fin} if opp else None,
                    "winProb": wp, "events": events,
                    "games": sorted(games.values(), key=lambda g: g["date"] or "")}

    def league_out(self):
        """Stand + alle matchups van deze week met live/verwachte scores."""
        with self.lock:
            teams = sorted(self.fantasy_teams.values(),
                           key=lambda t: (-(t["wins"] + 0.5 * t["ties"]), -(t["pf"] or 0)))
            done, matchups = set(), []
            for a, b in self.pairs.items():
                if a in done:
                    continue
                done |= {a, b}
                sa, sb = self._side(self.rosters.get(a, [])), self._side(self.rosters.get(b, []))
                sd = math.sqrt(sa[3] + sb[3])
                wp = (1.0 if sa[2] > sb[2] else 0.0) if sd == 0 else phi((sa[2] - sb[2]) / sd)
                matchups.append({"a": a, "b": b, "aTotal": sa[1], "bTotal": sb[1],
                                 "aFinal": sa[2], "bFinal": sb[2], "aWin": wp})
            rostered_teams = {self.players[r["id"]]["team"] for ro in self.rosters.values() for r in ro
                              if r["id"] in self.players}
            started = any(g["state"] != "pre" for t, g in self.games.items() if t in rostered_teams)
            return {"standings": teams, "matchups": matchups, "anyLive": self.any_live, "started": started,
                    "updated": self.live_updated, "week": self.meta.get("week")}

    # ------------------------------------------------------------------
    # API-output
    # ------------------------------------------------------------------
    def teams_out(self):
        with self.lock:
            return {"leagueName": self.meta.get("leagueName"), "default": self.default_team,
                    "demo": self.demo,
                    "teams": [{k: t.get(k) for k in ("id", "name", "abbrev", "owner", "wins", "losses", "ties", "logo")}
                              for t in sorted(self.fantasy_teams.values(), key=lambda t: t["id"])]}

    def state_out(self, tid):
        with self.lock:
            if not self.players:
                return {"status": "laden", "errors": self.errors}
            roster, opp_roster, opp_id = self.ctx(tid)
            players = self.players
            roster_ids = {r["id"] for r in roster + opp_roster}
            pool = []
            for pos, depth in POOL_DEPTH.items():
                grp = sorted([p for p in players.values() if p["pos"] == pos], key=lambda x: -(x["proj"] or 0))
                pool += grp[:depth] + [p for p in grp[depth:] if p["id"] in roster_ids]
            mine = {r["id"]: r["slot"] for r in roster}
            theirs = {r["id"]: r["slot"] for r in opp_roster}
            out_players = {}
            for p in pool:
                q = {k: v for k, v in p.items() if k not in ("projStats", "outlook")}
                if p["id"] in mine:
                    q["mine"] = True
                    q["slot"] = mine[p["id"]]
                if p["id"] in theirs:
                    q["oppTeam"] = True
                    q["oppSlot"] = theirs[p["id"]]
                q["adv"] = self._summary(p)
                out_players[p["id"]] = q
            a = self.analytics
            defenses = [{k: d[k] for k in d if k != "defenders"} for d in a.defenses.values()] if a.ready else []
            meta = dict(self.meta, team=self.fantasy_teams.get(tid),
                        opponent=self.fantasy_teams.get(opp_id) if opp_id else None, teamId=tid)
            return {
                "status": "ok", "generated": now_iso(), "meta": meta,
                "roster": [r["id"] for r in roster], "oppRoster": [r["id"] for r in opp_roster],
                "fantasyTeams": self.fantasy_teams, "players": out_players, "keyStats": KEY_STATS,
                "analytics": {"ready": a.ready, "maxWeek": getattr(a, "max_week", None),
                              "attrMeta": a.attr_meta() if a.ready else {},
                              "league": a.league if a.ready else None, "nTeams": getattr(a, "n_teams", 32)},
                "defenses": defenses, "errors": self.errors[-3:],
            }

    def player_out(self, pid, tid):
        with self.lock:
            p = self.players.get(pid)
            if not p:
                return None
            a = self.analytics
            prof = a.profile_for_espn(pid) if a.ready else None
            out = {"espn": p, "profile": prof, "matchup": None, "defense": None,
                   "news": self.news.for_players([pid], 40)}
            if prof and p.get("opp") and not p.get("bye"):
                out["matchup"] = a.matchup(prof["gsis"], p["opp"])
            if a.ready and p.get("opp"):
                out["defense"] = a.defense_out(p["opp"])
            grp = sorted([x for x in self.players.values() if x["pos"] == p["pos"]], key=lambda x: -(x["proj"] or 0))
            i = next((k for k, x in enumerate(grp) if x["id"] == pid), 0)
            lo = max(0, i - 4)
            out["competitors"] = [{"id": x["id"], "name": x["name"], "team": x["team"], "proj": x["proj"],
                                   "avg": x["avg"], "last3": x["last3"], "opp": x["opp"], "rank": lo + k + 1,
                                   "adv": self._summary(x), "onTeamId": x["onTeamId"]}
                                  for k, x in enumerate(grp[lo: i + 5])]
            return out

    def defense_detail(self, team):
        a = self.analytics
        if not a.ready:
            return None
        d = a.defense_out(team)
        if not d:
            return None
        return {"defense": d, "league": a.league, "nTeams": a.n_teams}

    def news_out(self, tid):
        with self.lock:
            roster, opp, _ = self.ctx(tid)
        return {"mine": self.news.for_players([r["id"] for r in roster], 200),
                "opp": self.news.for_players([r["id"] for r in opp], 60),
                "latest": self.news.latest(80), "etl": self._etl_status()}

    def _etl_status(self):
        try:
            return self.news.etl_status(3)
        except Exception as e:
            return {"backend": "onbekend", "error": str(e)}

    # ------------------------------------------------------------------
    # Achtergrondlus
    # ------------------------------------------------------------------
    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _safe(self, name, fn):
        try:
            return fn()
        except AuthError as e:
            self._err(name, e)
        except Exception as e:
            self._err(name, e)
            traceback.print_exc()
        return None

    def _news_async(self):
        """Nieuws in een eigen thread (duurt even door de pauzes); nooit twee tegelijk."""
        if getattr(self, "_news_thread", None) and self._news_thread.is_alive():
            return
        self._news_thread = threading.Thread(target=lambda: self._safe("Nieuws", self.refresh_news), daemon=True)
        self._news_thread.start()

    def _loop(self):
        while not self.players:
            self._safe("ESPN", self.refresh_fantasy)
            if not self.players:
                time.sleep(30)
        iv = self.cfg.get("intervals", {})
        a_iv = iv.get("analytics_seconds", 6 * 3600)
        if not self.analytics.ready or self._analytics_age() > a_iv:
            threading.Thread(target=lambda: self._safe("Analytics", self.refresh_analytics), daemon=True).start()
        else:
            self.log(f"Analytics uit cache geladen (t/m week {self.analytics.max_week}).")
        self._safe("Live", self.refresh_live)
        self._news_async()
        t = {k: time.time() for k in ("fantasy", "news", "live")}
        t["analytics"] = time.time() - (0 if not self.analytics.ready else min(self._analytics_age(), a_iv))
        live_fast = self.any_live
        while True:
            time.sleep(5)
            now = time.time()
            if now - t["live"] >= (iv.get("live_seconds", 30) if live_fast else iv.get("idle_seconds", 300)):
                t["live"] = now
                live_fast = bool(self._safe("Live", self.refresh_live))
            if now - t["news"] >= iv.get("news_seconds", 300):
                t["news"] = now
                self._news_async()
            if now - t["fantasy"] >= iv.get("fantasy_seconds", 900):
                t["fantasy"] = now
                self._safe("ESPN", self.refresh_fantasy)
            if now - t["analytics"] >= a_iv:
                t["analytics"] = now
                threading.Thread(target=lambda: self._safe("Analytics", self.refresh_analytics), daemon=True).start()

    def force_refresh(self):
        """Handmatig verversen; max. 1x per minuut (de app is gedeeld)."""
        if time.time() - getattr(self, "_last_force", 0) < 60:
            return False
        self._last_force = time.time()

        def run():
            self._safe("ESPN", self.refresh_fantasy)
            self._safe("Live", self.refresh_live)
            self._safe("Nieuws", self.refresh_news)
        threading.Thread(target=run, daemon=True).start()
        return True
