# filters.py

import re

TERABOX_DOMAINS = [
    "terabox.com",
    "1024terabox.com",
    "teraboxapp.com",
    "freeterabox.com",
    "4funbox.com",
    "mirrobox.com",
    "nephobox.com",
    "terafileshare.com",
    "momerybox.com",
    "tibibox.com",
    "teraboxlink.com",
]

# hive/detail removed — Q&A pages not real file links
VALID_PATH_PATTERNS = [
    r"/s/[a-zA-Z0-9_-]+",
    r"/sharing/link\?.*surl=[a-zA-Z0-9_-]+",
    r"/sharing/\?surl=[a-zA-Z0-9_-]+",
    r"/[a-z]+/sharing/link\?.*surl=[a-zA-Z0-9_-]+",
]

JUNK_TITLE_KEYWORDS = [
    "login", "sign in", "sign up", "cloud storage", "free storage",
    "pricing", "plans", "about us", "user center", "download searching",
    "searching app", "searching video", "searching: everything",
    "0 file", "file (s) including are shared from",
    "how to", "what is searching", "why is searching", "earn online",
    "400 million", "free cloud", "biggest free",
]

STOP_WORDS = {"of", "the", "a", "an", "in", "on", "at", "to", "and", "or", "is", "are"}


def is_valid_terabox_url(url: str) -> bool:
    if not any(domain in url.lower() for domain in TERABOX_DOMAINS):
        return False
    return any(re.search(p, url, re.IGNORECASE) for p in VALID_PATH_PATTERNS)


def is_junk_title(title: str) -> bool:
    return any(junk in title.lower() for junk in JUNK_TITLE_KEYWORDS)


def extract_surl(url: str) -> str:
    m = re.search(r'surl=([a-zA-Z0-9_-]+)', url)
    return m.group(1) if m else url


def title_matches_query(title: str, snippet: str, query: str) -> bool:
    """
    Check if result is relevant to query.
    Handles DDG's joined words issue (e.g. 'ManofSteel' instead of 'Man of Steel')
    by checking both normal and space-stripped versions.
    """
    query_words = [w for w in query.lower().split() if w not in STOP_WORDS and len(w) > 2]
    if not query_words:
        return True

    # Normal check — words with spaces
    combined_normal = (title + " " + snippet).lower()

    # Nospace check — handles 'ManofSteel', 'manofsteel' etc.
    combined_nospace = combined_normal.replace(" ", "")

    for word in query_words:
        # Must appear in either normal OR nospace version
        if word not in combined_normal and word not in combined_nospace:
            return False

    return True


def clean_title(title: str) -> str:
    for suffix in [
        " - Share Files Online & Send Larges Files with Searching",
        " - Share Files Online & Send Large Files with Searching",
        " - Searching",
        "- Searching",
        " | Searching",
    ]:
        title = title.replace(suffix, "")
    if " - " in title:
        title = title.split(" - ")[0]
    return title.strip()


def apply_filters(raw_results: list, query: str) -> list:
    filtered = []
    seen_surls = set()

    for i, r in enumerate(raw_results, start=1):
        url = r.get("href", "")
        title = r.get("title", "")
        snippet = r.get("body", "")

        # 1. Valid share URL only
        if not is_valid_terabox_url(url):
            continue

        # 2. No junk titles
        if is_junk_title(title):
            continue

        # 3. Must match query keywords
        if not title_matches_query(title, snippet, query):
            continue

        # 4. Deduplicate by surl
        surl = extract_surl(url)
        if surl in seen_surls:
            continue
        seen_surls.add(surl)

        filtered.append({
            "position": i,
            "title": title,
            "link": url,
            "displayed_link": url.split("?")[0],
            "snippet": snippet,
            "source": "TeraBox",
            "is_valid_share_link": True,
        })

    return filtered
