"""
Lichtgewicht analytics-model (pure Python, geen pandas).

Het zware rekenwerk gebeurt in ffd/build_analytics.py (apart proces); dit
module laadt het resultaat en berekent scheme-matchups op verzoek.
"""
import json
import math
import os

ESPN_TO_NFLVERSE = {"LAR": "LA", "WSH": "WAS"}
NFLVERSE_TO_ESPN = {v: k for k, v in ESPN_TO_NFLVERSE.items()}
DEPTHS = ["achter", "kort", "middel", "diep"]
DEPTH_LABEL = {"achter": "achter de LOS", "kort": "kort (0-9 yds)",
               "middel": "middellang (10-19)", "diep": "diep (20+)"}
LOCS = ["left", "middle", "right"]
LOC_LABEL = {"left": "links", "middle": "midden", "right": "rechts"}
BOXES = ["licht", "normaal", "stacked"]
BOX_LABEL = {"licht": "lichte box (≤6)", "normaal": "normale box (7)",
             "stacked": "stacked box (8+)"}




def _f(x, nd=3):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, nd)


def shrink(val, n, prior, k):
    if val is None:
        return prior
    if prior is None:
        return val
    return (val * n + prior * k) / (n + k)




class MatchupModel:
    """Vereist: profiles, defenses, league, n_teams, edge_sd, espn_to_gsis."""

    # ------------------------------------------------------------------
    # Scheme-matchup
    # ------------------------------------------------------------------
    def matchup(self, gsis, opp_espn):
        prof = self.profiles.get(gsis)
        opp = ESPN_TO_NFLVERSE.get(opp_espn, opp_espn)
        D, L = self.defenses.get(opp), self.league
        if not prof or not D:
            return None
        pos = prof["pos"]
        factors = []

        def add(label, value, text, weight=1.0):
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return
            factors.append({"label": label, "value": value * weight, "text": text})

        def rel(a, b):
            return None if a is None or b is None else a - b

        def dsh(sec, key, k=60):
            """Defensewaarde gekrompen naar league-gemiddelde (kleine samples)."""
            dv, lv = D[sec][key], L[sec][key]
            return shrink(dv["epa"], dv.get("n", 0), lv["epa"], k)

        def rk(m):
            return f"rang {D['rank'][m]}/{self.n_teams}, 1 = zwaarst"

        rec, rush, pas = prof.get("rec"), prof.get("rush"), prof.get("pass")
        w_rec = w_rush = 0.0
        if rec and pos in ("WR", "TE", "RB"):
            n_t, n_r = rec["targets"], (rush or {}).get("carries", 0)
            w_rec = n_t / max(n_t + n_r, 1) if pos == "RB" else 1.0
        if rush and pos == "RB":
            w_rush = 1.0 - w_rec

        if w_rec:
            # targetdiepte
            val, best = 0.0, None
            for b in DEPTHS:
                sh = rec["depth"][b]["share"] or 0
                d = rel(dsh("depth", b), L["depth"][b]["epa"])
                if d is None:
                    continue
                val += sh * d
                if sh >= 0.15 and (best is None or abs(sh * d) > abs(best[1])):
                    best = (b, sh * d, sh, d)
            if best:
                b, _v, sh, d = best
                add("Targetdiepte", val,
                    f"{sh:.0%} van zijn targets is {DEPTH_LABEL[b]}; {D['team']} staat daar "
                    f"{abs(d):.2f} EPA/target {'meer' if d > 0 else 'minder'} toe dan gemiddeld.", w_rec * 0.7)
            # richting
            val, best = 0.0, None
            for l in LOCS:
                sh = rec["loc"][l]["share"] or 0
                d = rel(dsh("loc", l, 80), L["loc"][l]["epa"])
                if d is None:
                    continue
                val += sh * d
                if best is None or abs(sh * d) > abs(best[1]):
                    best = (l, sh * d, sh, d)
            if best:
                l, _v, sh, d = best
                add("Richting", val, f"{sh:.0%} van zijn targets gaat naar {LOC_LABEL[l]}; daar is "
                    f"{D['team']} {'kwetsbaar' if d > 0 else 'sterk'} ({d:+.2f} EPA/target t.o.v. gem.).", w_rec * 0.4)
            # positie-funnel
            vp, lp = D["vs_pos"].get(pos), L["vs_pos"].get(pos)
            d = rel(dsh("vs_pos", pos, 50) if vp else None, lp and lp["epa"])
            if d is not None:
                add(f"Vs {pos}", d, f"{D['team']} geeft {pos}'s {vp['ypt']:.1f} yards/target "
                    f"({d:+.2f} EPA t.o.v. gem.); {vp['share']:.0%} van hun toegestane targets gaat naar {pos}'s.", w_rec)
            # blitz
            bs = rec["splits"]["blitz"]
            lb = L["epa_blitz"]
            pb = shrink(bs["ja"]["epa"], bs["ja"]["n"], lb, 15)
            pn = shrink(bs["nee"]["epa"], bs["nee"]["n"], L["epa_noblitz"], 15)
            dr = rel(D["blitz_rate"], L["blitz_rate"])
            if pb is not None and pn is not None and dr is not None:
                diff = (pb - pn) - (lb - L["epa_noblitz"])
                add("Blitz", diff * dr,
                    f"{D['team']} blitzt {D['blitz_rate']:.0%} (gem. {L['blitz_rate']:.0%}); hij doet het "
                    f"{'beter' if diff > 0 else 'slechter'} dan gemiddeld tegen de blitz ({bs['ja']['n']} targets).", w_rec)
            # play-action
            ps = rec["splits"]["pa"]
            d = rel(D["epa_pa"], L["epa_pa"])
            sh = ps["ja"]["n"] / max(rec["targets"], 1)
            if d is not None and sh > 0:
                add("Play-action", sh * d, f"{sh:.0%} van zijn targets komt na play-action; {D['team']} "
                    f"verdedigt PA {'zwak' if d > 0 else 'sterk'} ({d:+.2f} EPA).", w_rec)

        if w_rush:
            d = rel(D["epa_rush"], L["epa_rush"])
            add("Run defense", d, f"{D['team']} staat {D['ypc']:.1f} yards/carry toe "
                f"({d:+.2f} EPA/carry t.o.v. gem.; {rk('epa_rush')}).", w_rush)
            val, parts = 0.0, []
            for b in BOXES:
                pe = shrink(rush["box"][b]["epa"], rush["box"][b]["n"], L["box"][b]["epa"], 20)
                df = rel(D["box"][b]["freq"], L["box"][b]["freq"])
                if pe is None or df is None or L["box"][b]["epa"] is None:
                    continue
                val += df * (pe - L["epa_rush"])
                parts.append((b, df))
            if parts:
                b, df = max(parts, key=lambda x: abs(x[1]))
                add("Boxcount", val * 2, f"{D['team']} zet {'vaker' if df > 0 else 'minder vaak'} een {BOX_LABEL[b]} "
                    f"({D['box'][b]['freq']:.0%} vs {L['box'][b]['freq']:.0%} gem.); "
                    f"zijn EPA in die situatie: {shrink(rush['box'][b]['epa'], rush['box'][b]['n'], L['box'][b]['epa'], 20):+.2f}.", w_rush)

        if pas and pos == "QB":
            d = rel(D["epa_pass"], L["epa_pass"])
            add("Pass defense", d, f"{D['team']} staat {d:+.2f} EPA/dropback toe t.o.v. gemiddeld "
                f"({rk('epa_pass')}).")
            bs = pas["splits"]["blitz"]
            pb = shrink(bs["ja"]["epa"], bs["ja"]["n"], L["epa_blitz"], 30)
            pn = shrink(bs["nee"]["epa"], bs["nee"]["n"], L["epa_noblitz"], 30)
            dr = rel(D["blitz_rate"], L["blitz_rate"])
            if None not in (pb, pn, dr):
                diff = (pb - pn) - (L["epa_blitz"] - L["epa_noblitz"])
                add("Blitz", diff * dr, f"{D['team']} blitzt {D['blitz_rate']:.0%} (gem. {L['blitz_rate']:.0%}); "
                    f"hij is {'sterk' if diff > 0 else 'kwetsbaar'} tegen de blitz ({pb:+.2f} EPA/db).")
            ds = pas["splits"]["druk"]
            pp = shrink(ds["ja"]["epa"], ds["ja"]["n"], None, 0)
            dr = rel(D["pressure_rate"], L["pressure_rate"])
            if pp is not None and dr is not None:
                add("Druk", -dr * 0.6, f"{D['team']} zet druk op {D['pressure_rate']:.0%} van de dropbacks "
                    f"(gem. {L['pressure_rate']:.0%}); zijn sackpercentage: {pas['sack_rate']:.1%}.")
            sh = pas["depth"]["diep"]["share"] or 0
            d = rel(dsh("depth", "diep"), L["depth"]["diep"]["epa"])
            if d is not None:
                add("Diepe bal", sh * d, f"{sh:.0%} van zijn passes gaat diep; {D['team']} staat diep "
                    f"{d:+.2f} EPA/target toe t.o.v. gemiddeld.")

        if not factors:
            return None
        total = sum(f["value"] for f in factors)
        score = 50 + 50 * math.tanh(total / (2 * getattr(self, "edge_sd", 0.08)))
        grade = ("A+" if score >= 80 else "A" if score >= 70 else "B" if score >= 58 else
                 "C" if score >= 42 else "D" if score >= 30 else "F")
        factors.sort(key=lambda f: -abs(f["value"]))
        for f in factors:
            f["value"] = _f(f["value"], 3)
        return {"score": round(score), "grade": grade, "total": _f(total, 3),
                "opp": D["team"], "factors": factors}

    # ------------------------------------------------------------------
    def profile_for_espn(self, espn_id):
        g = self.espn_to_gsis.get(str(int(espn_id))) if espn_id and int(espn_id) > 0 else None
        return self.profiles.get(g) if g else None

    def defense_out(self, team):
        d = self.defenses.get(ESPN_TO_NFLVERSE.get(team, team))
        return d

    def league_out(self):
        return self.league


    def attr_meta(self):
        return getattr(self, "_attr_meta", {})


class AnalyticsResult(MatchupModel):
    FIELDS = ("profiles", "defenses", "league", "n_teams", "edge_sd", "max_week",
              "espn_to_gsis", "_attr_meta", "built")

    def __init__(self, data=None):
        self.ready = False
        self.profiles, self.defenses, self.league = {}, {}, None
        self.espn_to_gsis, self._attr_meta = {}, {}
        self.n_teams, self.edge_sd, self.max_week, self.built = 32, 0.08, None, None
        if data:
            for k in self.FIELDS:
                if k in data:
                    setattr(self, k, data[k])
            self.ready = True

    @classmethod
    def load(cls, path):
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))
