"""ESPN Fantasy (onofficiële API): league, selecties, projecties, live scores."""
import json
import urllib.error
import urllib.request

API = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?week={week}&seasontype=2&dates={season}"
NEWS = "https://site.api.espn.com/apis/fantasy/v2/games/ffl/news/players?limit={limit}&playerId={pid}"

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
POS_SLOT = {"QB": 0, "RB": 2, "WR": 4, "TE": 6, "K": 17, "D/ST": 16}
SLOT = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K",
        20: "Bank", 21: "IR", 23: "FLEX"}
BENCH = {20, 21}

KEY_STATS = {
    "QB": [("3", "Pass yds"), ("4", "Pass TD"), ("20", "INT"), ("24", "Rush yds"), ("25", "Rush TD")],
    "RB": [("23", "Carries"), ("24", "Rush yds"), ("25", "Rush TD"), ("58", "Targets"), ("53", "Rec"), ("42", "Rec yds")],
    "WR": [("58", "Targets"), ("53", "Rec"), ("42", "Rec yds"), ("43", "Rec TD"), ("24", "Rush yds")],
    "TE": [("58", "Targets"), ("53", "Rec"), ("42", "Rec yds"), ("43", "Rec TD")],
    "K": [("83", "FG"), ("84", "FG pog."), ("74", "FG 50+"), ("86", "XP")],
    "D/ST": [("99", "Sacks"), ("95", "INT"), ("96", "Fum. rec"), ("120", "Ptn tegen"), ("127", "Yds tegen")],
}
# Live-statregel per positie
LIVE_STATS = {
    "QB": [("1", "cmp"), ("0", "att"), ("3", "yds"), ("4", "TD"), ("20", "INT"), ("24", "rush yds")],
    "RB": [("23", "car"), ("24", "yds"), ("25", "TD"), ("53", "rec"), ("42", "rec yds")],
    "WR": [("53", "rec"), ("58", "tgt"), ("42", "yds"), ("43", "TD")],
    "TE": [("53", "rec"), ("58", "tgt"), ("42", "yds"), ("43", "TD")],
    "K": [("83", "FG"), ("86", "XP")],
    "D/ST": [("99", "sacks"), ("95", "INT"), ("120", "ptn tegen")],
}


class AuthError(Exception):
    pass


