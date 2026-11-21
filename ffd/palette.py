"""
Kleurenpalet per fantasy-team op basis van het teamlogo.

1. Logo ophalen (veilig: alleen https/publieke adressen, max. 2 MB, korte time-out).
2. Dominante kleuren bepalen (Pillow): transparante pixels en grijs/wit/zwart
   tellen nauwelijks mee, zodat de 'merkkleur' wint van de achtergrond.
3. Afgeleide UI-kleuren die altijd voldoende contrast hebben (WCAG):
   - accent: tekst/links op het oppervlak >= 4.5:1 (licht én donker thema)
   - knoppen: witte of zwarte tekst op de accentkleur >= 4.5:1
   - zijbalk: zeer donkere tint van de teamkleur, lichte tekst >= 7:1
Geen logo of ophalen mislukt: vaste kleur op basis van de teamnaam.
"""
import colorsys
import hashlib
import io
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

LIGHT_SURFACE = (0xFC, 0xFC, 0xFB)
DARK_SURFACE = (0x18, 0x1C, 0x22)
SIDEBAR_TEXT = (0xE8, 0xEC, 0xF2)
MAX_BYTES = 2 * 1024 * 1024

# Terugval-tinten (graden) voor teams zonder bruikbaar logo
FALLBACK_HUES = [212, 4, 145, 28, 268, 186, 334, 48, 96, 236]


# ----------------------------------------------------------------------
# Kleurwiskunde
# ----------------------------------------------------------------------
def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def hexc(rgb):
    return "#%02x%02x%02x" % tuple(int(round(max(0, min(255, x)))) for x in rgb)


def from_hls(h, l, s):
    return tuple(round(x * 255) for x in colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s))))


def to_hls(rgb):
    return colorsys.rgb_to_hls(*(x / 255 for x in rgb))


def mix(a, b, t):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


def fit_lightness(rgb, ok, darker=True, steps=100):
    """Verschuif de lichtheid (zelfde tint/verzadiging) tot ok(kleur) waar is."""
    h, l, s = to_hls(rgb)
    if ok(rgb):
        return rgb
    for i in range(1, steps + 1):
        nl = l - i / steps if darker else l + i / steps
        c = from_hls(h, nl, s)
        if ok(c):
            return c
        if nl <= 0 or nl >= 1:
            break
    return (0, 0, 0) if darker else (255, 255, 255)


# ----------------------------------------------------------------------
# Kleuren uit een logo
# ----------------------------------------------------------------------
def dominant_colors(data):
    """Geef de (max. 2) kenmerkende kleuren van een logo als RGB-tuples."""
    from PIL import Image  # alleen laden als er logo's zijn

    img = Image.open(io.BytesIO(data))
    img.draft("RGB", (128, 128))
    img = img.convert("RGBA")
    img.thumbnail((96, 96))
    px = [p for p in img.getdata() if p[3] >= 128]
    if not px:
        return []
    rgb = Image.new("RGB", (len(px), 1))
    rgb.putdata([p[:3] for p in px])
    q = rgb.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: 8 * 3]
    counts = sorted(q.getcolors() or [], reverse=True)
    scored = []
    total = sum(c for c, _ in counts) or 1
    for cnt, idx in counts:
        c = tuple(pal[idx * 3: idx * 3 + 3])
        h, l, s = to_hls(c)
        # merkkleur: verzadigd en niet bijna-wit/zwart weegt zwaar
        vivid = s * (1 - abs(l - 0.5) * 1.6)
        scored.append((cnt / total * (0.15 + vivid), c, h, s, l))
    scored.sort(reverse=True)
    out = [scored[0]]
    for cand in scored[1:]:
        dh = min(abs(cand[2] - out[0][2]), 1 - abs(cand[2] - out[0][2]))
        if (dh > 0.08 and cand[3] > 0.25) or abs(cand[4] - out[0][4]) > 0.35:
            out.append(cand)
            break
    return [c[1] for c in out]


