"""Download en cache van nflverse-datasets (gratis, CC-BY / CC-BY-SA)."""
import os
import time
import urllib.request

import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download/"
FILES = {
    "pbp": "pbp/play_by_play_{s}.parquet",
    "ftn": "ftn_charting/ftn_charting_{s}.parquet",
    "players": "players/players.csv.gz",
    "snaps": "snap_counts/snap_counts_{s}.csv.gz",
    "stats": "stats_player/stats_player_week_{s}.csv.gz",
    "pfr_def": "pfr_advstats/advstats_week_def_{s}.csv.gz",
    "ngs_rec": "nextgen_stats/ngs_receiving.csv.gz",
    "ngs_pass": "nextgen_stats/ngs_passing.csv.gz",
    "ngs_rush": "nextgen_stats/ngs_rushing.csv.gz",
}

PBP_COLS = [
    "game_id", "play_id", "season_type", "week", "posteam", "defteam",
    "play_type", "pass_length", "pass_location", "air_yards", "yardline_100",
    "epa", "success", "complete_pass", "receiver_player_id", "rusher_player_id",
    "passer_player_id", "qb_hit", "sack", "yards_after_catch",
    "xyac_mean_yardage", "cpoe", "qb_dropback", "rush_attempt", "pass_attempt",
    "yards_gained", "touchdown", "interception", "qb_scramble", "down",
]


FTN_COLS = [
    "nflverse_game_id", "nflverse_play_id", "n_defense_box", "n_blitzers", "n_pass_rushers",
    "is_motion", "is_play_action", "is_screen_pass", "is_qb_out_of_pocket", "is_interception_worthy",
    "is_throw_away", "is_catchable_ball", "is_contested_ball", "is_drop",
]


class NflverseCache:
    def __init__(self, season, cache_dir, max_age_hours=12, log=print):
        self.season = season
        self.dir = cache_dir
        self.max_age = max_age_hours * 3600
        self.log = log
        os.makedirs(cache_dir, exist_ok=True)

    def path(self, name):
        rel = FILES[name].format(s=self.season)
        return os.path.join(self.dir, os.path.basename(rel))

    def fetch(self, name, force=False):
        p = self.path(name)
        fresh = os.path.exists(p) and time.time() - os.path.getmtime(p) < self.max_age
        if fresh and not force:
            return p
        url = BASE + FILES[name].format(s=self.season)
        self.log(f"  nflverse: {os.path.basename(p)} downloaden…")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ff-dashboard/2.0"})
            with urllib.request.urlopen(req, timeout=300) as r, open(p + ".tmp", "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(p + ".tmp", p)
        except Exception as e:  # oude cache gebruiken als die er is
            if os.path.exists(p):
                self.log(f"  nflverse: {name} niet ververst ({e}); cache gebruikt")
            else:
                self.log(f"  nflverse: {name} niet beschikbaar ({e})")
                return None
        return p

    def load(self, name, **kw):
        p = self.fetch(name)
        if not p:
            return pd.DataFrame()
        if p.endswith(".parquet"):
            return pd.read_parquet(p, **kw)
        # in blokken lezen: houdt het geheugen laag bij grote gecomprimeerde CSV's
        chunks = pd.read_csv(p, low_memory=True, chunksize=20000, **kw)
        return pd.concat(chunks, ignore_index=True)

    def pbp(self):
        df = self.load("pbp", columns=PBP_COLS)
        ftn = self.load("ftn", columns=FTN_COLS)
        if not ftn.empty:
            ftn = ftn.drop(columns=["season", "week"], errors="ignore")
            df = df.merge(ftn, how="left", left_on=["game_id", "play_id"],
                          right_on=["nflverse_game_id", "nflverse_play_id"])
        return df
