# filters.py

import re

# StreamIMDb configuration
STREAM_SITE_DOMAIN = "streamimdb.ru"
PLAYIMDB_DOMAIN = "playimdb.com"

# IMDb ID pattern (e.g., tt5950044)
IMDB_ID_PATTERN = re.compile(r'(tt\d{6,9})')

# TV Series indicators
TV_KEYWORDS = ["tv series", "tv show", "season", "episode", "series", "tv show"]
TV_SHOW_KEYWORDS = ["tv series", "tv show", "series"]

JUNK_TITLE_KEYWORDS = [
    "login", "sign in", "sign up", "pricing", "plans", "about us", "user center",
    "how to", "earn online", "list of", "filmography", "born", "film", "cast",
    "review", "rating", "trailer", "photo", "video", "full cast", "trivia",
]

# Common STOP_WORDS to ignore in matching
STOP_WORDS = {
    "of", "the", "a", "an", "in", "on", "at", "to", "and", "or", "is", "are",
    "for", "with", "2024", "2023", "2022", "2021", "2020", "2019", "2018",
    "hd", "full", "movie", "film", "download", "watch", "online", "free",
    "tamil", "hindi", "english", "telugu", "malayalam", "kannada", "bollywood",
    "hollywood", "dubbed", "subtitles", "1080p", "720p", "480p", "4k", "uhd",
}


def is_junk_title(title: str) -> bool:
    title_lower = title.lower()
    return any(junk in title_lower for junk in JUNK_TITLE_KEYWORDS)


def is_tv_title(title: str) -> bool:
    """Check if title indicates a TV series/episode"""
    title_lower = title.lower()
    return any(kw in title_lower for kw in TV_KEYWORDS)


def detect_item_type(title: str, url: str) -> str:
    """Detect if result is a movie or TV series/episode"""
    title_lower = title.lower()
    url_lower = url.lower()

    # Check for episodes (has season/episode in title or URL)
    if "episode" in title_lower or "/ep/" in url_lower:
        return "tv"

    # Check for TV series
    if any(kw in title_lower for kw in TV_SHOW_KEYWORDS):
        return "tv"

    # Check URL patterns
    if "/title/tt" in url_lower:
        # If URL contains /search/ or /list/ it's likely a movie list, not a show
        if "/search/" in url_lower or "/list/" in url_lower:
            return "movie"

    return "movie"


def extract_imdb_id(url: str) -> str:
    """Extract IMDb ID from URL. e.g. https://www.imdb.com/title/tt5950044/ -> tt5950044"""
    match = IMDB_ID_PATTERN.search(url)
    if match:
        return match.group(1)
    return None


def strict_title_match(title: str, query: str) -> bool:
    """
    Strictly check if query keywords appear in title.
    Returns True only if significant query words are found in title.
    """
    # Clean both title and query
    title_clean = re.sub(r'[^\w\s]', '', title.lower())
    query_clean = re.sub(r'[^\w\s]', '', query.lower())

    # Get important words from query (at least 3 chars, not stop words)
    query_words = [w for w in query_clean.split() if len(w) >= 3 and w not in STOP_WORDS]

    if not query_words:
        return True  # No significant words to match

    # For single-word queries (like "Dhurandhar"), require exact match at START of title
    if len(query_words) == 1:
        main_word = query_words[0]
        # Check if title starts with the query word (exact match at beginning)
        title_start = title_clean.split()[0] if title_clean.split() else ""
        if title_start == main_word:
            return True
        # Also check if query is a significant part (first word matches)
        if main_word in title_clean.split()[:2]:  # First 2 words
            return True
        return False

    # Check if at least 50% of significant query words are in title
    matches = sum(1 for w in query_words if w in title_clean)

    # For short queries (1-2 words), require at least one match
    if len(query_words) <= 2:
        return matches >= 1

    # For longer queries, require 50% match
    return matches >= len(query_words) * 0.5


def title_matches_query(title: str, snippet: str, query: str) -> bool:
    """Check if title matches query - stricter version"""
    # First do strict title matching
    if not strict_title_match(title, query):
        return False

    # Also check snippet as fallback
    query_words = [w for w in query.lower().split() if w not in STOP_WORDS and len(w) > 2]
    if not query_words:
        return True

    combined_normal = (title + " " + snippet).lower()
    combined_nospace = combined_normal.replace(" ", "")

    for word in query_words:
        if word not in combined_normal and word not in combined_nospace:
            return False

    return True


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

    # Remove TV series/episode keywords for cleaner display
    tv_cleanups = [
        " TV Series", " TV Show", " Season ", " Episode ",
        " TV Mini-Series", " TV", " (TV)", " - Season", " - Episode",
    ]
    for cleanup in tv_cleanups:
        if cleanup in title:
            title = title.replace(cleanup, "")

    if " - " in title:
        title = title.split(" - ")[0]
    if "(" in title:
        title = title.split("(")[0]
    return title.strip()


def build_streamimdb_link(imdb_id: str, item_type: str = "movie") -> str:
    """Build StreamIMDb embed link from IMDb ID (e.g., tt5950044)"""
    # Ensure IMDb ID has 'tt' prefix
    if not imdb_id.startswith("tt"):
        imdb_id = "tt" + imdb_id
    return f"https://{STREAM_SITE_DOMAIN}/embed/{item_type}/{imdb_id}"


def apply_filters(raw_results: list, query: str) -> list:
    """
    Filter IMDb search results and convert to StreamIMDb links.
    """
    filtered = []
    seen_ids = set()
    seen_titles = set()

    # First, check if query might be a TV series (common patterns)
    query_lower = query.lower()
    is_tv_query = any(tv_kw in query_lower for tv_kw in ["show", "series", "season", "episode", "tv"])

    for i, r in enumerate(raw_results, start=1):
        url = r.get("href", "")
        title = r.get("title", "")
        snippet = r.get("body", "")

        # 1. Must be a valid IMDb URL (title page, not search results)
        imdb_id = extract_imdb_id(url)
        if not imdb_id:
            continue

        # Skip search/list pages
        if "/search/" in url.lower() or "/list/" in url.lower():
            continue

        # 2. No junk titles
        if is_junk_title(title):
            continue

        # 3. Must STRICTLY match query keywords
        if not title_matches_query(title, snippet, query):
            continue

        # 4. Deduplicate by IMDb ID
        if imdb_id in seen_ids:
            continue
        seen_ids.add(imdb_id)

        # Detect type - movie or TV
        item_type = detect_item_type(title, url)

        # For TV shows, also add main series entry
        if item_type == "tv" and is_tv_query:
            pass

        # Clean the title
        cleaned_title = clean_title(title)

        # Skip if we've seen this title before
        title_key = cleaned_title.lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

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
    """
    For TV series, search for multiple seasons.
    Returns a list of search queries to run.
    """
    queries = []

    # Try different season patterns
    for season_num in range(1, 6):  # Search first 5 seasons
        queries.append(f"{query} season {season_num}")

    return queries