class Espn:
    def __init__(self, season, espn_s2=None, swid=None):
        self.season = season
        self.base = API.format(season=season)
        self.cookie = f"espn_s2={espn_s2}; SWID={swid}" if espn_s2 and swid else None

    def get(self, url, fantasy_filter=None, auth=True, timeout=60):
        headers = {"User-Agent": "ff-dashboard/2.0", "Accept": "application/json"}
        if fantasy_filter is not None:
            headers["x-fantasy-filter"] = json.dumps(fantasy_filter)
        if auth and self.cookie:
            headers["Cookie"] = self.cookie
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise AuthError("ESPN weigert toegang (401): controleer espn_s2 en swid in config.json")
            raise

    # ------------------------------------------------------------------
    def current_week(self):
        return self.get(self.base, auth=False)["currentScoringPeriod"]["id"]

    def pro_teams(self):
        data = self.get(self.base + "?view=proTeamSchedules_wl", auth=False)
        teams = {}
        for t in data["settings"]["proTeams"]:
            games = {}
            for wk, gl in (t.get("proGamesByScoringPeriod") or {}).items():
                g = gl[0]
                home = g["homeProTeamId"] == t["id"]
                games[int(wk)] = {"opp": g["awayProTeamId"] if home else g["homeProTeamId"],
                                  "home": home, "date": g["date"], "gameId": g["id"]}
            teams[t["id"]] = {"abbrev": t["abbrev"], "name": f'{t["location"]} {t["name"]}'.strip(),
                              "bye": t.get("byeWeek"), "games": games}
        return teams

    def league(self, league_id, week):
        url = (f"{self.base}/segments/0/leagues/{league_id}"
               f"?view=mTeam&view=mRoster&view=mSettings&view=mMatchup&scoringPeriodId={week}")
        return self.get(url)

    def _filter(self, slot_ids=None, limit=None, ids=None):
        # Het league-endpoint stuurt weekpunten en weekprojecties alleen mee als je
        # ze expliciet opvraagt: top-18 speelrondes (gescoorde punten per week) plus
        # seizoenstotalen en de projectie per week ("11{seizoen}{week}").
        y = self.season
        f = {"filterStatsForTopScoringPeriodIds": {
            "value": 18,
            "additionalValue": [f"00{y}", f"10{y}", f"00{y - 1}", f"10{y - 1}"]
                               + [f"11{y}{w}" for w in range(1, 19)],
        }}
        if ids is not None:
            f["filterIds"] = {"value": ids}
        if slot_ids is not None:
            f["filterSlotIds"] = {"value": slot_ids}
        if limit:
            f["limit"] = limit
            f["sortPercOwned"] = {"sortAsc": False, "sortPriority": 1}
        return {"players": f}

    def players_url(self, league_id):
        if league_id:
            return f"{self.base}/segments/0/leagues/{league_id}"
        return f"{self.base}/segments/0/leaguedefaults/3"

    def players(self, league_id, week, ids=(), limit=500):
        u = f"{self.players_url(league_id)}?view=kona_player_info&scoringPeriodId={week}"
        pool = self.get(u, self._filter(list(POS_SLOT.values()), limit))["players"]
        have = {p["id"] for p in pool}
        missing = [i for i in ids if i not in have]
        if missing:
            pool += self.get(u, self._filter(ids=missing))["players"]
        return pool

    def players_by_id(self, league_id, week, ids):
        u = f"{self.players_url(league_id)}?view=kona_player_info&scoringPeriodId={week}"
        return self.get(u, self._filter(ids=list(ids)), timeout=30)["players"]

    def scoreboard(self, week):
        return self.get(SCOREBOARD.format(week=week, season=self.season), auth=False, timeout=20)

    def news(self, pid, limit=8):
        if pid < 0:
            return []
        data = self.get(NEWS.format(limit=limit, pid=pid), auth=False, timeout=20)
        out = []
        for a in data.get("feed", []):
            link = ((a.get("links") or {}).get("web") or {}).get("href")
            typ = a.get("type")
            out.append({"id": "espn-" + str(a.get("id")),
                        "source": "Rotowire" if typ == "Rotowire" else "ESPN",
                        "via": "ESPN" if typ == "Rotowire" else None,
                        "kind": {"Rotowire": "Update", "Story": "Analyse", "Media": "Video",
                                 "HeadlineNews": "Nieuws"}.get(typ, typ),
                        "author": a.get("byline"),
                        "headline": a.get("headline", ""), "description": a.get("description", ""),
                        "published": a.get("published"), "type": typ, "link": link})
        return out


# ----------------------------------------------------------------------
# Spelers verwerken
# ----------------------------------------------------------------------
def r1(x):
    return None if x is None else round(x, 1)


def stat_index(player, season):
    idx = {}
    for s in player.get("stats", []):
        if s.get("seasonId") == season:
            idx[(s["scoringPeriodId"], s["statSourceId"], s["statSplitTypeId"])] = s
    return idx


