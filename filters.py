# filters.py

import re

# StreamIMDb configuration
STREAM_SITE_DOMAIN = "streamimdb.ru"

# IMDb ID pattern (e.g., tt5950044)
IMDB_ID_PATTERN = re.compile(r'(tt\d{6,9})')

# TV Series indicators
TV_KEYWORDS = ["tv series", "tv show", "season", "episode", "series"]


def detect_item_type(title: str, url: str) -> str:
    """Detect if result is a movie or TV series/episode"""
    title_lower = title.lower()
    url_lower = url.lower()

    if "episode" in title_lower or "/ep/" in url_lower:
        return "tv"

    if any(kw in title_lower for kw in ["tv series", "tv show", "series"]):
        return "tv"

    return "movie"


def extract_imdb_id(url: str) -> str:
    """Extract IMDb ID from URL. e.g. https://www.imdb.com/title/tt5950044/ -> tt5950044"""
    match = IMDB_ID_PATTERN.search(url)
    if match:
        return match.group(1)
    return None


def clean_title(title: str) -> str:
    # Remove common suffixes from titles
    suffixes = [
        " - IMDb",
        " | IMDb",
        " - IMDb",
        " - Wikipedia",
        " (film)",
        " (TV Series)",
        " (TV Movie)",
        " (TV)",
    ]
    for suffix in suffixes:
        title = title.replace(suffix, "")

    if " - " in title:
        title = title.split(" - ")[0]
    if "(" in title:
        title = title.split("(")[0]
    return title.strip()


def build_streamimdb_link(imdb_id: str, item_type: str = "movie") -> str:
    """Build StreamIMDb embed link from IMDb ID"""
    if not imdb_id.startswith("tt"):
        imdb_id = "tt" + imdb_id
    return f"https://{STREAM_SITE_DOMAIN}/embed/{item_type}/{imdb_id}"


def apply_filters(raw_results: list, query: str) -> list:
    """
    Filter IMDb search results and convert to StreamIMDb links.
    Very simple - just extract IMDb IDs and build links.
    """
    filtered = []
    seen_ids = set()

    for i, r in enumerate(raw_results, start=1):
        url = r.get("href", "")
        title = r.get("title", "")
        snippet = r.get("body", "")

        # Must have a valid IMDb ID
        imdb_id = extract_imdb_id(url)
        if not imdb_id:
            continue

        # Skip search/list pages
        if "/search/" in url.lower() or "/list/" in url.lower():
            continue

        # Skip if already seen
        if imdb_id in seen_ids:
            continue
        seen_ids.add(imdb_id)

        # Detect type
        item_type = detect_item_type(title, url)

        # Clean title
        cleaned_title = clean_title(title)

        filtered.append({
            "position": len(filtered) + 1,
            "title": cleaned_title,
            "link": build_streamimdb_link(imdb_id, item_type),
            "movie_id": imdb_id,
            "type": item_type,
            "snippet": snippet[:100] if snippet else "",
            "source": "StreamIMDb",
        })

    return filtered


def search_tv_series_seasons(query: str) -> list:
    """For TV series, search for multiple seasons."""
    queries = []
    for season_num in range(1, 6):
        queries.append(f"{query} season {season_num}")
    return queries