def _public_https(url):
    """Alleen https naar publieke adressen (geen interne netwerken: SSRF)."""
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or not u.hostname:
        return False
    try:
        infos = socket.getaddrinfo(u.hostname, 443)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return False
    return True


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Volg een redirect alleen als het nieuwe adres ook https + publiek is."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public_https(newurl):
            raise urllib.error.URLError("redirect naar niet-toegestaan adres")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect)


def fetch_logo(url, timeout=6):
    if not url or not _public_https(url):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "ff-dashboard/3.0", "Accept": "image/*"})
    with _OPENER.open(req, timeout=timeout) as r:
        if not (r.headers.get("Content-Type") or "image/").startswith("image/"):
            return None
        data = r.read(MAX_BYTES + 1)
    return data if len(data) <= MAX_BYTES else None


# ----------------------------------------------------------------------
# Palet
# ----------------------------------------------------------------------
def build_palette(primary, secondary=None, source="logo"):
    h, l, s = to_hls(primary)
    if s < 0.12:  # zwart/wit/grijs logo: neutrale leisteen-tint
        h, s = 0.6, 0.18
        primary = from_hls(h, min(max(l, 0.3), 0.6), s)
    base = from_hls(h, l, max(s, 0.35))

    light_accent = fit_lightness(base, lambda c: contrast(c, LIGHT_SURFACE) >= 4.5, darker=True)
    dark_accent = fit_lightness(base, lambda c: contrast(c, DARK_SURFACE) >= 4.5, darker=False)

    def on(c):
        return "#ffffff" if contrast(c, (255, 255, 255)) >= 4.5 else "#0b0b0b"

    # knopkleur: zo dicht mogelijk bij de merkkleur, met leesbare tekst erop
    button = base if max(contrast(base, (255, 255, 255)), contrast(base, (11, 11, 11))) >= 4.5 else \
        fit_lightness(base, lambda c: contrast(c, (255, 255, 255)) >= 4.5, darker=True)
    # zijbalk: tint van de donkerste (verzadigde) teamkleur, anders van de hoofdkleur
    sh, ss = h, s
    if secondary is not None and luminance(secondary) < luminance(primary):
        h2, _l2, s2 = to_hls(secondary)
        if s2 >= 0.2:
            sh, ss = h2, s2
    sidebar = from_hls(sh, 0.12, min(ss, 0.45))
    if contrast(sidebar, SIDEBAR_TEXT) < 7:
        sidebar = fit_lightness(sidebar, lambda c: contrast(c, SIDEBAR_TEXT) >= 7, darker=True)
    # actieve navigatie in de (donkere) zijbalk: zichtbaar t.o.v. zijbalk + leesbare tekst
    active = fit_lightness(base, lambda c: contrast(c, (255, 255, 255)) >= 4.5 and contrast(c, sidebar) >= 1.8,
                           darker=True)
    if contrast(active, sidebar) < 1.8:
        active = fit_lightness(base, lambda c: contrast(c, (11, 11, 11)) >= 4.5 and contrast(c, sidebar) >= 3,
                               darker=False)
    sec = secondary or from_hls((h + 0.08) % 1, l, s)
    return {
        "source": source,
        "primary": hexc(primary), "secondary": hexc(sec),
        "button": hexc(button), "onButton": on(button),
        "sidebar": hexc(sidebar), "sidebarActive": hexc(active), "onSidebarActive": on(active),
        "light": {"accent": hexc(light_accent), "accentSoft": hexc(mix(LIGHT_SURFACE, light_accent, 0.12)),
                  "mine": hexc(mix(LIGHT_SURFACE, base, 0.10))},
        "dark": {"accent": hexc(dark_accent), "accentSoft": hexc(mix(DARK_SURFACE, dark_accent, 0.20)),
                 "mine": hexc(mix(DARK_SURFACE, base, 0.22))},
    }


def fallback_palette(seed):
    n = int(hashlib.sha1(str(seed).encode()).hexdigest(), 16)
    hue = FALLBACK_HUES[n % len(FALLBACK_HUES)] / 360
    return build_palette(from_hls(hue, 0.45, 0.65), source="naam")


def palette_from_bytes(data):
    cols = dominant_colors(data)
    if not cols:
        return None
    return build_palette(cols[0], cols[1] if len(cols) > 1 else None)
