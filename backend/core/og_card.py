"""Open Graph share-card rendering for detection permalinks.

Pure presentation helpers: given a (localized) detection payload and the
absolute URLs the route resolved, produce the tiny HTML document whose
``<head>`` carries the OG/Twitter meta tags that link-unfurl crawlers read.
Which card a caller is entitled to (detailed vs. generic) is the route's
business — see api.get_recording_og_card.
"""
import html
from datetime import datetime

# A single static PNG (the app's branded bird illustration) backs every card.
# It lives in the frontend's public/ dir, so nginx serves it at the web root —
# the OG endpoint only needs to reference its absolute URL. PNG (not the WebP
# original) because several unfurlers won't render WebP og:images.
OG_CARD_IMAGE_PATH = "/default_bird.png"
_OG_CARD_IMAGE_SIZE = (1024, 1024)  # square — the full branded illustration


def _format_og_timestamp(ts):
    """Human-friendly detection time for the preview description. 24-hour clock
    sidesteps platform-specific strftime padding flags; raw value if unparseable."""
    if not ts:
        return ''
    try:
        dt = datetime.fromisoformat(str(ts))
    except ValueError:
        return str(ts)
    return dt.strftime('%b %d, %Y, %H:%M')


def format_og_description(recording):
    """One-line ' · '-joined summary: scientific name, confidence, and time.

    The audio source is intentionally omitted — it's an internal label
    (``source_0``, an RTSP name, …) that means nothing to someone receiving a
    shared link."""
    parts = []
    sci = recording.get('scientific_name')
    if sci:
        parts.append(sci)
    conf = recording.get('confidence')
    if isinstance(conf, (int, float)):
        parts.append(f"{round(conf * 100)}% confidence")
    when = _format_og_timestamp(recording.get('timestamp'))
    if when:
        parts.append(when)
    return " · ".join(parts) or "Bird detection"


def indefinite_article(noun):
    """'a' or 'an' for the leading sound of ``noun`` (a species name).

    Heuristic, not perfect: vowel-initial → 'an', except the 'eu-' words that
    read with a 'y' glide ('a European Starling', 'a Eurasian Wigeon'). Good
    enough for the species names that appear in share-card titles."""
    word = str(noun).strip().lower()
    if not word:
        return 'a'
    if word.startswith('eu'):
        return 'a'
    return 'an' if word[0] in 'aeiou' else 'a'


def render_og_card(*, title, description, url, image_url, site_name="BirdNET-PiPy"):
    """Render a minimal HTML doc carrying Open Graph + Twitter Card meta tags for
    link-unfurl crawlers (iMessage/LinkPresentation, Slack, Discord, …). Only
    crawlers reach this (nginx routes them here); a canonical link + meta-refresh
    send any stray human to the real SPA page. All values are attribute-escaped.

    Every card carries the branded illustration (``image_url``, the caller's
    absolute URL for OG_CARD_IMAGE_PATH): a ``summary_large_image`` card also
    reveals the description on iMessage (its no-image card shows only the
    title)."""
    def e(s):
        return html.escape(str(s), quote=True)
    t, d, u, s = e(title), e(description), e(url), e(site_name)
    # The <title> appends " · site" for branding, but skip it when the title
    # already names the site (e.g. "BirdNET-PiPy overheard a Northern Cardinal")
    # to avoid a redundant doubled brand.
    page_title = t if site_name in title else f"{t} · {s}"
    iu = e(image_url)
    w, h = _OG_CARD_IMAGE_SIZE
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en" prefix="og: https://ogp.me/ns#">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{page_title}</title>\n"
        f'<link rel="canonical" href="{u}">\n'
        f'<meta name="description" content="{d}">\n'
        '<meta property="og:type" content="website">\n'
        f'<meta property="og:site_name" content="{s}">\n'
        f'<meta property="og:title" content="{t}">\n'
        f'<meta property="og:description" content="{d}">\n'
        f'<meta property="og:url" content="{u}">\n'
        f'<meta property="og:image:width" content="{w}">\n'
        f'<meta property="og:image:height" content="{h}">\n'
        f'<meta property="og:image" content="{iu}">\n'
        f'<meta property="og:image:alt" content="{s}">\n'
        '<meta property="og:image:type" content="image/png">\n'
        f'<meta name="twitter:image" content="{iu}">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{t}">\n'
        f'<meta name="twitter:description" content="{d}">\n'
        f'<meta http-equiv="refresh" content="0; url={u}">\n'
        "</head>\n"
        f'<body><p>View this detection at <a href="{u}">{u}</a>.</p></body>\n'
        "</html>\n"
    )