def build_player(entry, season, week, pro):
    p = entry["player"]
    pos = POS.get(p.get("defaultPositionId"))
    st = stat_index(p, season)
    team = pro.get(p.get("proTeamId"), {})
    season_act = st.get((0, 0, 0), {})
    weekly = []
    for wk in range(1, week):
        s = st.get((wk, 0, 1))
        pj = st.get((wk, 1, 1))
        g = team.get("games", {}).get(wk)
        weekly.append({"wk": wk, "pts": r1(s["appliedTotal"]) if s else None,
                       "proj": r1(pj["appliedTotal"]) if pj else None,
                       "bye": team.get("bye") == wk,
                       "opp": pro.get(g["opp"], {}).get("abbrev") if g else None})
    played = [w["pts"] for w in weekly if w["pts"] is not None]
    last3 = played[-3:]
    proj = st.get((week, 1, 1))
    live = st.get((week, 0, 1))
    game = team.get("games", {}).get(week)
    raw = season_act.get("stats", {})
    by_week = (p.get("outlooks") or {}).get("outlooksByWeek") or {}
    ow = max((int(k) for k in by_week if k.isdigit() and int(k) <= week), default=None)
    own = p.get("ownership") or {}
    return {
        "id": p["id"], "name": p.get("fullName"), "pos": pos,
        "proTeamId": p.get("proTeamId"), "team": team.get("abbrev", "FA"),
        "injury": p.get("injuryStatus") or ("ACTIVE" if not p.get("injured") else "INJURED"),
        "onTeamId": entry.get("onTeamId", 0), "status": entry.get("status"),
        "owned": r1(own.get("percentOwned")), "ownedChange": r1(own.get("percentChange")),
        "proj": r1(proj["appliedTotal"]) if proj else None,
        "projStats": {sid: r1(proj["stats"][sid]) for sid, _ in KEY_STATS.get(pos, [])
                      if proj and sid in proj.get("stats", {})},
        "livePts": r1(live["appliedTotal"]) if live else None,
        "total": r1(season_act.get("appliedTotal")),
        "avg": r1(sum(played) / len(played)) if played else None,
        "last3": r1(sum(last3) / len(last3)) if last3 else None,
        "games": len(played), "ros": r1((st.get((0, 1, 0)) or {}).get("appliedTotal")),
        "weekly": weekly,
        "key": {sid: r1(raw[sid]) for sid, _ in KEY_STATS.get(pos, []) if sid in raw},
        "outlook": by_week.get(str(ow)) if ow else None, "outlookWeek": ow,
        "bye": team.get("bye") == week,
        "opp": pro.get(game["opp"], {}).get("abbrev") if game else None,
        "oppId": game["opp"] if game else None,
        "home": game["home"] if game else None,
        "kickoff": game["date"] if game else None,
        "gameId": game["gameId"] if game else None,
        "lastNews": p.get("lastNewsDate"),
    }


def live_line(entry, season, week):
    """Live punten + statregel voor één speler."""
    p = entry["player"]
    pos = POS.get(p.get("defaultPositionId"))
    st = stat_index(p, season)
    live = st.get((week, 0, 1))
    proj = st.get((week, 1, 1))
    stats = (live or {}).get("stats", {})
    line = []
    for sid, lab in LIVE_STATS.get(pos, []):
        if sid in stats and stats[sid]:
            v = stats[sid]
            line.append(f"{int(v) if float(v).is_integer() else round(v, 1)} {lab}")
    return {"id": p["id"], "pts": r1(live["appliedTotal"]) if live else 0.0,
            "proj": r1(proj["appliedTotal"]) if proj else None,
            "line": ", ".join(line), "injury": p.get("injuryStatus")}


def parse_scoreboard(sb):
    """ESPN NFL-scoreboard -> per team abbrev de wedstrijdstatus."""
    games = {}
    for ev in sb.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        st = comp.get("status") or ev.get("status") or {}
        stype = st.get("type", {})
        teams = comp.get("competitors", [])
        sit = comp.get("situation") or {}
        poss = sit.get("possession")
        info = {
            "id": ev.get("id"), "state": stype.get("state"),  # pre / in / post
            "detail": stype.get("shortDetail"), "period": st.get("period"),
            "clock": st.get("displayClock"), "date": ev.get("date"),
            "teams": [], "redzone": sit.get("isRedZone"), "downDistance": sit.get("shortDownDistanceText"),
            "lastPlay": (sit.get("lastPlay") or {}).get("text"),
        }
        for c in teams:
            t = c.get("team", {})
            info["teams"].append({"abbrev": t.get("abbreviation"), "score": c.get("score"),
                                  "home": c.get("homeAway") == "home",
                                  "possession": poss is not None and poss == t.get("id")})
        # fractie gespeeld (0..1)
        if info["state"] == "post":
            frac = 1.0
        elif info["state"] == "in":
            per = min(info["period"] or 1, 4)
            try:
                m, s = (info["clock"] or "15:00").split(":")
                left = int(m) * 60 + int(s)
            except ValueError:
                left = 900
            frac = min(1.0, ((per - 1) * 900 + (900 - left)) / 3600)
        else:
            frac = 0.0
        info["frac"] = frac
        for t in info["teams"]:
            games[t["abbrev"]] = info
    return games
