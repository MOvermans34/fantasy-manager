"""
Advanced analytics op basis van nflverse play-by-play + FTN-charting.

- Spelerprofielen (ontvangers, lopers, quarterbacks) met splits:
  targetdiepte, richting, vs blitz, play-action, motion, boxcount.
- Defense-profielen: wat een defense doet (blitz, druk, box) en wat ze
  weggeeft (per diepte, richting, positie), plus coverage-stats per verdediger.
- Scheme-matchup: spelerprofiel x defense-profiel -> score + uitleg.
- Football Manager-achtige attributen (1-20) op basis van percentielen.
"""
import math

import numpy as np
import pandas as pd

from .model import BOXES, DEPTHS, LOCS, NFLVERSE_TO_ESPN, MatchupModel
def _f(x, nd=3):
    if x is None:
        return None
    try:
        if isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x)):
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def _mean(s):
    s = pd.to_numeric(pd.Series(s, dtype="float64") if isinstance(s, list) else s, errors="coerce").dropna()
    return float(s.mean()) if len(s) else None


def _rate(s):
    """Aandeel True in een bool/0-1-serie (NaN genegeerd)."""
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.mean()) if len(s) else None



class Analytics(MatchupModel):
    def __init__(self, nfl, log=print):
        self.nfl = nfl
        self.log = log
        self.ready = False
        self.error = None

    # ------------------------------------------------------------------
    def build(self):
        log = self.log
        log("Analytics: nflverse-data laden…")
        pbp = self.nfl.pbp()
        players = self.nfl.load("players", usecols=["gsis_id", "espn_id", "pfr_id", "position", "headshot"])
        snaps = self.nfl.load("snaps", usecols=["game_type", "week", "pfr_player_id", "position", "team",
                                                "offense_snaps", "offense_pct"])
        stats = self.nfl.load("stats", usecols=["player_id", "position", "week", "season_type",
                                                "opponent_team", "fantasy_points_ppr"])
        pfr = self.nfl.load("pfr_def")
        ngs_cols = {"rec": ["avg_separation", "avg_cushion", "avg_yac_above_expectation"],
                    "pass": ["avg_time_to_throw", "aggressiveness", "completion_percentage_above_expectation"],
                    "rush": ["rush_yards_over_expected_per_att", "efficiency", "percent_attempts_gte_eight_defenders"]}
        ngs = {k: self.nfl.load("ngs_" + k, usecols=lambda c, k=k: c in ngs_cols[k] + ["season", "season_type", "week", "player_gsis_id"])
               for k in ngs_cols}
        if pbp.empty:
            raise RuntimeError("Geen play-by-play-data beschikbaar")

        # --- spelers & id-koppelingen
        players = players[players["gsis_id"].notna()]
        self.pos = dict(zip(players["gsis_id"], players["position"]))
        self.espn_to_gsis = {}
        for g, e in zip(players["gsis_id"], players["espn_id"]):
            if pd.notna(e):
                self.espn_to_gsis[int(e)] = g
        pfr_to_gsis = {p: g for g, p in zip(players["gsis_id"], players["pfr_id"]) if pd.notna(p)}
        self.headshot = {g: h for g, h in zip(players["gsis_id"], players["headshot"]) if pd.notna(h)}

        # --- play-by-play opschonen
        pbp = pbp[pbp["season_type"] == "REG"]
        pbp = pbp[pbp["play_type"].isin(["pass", "run"]) & pbp["epa"].notna()].copy()
        for c, lo, hi in (("n_blitzers", 0, 11), ("n_pass_rushers", 1, 11), ("n_defense_box", 3, 11)):
            if c in pbp:
                pbp.loc[(pbp[c] < lo) | (pbp[c] > hi), c] = np.nan
            else:
                pbp[c] = np.nan
        for c in ("is_play_action", "is_motion", "is_catchable_ball", "is_contested_ball",
                  "is_drop", "is_interception_worthy", "is_throw_away", "is_qb_out_of_pocket",
                  "is_screen_pass"):
            if c not in pbp:
                pbp[c] = np.nan
            pbp[c] = pbp[c].map(lambda v: np.nan if pd.isna(v) else float(bool(v)))
        pbp["blitz"] = np.where(pbp["n_blitzers"].isna(), np.nan, (pbp["n_blitzers"] >= 1).astype(float))
        ay = pbp["air_yards"]
        pbp["depth"] = np.select([ay < 0, ay < 10, ay < 20, ay >= 20], DEPTHS, default=None)
        bx = pbp["n_defense_box"]
        pbp["box"] = np.select([bx <= 6, bx == 7, bx >= 8], BOXES, default=None)
        pbp["pressure"] = ((pbp["qb_hit"] == 1) | (pbp["sack"] == 1)).astype(float)
        pbp["rz"] = pbp["yardline_100"] <= 20
        pbp["gl"] = pbp["yardline_100"] <= 5
        is_run = pbp["play_type"] == "run"
        pbp["explosive"] = np.where(is_run, pbp["yards_gained"] >= 10, pbp["yards_gained"] >= 20).astype(float)
        pbp["rpos"] = pbp["receiver_player_id"].map(self.pos)

        self.max_week = int(pbp["week"].max())
        self.pbp = pbp
        self.dropbacks = pbp[(pbp["play_type"] == "pass") & (pbp["qb_dropback"] == 1)]
        self.targets = pbp[(pbp["play_type"] == "pass") & pbp["receiver_player_id"].notna()]
        self.rushes = pbp[is_run & pbp["rusher_player_id"].notna() & (pbp["qb_scramble"] != 1)]

        # --- snaps -> actieve weken per speler (week, team, snap%)
        self.active = {}
        snaps_all = snaps
        if not snaps.empty:
            snaps = snaps[(snaps["game_type"] == "REG") & (snaps["offense_snaps"] > 0)]
            for pid, wk, team, pct in zip(snaps["pfr_player_id"], snaps["week"],
                                          snaps["team"], snaps["offense_pct"]):
                g = pfr_to_gsis.get(pid)
                if g:
                    self.active.setdefault(g, {})[int(wk)] = (team, float(pct))

        # --- weekly PPR uit nflverse (voor consistentie & toegestane punten)
        self.stats = stats[stats["season_type"] == "REG"] if not stats.empty else stats

        # --- NGS seizoensregels (week 0 = seizoen)
        self.ngs = {}
        for k, df in ngs.items():
            if df.empty:
                self.ngs[k] = {}
                continue
            d = df[(df["season"] == self.nfl.season) & (df["season_type"] == "REG") & (df["week"] == 0)]
            self.ngs[k] = {r["player_gsis_id"]: r for r in d.to_dict("records")}

        # --- teamnoemers per week
        t = self.targets
        self.team_tgt = t.groupby(["posteam", "week"]).size().to_dict()
        self.team_air = t.groupby(["posteam", "week"])["air_yards"].sum().to_dict()
        self.team_rz_tgt = t[t["rz"]].groupby(["posteam", "week"]).size().to_dict()
        self.team_tgt_split = {}
        for col in ("blitz", "is_play_action", "is_motion"):
            for val in (0.0, 1.0):
                sub = t[t[col] == val]
                self.team_tgt_split[(col, val)] = sub.groupby(["posteam", "week"]).size().to_dict()
        r = self.rushes
        self.team_rush = r.groupby(["posteam", "week"]).size().to_dict()
        self.team_gl = r[r["gl"]].groupby(["posteam", "week"]).size().to_dict()
        self.team_rz_rush = r[r["rz"]].groupby(["posteam", "week"]).size().to_dict()

        self._by_rec = dict(tuple(t.groupby("receiver_player_id")))
        self._by_rush = dict(tuple(r.groupby("rusher_player_id")))
        self._by_pass = dict(tuple(self.dropbacks.groupby("passer_player_id")))

        log("Analytics: league-baselines en defenses berekenen…")
        self.league = self._league_baseline()
        self.defenses = {team: self._defense(team, df)
                         for team, df in pbp.groupby("defteam")}
        self._defenders(pfr, snaps_all)
        self._fp_allowed()
        self._rank_defenses()

        log("Analytics: spelerprofielen en attributen…")
        self.profiles = {}
        self._build_all_profiles()
        self._attributes()
        self._calibrate()
        self.ready = True
        log(f"Analytics klaar (t/m week {self.max_week}, {len(self.profiles)} spelers).")

    # ------------------------------------------------------------------
    # League & defense
    # ------------------------------------------------------------------
    def _split_profile(self, t, rush, db):
        """Gedeelde berekeningen voor league- en defense-niveau."""
        out = {
            "plays": int(len(t) + len(rush)),
            "epa_pass": _mean(db["epa"]), "succ_pass": _rate(db["success"]),
            "epa_rush": _mean(rush["epa"]), "succ_rush": _rate(rush["success"]),
            "ypc": _mean(rush["yards_gained"]),
            "expl_pass": _rate(db["explosive"]), "expl_rush": _rate(rush["explosive"]),
            "blitz_rate": _rate(db["blitz"]), "rushers": _mean(db["n_pass_rushers"]),
            "pressure_rate": _rate(db["pressure"]), "sack_rate": _rate(db["sack"]),
            "box_avg": _mean(rush["n_defense_box"]),
            "pa_rate": _rate(db["is_play_action"]),
            "epa_pa": _mean(db[db["is_play_action"] == 1]["epa"]),
            "epa_nopa": _mean(db[db["is_play_action"] == 0]["epa"]),
            "epa_blitz": _mean(db[db["blitz"] == 1]["epa"]),
            "epa_noblitz": _mean(db[db["blitz"] == 0]["epa"]),
            "cpoe": _mean(db["cpoe"]),
            "adot": _mean(t["air_yards"]),
        }
        n_t = max(len(t), 1)
        out["depth"] = {b: {"share": len(t[t["depth"] == b]) / n_t, "n": int((t["depth"] == b).sum()),
                            "epa": _mean(t[t["depth"] == b]["epa"]),
                            "ypt": _mean(t[t["depth"] == b]["yards_gained"])} for b in DEPTHS}
        out["loc"] = {l: {"share": len(t[t["pass_location"] == l]) / n_t, "n": int((t["pass_location"] == l).sum()),
                          "epa": _mean(t[t["pass_location"] == l]["epa"])} for l in LOCS}
        out["vs_pos"] = {}
        for p in ("WR", "TE", "RB"):
            s = t[t["rpos"] == p]
            out["vs_pos"][p] = {"share": len(s) / n_t, "n": int(len(s)), "epa": _mean(s["epa"]),
                                "ypt": _mean(s["yards_gained"]), "catch": _rate(s["complete_pass"])}
        n_r = max(len(rush.dropna(subset=["box"])), 1)
        out["box"] = {b: {"freq": len(rush[rush["box"] == b]) / n_r, "n": int((rush["box"] == b).sum()),
                          "ypc": _mean(rush[rush["box"] == b]["yards_gained"]),
                          "epa": _mean(rush[rush["box"] == b]["epa"])} for b in BOXES}
        return out

    def _league_baseline(self):
        return self._split_profile(self.targets, self.rushes, self.dropbacks)

    def _defense(self, team, df):
        t = df[(df["play_type"] == "pass") & df["receiver_player_id"].notna()]
        db = df[(df["play_type"] == "pass") & (df["qb_dropback"] == 1)]
        rush = df[(df["play_type"] == "run") & df["rusher_player_id"].notna() & (df["qb_scramble"] != 1)]
        d = self._split_profile(t, rush, db)
        d["team"] = NFLVERSE_TO_ESPN.get(team, team)
        d["games"] = int(df["game_id"].nunique())
        return d

    def _defenders(self, pfr, snaps):
        """Coverage-stats per verdediger (PFR advanced stats)."""
        for d in self.defenses.values():
            d["defenders"] = []
        if pfr.empty:
            return
        pfr = pfr[pfr["game_type"] == "REG"].copy()
        pos = {}
        if not snaps.empty and "position" in snaps:
            pos = dict(zip(snaps["pfr_player_id"], snaps["position"]))
        num = ["def_targets", "def_completions_allowed", "def_yards_allowed",
               "def_receiving_td_allowed", "def_ints", "def_air_yards_completed",
               "def_yards_after_catch", "def_missed_tackles", "def_tackles_combined",
               "def_times_blitzed", "def_pressures", "def_sacks"]
        for c in num:
            pfr[c] = pd.to_numeric(pfr[c], errors="coerce").fillna(0)
        pfr["rating_x_tgt"] = pd.to_numeric(pfr["def_passer_rating_allowed"], errors="coerce").fillna(0) * pfr["def_targets"]
        last_team = pfr.sort_values("week").groupby("pfr_player_id")["team"].last()
        agg = pfr.groupby("pfr_player_id").agg(
            name=("pfr_player_name", "last"), games=("game_id", "nunique"),
            **{c: (c, "sum") for c in num + ["rating_x_tgt"]})
        agg["team"] = last_team
        for pid, r in agg.iterrows():
            team = r["team"]
            if team not in self.defenses or r["def_targets"] < 5:
                continue
            tg = r["def_targets"]
            self.defenses[team]["defenders"].append({
                "name": r["name"], "pos": pos.get(pid, ""), "games": int(r["games"]),
                "targets": int(tg), "cmp": int(r["def_completions_allowed"]),
                "cmp_pct": _f(r["def_completions_allowed"] / tg, 3),
                "yds": int(r["def_yards_allowed"]), "ypt": _f(r["def_yards_allowed"] / tg, 1),
                "td": int(r["def_receiving_td_allowed"]), "int": int(r["def_ints"]),
                "rating": _f(r["rating_x_tgt"] / tg, 1),
                "tgt_pg": _f(tg / max(r["games"], 1), 1),
                "missed_tkl_pct": _f(r["def_missed_tackles"] / max(r["def_missed_tackles"] + r["def_tackles_combined"], 1), 3),
                "pressures": int(r["def_pressures"]),
            })
        for d in self.defenses.values():
            d["defenders"].sort(key=lambda x: -x["targets"])
            d["defenders"] = d["defenders"][:10]

    def _fp_allowed(self):
        s = self.stats
        for d in self.defenses.values():
            d["fp_allowed"] = {}
        self.league["fp_allowed"] = {}
        if s.empty:
            return
        s = s[s["position"].isin(["QB", "RB", "WR", "TE"])]
        g = s.groupby(["opponent_team", "position", "week"])["fantasy_points_ppr"].sum().reset_index()
        per = g.groupby(["opponent_team", "position"])["fantasy_points_ppr"].mean()
        for (team, p), v in per.items():
            if team in self.defenses:
                self.defenses[team]["fp_allowed"][p] = _f(v, 1)
        for p in ("QB", "RB", "WR", "TE"):
            vals = [d["fp_allowed"].get(p) for d in self.defenses.values() if d["fp_allowed"].get(p) is not None]
            self.league["fp_allowed"][p] = _f(sum(vals) / len(vals), 1) if vals else None

    def _rank_defenses(self):
        """Rang 1 = moeilijkst voor de aanval."""
        teams = list(self.defenses)
        spec = {  # metric -> hoger is beter voor de defense?
            "epa_pass": False, "epa_rush": False, "succ_pass": False, "succ_rush": False,
            "pressure_rate": True, "blitz_rate": True, "expl_pass": False, "expl_rush": False,
            "ypc": False, "sack_rate": True,
        }
        for m, higher_better in spec.items():
            vals = sorted(teams, key=lambda t: (self.defenses[t][m] if self.defenses[t][m] is not None else 0),
                          reverse=higher_better)
            for i, t in enumerate(vals):
                self.defenses[t].setdefault("rank", {})[m] = i + 1
        for p in ("QB", "RB", "WR", "TE"):
            vals = sorted(teams, key=lambda t: self.defenses[t]["fp_allowed"].get(p) or 0)
            for i, t in enumerate(vals):
                self.defenses[t]["rank"]["fp_" + p] = i + 1
        for b in ("diep",):
            vals = sorted(teams, key=lambda t: self.defenses[t]["depth"][b]["epa"] or 0)
            for i, t in enumerate(vals):
                self.defenses[t]["rank"]["epa_" + b] = i + 1
        self.n_teams = len(teams)

    # ------------------------------------------------------------------
    # Spelers
    # ------------------------------------------------------------------
    def _active(self, gsis, frames):
        act = dict(self.active.get(gsis, {}))
        for df in frames:
            if df is None:
                continue
            for wk, team in zip(df["week"], df["posteam"]):
                act.setdefault(int(wk), (team, None))
        return act

    @staticmethod
    def _denom(table, act):
        return sum(table.get((team, wk), 0) for wk, (team, _p) in act.items())

    def _receiving(self, g, t, act):
        n = len(t)
        team_t = self._denom(self.team_tgt, act)
        team_air = self._denom(self.team_air, act)
        rec = t[t["complete_pass"] == 1]
        catchable = t[t["is_catchable_ball"] == 1]
        out = {
            "targets": n, "rec": int(len(rec)), "yds": int(t["yards_gained"].sum()),
            "td": int(t["touchdown"].sum()),
            "tshare": n / team_t if team_t else None,
            "air_share": t["air_yards"].sum() / team_air if team_air else None,
            "adot": _mean(t["air_yards"]), "epa_tgt": _mean(t["epa"]),
            "succ": _rate(t["success"]), "ypt": _mean(t["yards_gained"]),
            "catch_rate": len(rec) / n if n else None,
            "catchable_rate": _rate(t["is_catchable_ball"]),
            "catch_on_catchable": (len(catchable[catchable["complete_pass"] == 1]) / len(catchable)) if len(catchable) else None,
            "drops": int(t["is_drop"].fillna(0).sum()),
            "contested_rate": _rate(t["is_contested_ball"]),
            "yac_pr": _mean(rec["yards_after_catch"]),
            "yacoe": _mean(rec["yards_after_catch"] - rec["xyac_mean_yardage"]),
            "deep_share": len(t[t["depth"] == "diep"]) / n if n else None,
            "rz_tgt": int(t["rz"].sum()),
            "rz_share": (t["rz"].sum() / self._denom(self.team_rz_tgt, act)) if self._denom(self.team_rz_tgt, act) else None,
            "ez_tgt": int((t["air_yards"] >= t["yardline_100"]).sum()),
            "expl_rate": _rate(t["explosive"]),
        }
        if out["tshare"] is not None and out["air_share"] is not None:
            out["wopr"] = 1.5 * out["tshare"] + 0.7 * out["air_share"]
        out["depth"] = {b: {"n": int((t["depth"] == b).sum()),
                            "share": (t["depth"] == b).sum() / n if n else None,
                            "epa": _mean(t[t["depth"] == b]["epa"]),
                            "ypt": _mean(t[t["depth"] == b]["yards_gained"])} for b in DEPTHS}
        out["loc"] = {l: {"n": int((t["pass_location"] == l).sum()),
                          "share": (t["pass_location"] == l).sum() / n if n else None,
                          "epa": _mean(t[t["pass_location"] == l]["epa"])} for l in LOCS}
        out["splits"] = {}
        for col, key in (("blitz", "blitz"), ("is_play_action", "pa"), ("is_motion", "motion")):
            sp = {}
            for val, lab in ((1.0, "ja"), (0.0, "nee")):
                s = t[t[col] == val]
                den = self._denom(self.team_tgt_split[(col, val)], act)
                sp[lab] = {"n": int(len(s)), "tshare": len(s) / den if den else None,
                           "epa": _mean(s["epa"]), "ypt": _mean(s["yards_gained"]),
                           "catch": _rate(s["complete_pass"])}
            out["splits"][key] = sp
        ngs = self.ngs.get("rec", {}).get(g)
        if ngs:
            out["separation"] = _f(ngs.get("avg_separation"), 2)
            out["cushion"] = _f(ngs.get("avg_cushion"), 2)
            out["ngs_yacoe"] = _f(ngs.get("avg_yac_above_expectation"), 2)
        return out

    def _rushing(self, g, r, act):
        n = len(r)
        team_r = self._denom(self.team_rush, act)
        team_gl = self._denom(self.team_gl, act)
        team_rz = self._denom(self.team_rz_rush, act)
        out = {
            "carries": n, "yds": int(r["yards_gained"].sum()), "td": int(r["touchdown"].sum()),
            "ypc": _mean(r["yards_gained"]), "epa_rush": _mean(r["epa"]), "succ": _rate(r["success"]),
            "rush_share": n / team_r if team_r else None, "expl_rate": _rate(r["explosive"]),
            "rz_att": int(r["rz"].sum()), "rz_share": r["rz"].sum() / team_rz if team_rz else None,
            "gl_att": int(r["gl"].sum()), "gl_share": r["gl"].sum() / team_gl if team_gl else None,
        }
        nb = max(len(r.dropna(subset=["box"])), 1)
        out["box"] = {b: {"n": int((r["box"] == b).sum()), "freq": (r["box"] == b).sum() / nb,
                          "ypc": _mean(r[r["box"] == b]["yards_gained"]),
                          "epa": _mean(r[r["box"] == b]["epa"])} for b in BOXES}
        ngs = self.ngs.get("rush", {}).get(g)
        if ngs:
            out["ryoe_att"] = _f(ngs.get("rush_yards_over_expected_per_att"), 2)
            out["efficiency"] = _f(ngs.get("efficiency"), 2)
            out["pct_8box"] = _f(ngs.get("percent_attempts_gte_eight_defenders"), 1)
        return out

    def _passing(self, g, db):
        att = db[db["pass_attempt"] == 1]
        n = len(db)
        out = {
            "dropbacks": n, "att": int((att["sack"] != 1).sum()),
            "cmp_pct": _rate(att[att["sack"] != 1]["complete_pass"]),
            "yds": int(att[att["sack"] != 1]["yards_gained"].sum()),
            "td": int(att["touchdown"].sum() - 0), "int": int(db["interception"].fillna(0).sum()),
            "epa_db": _mean(db["epa"]), "succ": _rate(db["success"]), "cpoe": _mean(db["cpoe"]),
            "adot": _mean(att["air_yards"]), "deep_rate": _rate(att["depth"].dropna() == "diep"),
            "sack_rate": _rate(db["sack"]), "pressure_rate": _rate(db["pressure"]),
            "int_worthy_rate": _rate(db["is_interception_worthy"]),
            "throwaway_rate": _rate(db["is_throw_away"]),
            "oop_rate": _rate(db["is_qb_out_of_pocket"]),
        }
        out["splits"] = {}
        for col, key in (("blitz", "blitz"), ("is_play_action", "pa"), ("pressure", "druk"),
                         ("is_qb_out_of_pocket", "buiten_pocket")):
            sp = {}
            for val, lab in ((1.0, "ja"), (0.0, "nee")):
                s = db[db[col] == val]
                a = s[(s["pass_attempt"] == 1) & (s["sack"] != 1)]
                sp[lab] = {"n": int(len(s)), "epa": _mean(s["epa"]), "cmp": _rate(a["complete_pass"]),
                           "ypa": _mean(a["yards_gained"]), "sack": _rate(s["sack"])}
            out["splits"][key] = sp
        out["depth"] = {b: {"n": int((att["depth"] == b).sum()),
                            "share": _rate(att["depth"].dropna() == b),
                            "epa": _mean(att[att["depth"] == b]["epa"])} for b in DEPTHS}
        ngs = self.ngs.get("pass", {}).get(g)
        if ngs:
            out["ttt"] = _f(ngs.get("avg_time_to_throw"), 2)
            out["aggressiveness"] = _f(ngs.get("aggressiveness"), 1)
            out["cpoe_ngs"] = _f(ngs.get("completion_percentage_above_expectation"), 1)
        return out

    def _weekly_ppr(self, g):
        s = self.stats
        if s.empty:
            return []
        d = s[s["player_id"] == g]
        return [{"wk": int(w), "ppr": _f(p, 1), "opp": NFLVERSE_TO_ESPN.get(o, o)}
                for w, p, o in zip(d["week"], d["fantasy_points_ppr"], d["opponent_team"])]

    def _build_all_profiles(self):
        ids = set(self._by_rec) | set(self._by_rush) | set(self._by_pass)
        for g in ids:
            pos = self.pos.get(g)
            if pos not in ("QB", "RB", "WR", "TE"):
                continue
            t, r, db = self._by_rec.get(g), self._by_rush.get(g), self._by_pass.get(g)
            act = self._active(g, [t, r, db])
            prof = {"gsis": g, "pos": pos, "games": len(act),
                    "snap_pct": _mean([p for _t, p in act.values() if p is not None]),
                    "snap_last3": _mean([act[w][1] for w in sorted(act)[-3:] if act[w][1] is not None]),
                    "snaps_wk": {int(w): _f(p, 2) for w, (_t, p) in act.items() if p is not None},
                    "headshot": self.headshot.get(g)}
            if t is not None and len(t):
                prof["rec"] = self._receiving(g, t, act)
            if r is not None and len(r):
                prof["rush"] = self._rushing(g, r, act)
            if db is not None and len(db) >= 20:
                prof["pass"] = self._passing(g, db)
            wk = self._weekly_ppr(g)
            prof["weekly_ppr"] = wk
            pts = [w["ppr"] for w in wk if w["ppr"] is not None]
            if len(pts) >= 3 and np.mean(pts) > 0:
                prof["cv"] = float(np.std(pts) / np.mean(pts))
            if pts:
                prof["ppr_pg"] = float(np.mean(pts))
            self.profiles[g] = prof

    # ------------------------------------------------------------------
    # Attributen (1-20, percentielen binnen de positie)
    # ------------------------------------------------------------------
    ATTRS = {
        "WR": [
            ("Volume", lambda p: p["rec"].get("tshare"), "Aandeel van de team-targets"),
            ("Air yards", lambda p: p["rec"].get("air_share"), "Aandeel van de team-air yards"),
            ("Diepte", lambda p: p["rec"].get("adot"), "Gemiddelde targetdiepte (aDOT)"),
            ("Separatie", lambda p: p["rec"].get("separation"), "NGS: gem. ruimte tot verdediger bij de catch/incompletie"),
            ("Vangzekerheid", lambda p: p["rec"].get("catch_on_catchable"), "Vangpercentage op vangbare ballen (FTN)"),
            ("Na de vangst", lambda p: p["rec"].get("yacoe"), "Yards na de catch boven verwachting (xYAC)"),
            ("Efficiëntie", lambda p: p["rec"].get("epa_tgt"), "EPA per target"),
            ("Explosiviteit", lambda p: p["rec"].get("expl_rate"), "Aandeel targets met 20+ yards"),
            ("Red zone", lambda p: p["rec"].get("rz_share"), "Aandeel van de team-targets in de red zone"),
            ("Vs blitz", lambda p: (p["rec"]["splits"]["blitz"]["ja"].get("epa")), "EPA per target als de defense blitzt"),
            ("Snaps", lambda p: p.get("snap_pct"), "Gemiddeld snap-percentage"),
            ("Consistentie", lambda p: -p["cv"] if p.get("cv") is not None else None, "Spreiding van wekelijkse punten (laag = stabiel)"),
        ],
        "RB": [
            ("Werklast", lambda p: p["rush"].get("rush_share"), "Aandeel van de team-carries"),
            ("Snaps", lambda p: p.get("snap_pct"), "Gemiddeld snap-percentage"),
            ("Efficiëntie", lambda p: p["rush"].get("epa_rush"), "EPA per carry"),
            ("Succes", lambda p: p["rush"].get("succ"), "Succespercentage per carry"),
            ("Boven verwachting", lambda p: p["rush"].get("ryoe_att"), "NGS: rushing yards boven verwachting per carry"),
            ("Explosiviteit", lambda p: p["rush"].get("expl_rate"), "Aandeel carries met 10+ yards"),
            ("Vs stacked box", lambda p: p["rush"]["box"]["stacked"].get("epa"), "EPA per carry tegen 8+ man in de box"),
            ("Goal line", lambda p: p["rush"].get("gl_share"), "Aandeel van de team-carries binnen de 5"),
            ("Receiving", lambda p: (p.get("rec") or {}).get("tshare"), "Aandeel van de team-targets"),
            ("Na de vangst", lambda p: (p.get("rec") or {}).get("yac_pr"), "Yards na de catch per receptie"),
            ("Consistentie", lambda p: -p["cv"] if p.get("cv") is not None else None, "Spreiding van wekelijkse punten"),
        ],
        "QB": [
            ("Efficiëntie", lambda p: p["pass"].get("epa_db"), "EPA per dropback"),
            ("Precisie", lambda p: p["pass"].get("cpoe"), "Completion % boven verwachting (CPOE)"),
            ("Diepe bal", lambda p: p["pass"]["depth"]["diep"].get("epa"), "EPA op passes van 20+ yards"),
            ("Agressiviteit", lambda p: p["pass"].get("deep_rate"), "Aandeel diepe passes"),
            ("Pocket", lambda p: -p["pass"]["sack_rate"] if p["pass"].get("sack_rate") is not None else None, "Sackpercentage (laag = beter)"),
            ("Vs blitz", lambda p: p["pass"]["splits"]["blitz"]["ja"].get("epa"), "EPA per dropback tegen de blitz"),
            ("Onder druk", lambda p: p["pass"]["splits"]["druk"]["ja"].get("epa"), "EPA per dropback onder druk"),
            ("Beslissingen", lambda p: -p["pass"]["int_worthy_rate"] if p["pass"].get("int_worthy_rate") is not None else None, "Interception-worthy throws (laag = beter)"),
            ("Play-action", lambda p: p["pass"]["splits"]["pa"]["ja"].get("epa"), "EPA per dropback met play-action"),
            ("Mobiliteit", lambda p: ((p.get("rush") or {}).get("yds", 0) / max(p.get("games") or 1, 1)), "Rushing yards per wedstrijd (designed runs)"),
            ("Consistentie", lambda p: -p["cv"] if p.get("cv") is not None else None, "Spreiding van wekelijkse punten"),
        ],
    }
    ATTRS["TE"] = ATTRS["WR"]
    MIN_VOL = {"WR": ("rec", "targets", 15), "TE": ("rec", "targets", 12),
               "RB": ("rush", "carries", 25), "QB": ("pass", "dropbacks", 80)}

    def _attributes(self):
        for pos, attrs in self.ATTRS.items():
            sec, key, mn = self.MIN_VOL[pos]
            group = [p for p in self.profiles.values() if p["pos"] == pos and sec in p]
            qualified = [p for p in group if p[sec].get(key, 0) >= mn]
            for name, fn, _desc in attrs:
                vals = []
                for p in qualified:
                    try:
                        v = fn(p)
                    except (KeyError, TypeError):
                        v = None
                    if v is not None and not (isinstance(v, float) and math.isnan(v)):
                        vals.append(v)
                vals.sort()
                for p in group:
                    try:
                        v = fn(p)
                    except (KeyError, TypeError):
                        v = None
                    if v is None or (isinstance(v, float) and math.isnan(v)) or not vals:
                        score = None
                    else:
                        pct = np.searchsorted(vals, v, side="right") / len(vals)
                        score = int(max(1, min(20, round(1 + pct * 19))))
                    p.setdefault("attrs", []).append({"name": name, "score": score, "raw": _f(v, 3)})
            for p in group:
                sc = [a["score"] for a in p["attrs"] if a["score"] is not None]
                p["overall"] = _f(np.mean(sc), 1) if sc else None
                p["low_sample"] = p[sec].get(key, 0) < mn

    def _calibrate(self):
        """Spreiding van matchup-totalen -> schaal voor de 0-100 score."""
        self.edge_sd = 0.08
        totals = []
        for g, p in self.profiles.items():
            if (p.get("ppr_pg") or 0) < 8:
                continue
            for t in self.defenses:
                m = self.matchup(g, NFLVERSE_TO_ESPN.get(t, t))
                if m:
                    totals.append(m["total"])
        if len(totals) > 50:
            self.edge_sd = float(np.std(totals)) or 0.08

    def export(self):
        """Compact, JSON-serialiseerbaar resultaat voor de server."""
        import datetime as _dt
        used = {g for g in self.profiles}
        return {
            "profiles": self.profiles, "defenses": self.defenses, "league": self.league,
            "n_teams": self.n_teams, "edge_sd": self.edge_sd, "max_week": self.max_week,
            "espn_to_gsis": {str(e): g for e, g in self.espn_to_gsis.items() if g in used},
            "_attr_meta": {pos: [{"name": n, "desc": d} for n, _f2, d in a] for pos, a in self.ATTRS.items()},
            "built": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        }
