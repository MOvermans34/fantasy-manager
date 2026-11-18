"""
Bouwt de nflverse-analytics in een apart proces en schrijft een compact JSON-resultaat.

    python ffd/build_analytics.py <seizoen> <cache_dir> <uitvoer.json> [max_age_uren]

Zo blijft het geheugen van de webserver laag (belangrijk op hosting met 512 MB):
na afloop van dit proces komt al het pandas-geheugen weer vrij.
"""
import json
import math
import os
import sys

os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")  # ~50 MB minder piekgeheugen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ffd.analytics import Analytics  # noqa: E402
from ffd.nflverse import NflverseCache  # noqa: E402


def clean(o):
    """numpy-types -> Python, NaN/inf -> None, dict-sleutels -> str."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            o = o.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def main():
    season, cache_dir, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    max_age = float(sys.argv[4]) if len(sys.argv) > 4 else 12

    def log(*a):
        print(*a, flush=True)

    a = Analytics(NflverseCache(season, cache_dir, max_age_hours=max_age, log=log), log=log)
    a.build()
    data = clean(a.export())
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
    os.replace(tmp, out)


if __name__ == "__main__":
    main()
