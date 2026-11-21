"""
Zelfgekozen teamkleuren (per fantasy-team, gedeeld met de hele league).

Opslag in Postgres als DATABASE_URL is gezet (blijft bewaard bij herstarts),
anders in data/team_colors.json.
"""
import json
import os
import re
import threading
import time

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# Kant-en-klare paletten: (id, naam, hoofdkleur, tweede kleur)
PRESETS = [
    ("navy-zilver", "Navy & zilver", "#1d3f8f", "#a5acaf"),
    ("groen-goud", "Groen & goud", "#1f6b3a", "#ffb612"),
    ("zwart-goud", "Zwart & goud", "#ffb612", "#141414"),
    ("rood-wit", "Rood & wit", "#c8102e", "#ffffff"),
    ("paars-goud", "Paars & goud", "#4f2683", "#ffc62f"),
    ("teal-zwart", "Teal & zwart", "#00a0b0", "#141414"),
    ("oranje-navy", "Oranje & navy", "#f26a24", "#0b1f3a"),
    ("hemelsblauw", "Hemelsblauw & zilver", "#2e86de", "#b0b7bc"),
    ("bordeaux-goud", "Bordeaux & goud", "#7a1f2b", "#ffb612"),
    ("mint-grijs", "Mint & grijs", "#3ec9a7", "#3b4252"),
    ("roze-zwart", "Roze & zwart", "#e84a9c", "#141414"),
    ("oranje-bruin", "Oranje & bruin", "#ff6a13", "#3a2618"),
]


def valid_hex(v):
    return isinstance(v, str) and bool(HEX.match(v))


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def palette_for(primary, secondary):
    from .palette import build_palette
    pal = build_palette(rgb(primary), rgb(secondary) if secondary else None, source="gekozen")
    pal["chosenPrimary"], pal["chosenSecondary"] = primary.lower(), (secondary or "").lower() or None
    return pal


class TeamColorStore:
    def __init__(self, league_key, data_dir, database_url=None, log=print):
        self.key = league_key
        self.url = database_url
        self.log = log
        self.path = os.path.join(data_dir, "team_colors.json")
        self.lock = threading.Lock()
        self.colors = {}  # team_id -> {"primary", "secondary"}
        self._loaded, self._last_try = False, 0.0
        self._load()

    # -- opslag --------------------------------------------------------
    def _db(self):
        import psycopg
        return psycopg.connect(self.url, autocommit=True, connect_timeout=10)

    def _load(self):
        self._last_try = time.time()
        try:
            if self.url:
                with self._db() as conn:
                    conn.execute("""CREATE TABLE IF NOT EXISTS team_colors (
                                        league_key text NOT NULL, team_id integer NOT NULL,
                                        primary_color text NOT NULL, secondary_color text,
                                        updated_at timestamptz NOT NULL DEFAULT now(),
                                        PRIMARY KEY (league_key, team_id))""")
                    rows = conn.execute("SELECT team_id, primary_color, secondary_color FROM team_colors "
                                        "WHERE league_key = %s", (self.key,)).fetchall()
                self.colors = {int(t): {"primary": p, "secondary": s} for t, p, s in rows}
            elif os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as f:
                    self.colors = {int(k): v for k, v in json.load(f).get(self.key, {}).items()}
        except Exception as e:
            self.log(f"Teamkleuren laden mislukt ({e}); standaardkleuren tot de database bereikbaar is.")
            return
        self._loaded = True

    def set(self, team_id, primary, secondary):
        if not valid_hex(primary) or (secondary and not valid_hex(secondary)):
            raise ValueError("ongeldige kleur (verwacht #rrggbb)")
        team_id = int(team_id)
        with self.lock:
            if self.url:
                with self._db() as conn:
                    conn.execute("""INSERT INTO team_colors (league_key, team_id, primary_color, secondary_color)
                                    VALUES (%s, %s, %s, %s)
                                    ON CONFLICT (league_key, team_id) DO UPDATE
                                    SET primary_color = EXCLUDED.primary_color,
                                        secondary_color = EXCLUDED.secondary_color, updated_at = now()""",
                                 (self.key, team_id, primary, secondary))
            else:
                data = {}
                if os.path.exists(self.path):
                    with open(self.path, encoding="utf-8") as f:
                        data = json.load(f)
                data.setdefault(self.key, {})[str(team_id)] = {"primary": primary, "secondary": secondary}
                with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(self.path + ".tmp", self.path)
            self.colors[team_id] = {"primary": primary, "secondary": secondary}

    def palette(self, team_id):
        if not self._loaded and time.time() - self._last_try > 60:  # database was eerder onbereikbaar
            self._load()
        c = self.colors.get(int(team_id))
        return palette_for(c["primary"], c.get("secondary")) if c else None
