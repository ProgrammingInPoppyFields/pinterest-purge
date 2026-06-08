#!/usr/bin/env python3
# 🌸🌼🌷 PROGRAMMING IN POPPY FIELDS 🌷🌼🌸
# pinterest_purge_merged.py
#
# Download images from public Pinterest boards OR board sections.
#
# What to install:
#   pip install -U selenium requests
#
# Browser / driver setup:
#   - You need Google Chrome installed.
#   - With modern Selenium, you usually do NOT need to manually install ChromeDriver.
#     Selenium Manager handles driver setup automatically in most cases.
#
# How it works:
#   Instead of scraping the rendered DOM (which misses pins due to Pinterest's
#   virtual scrolling), this script uses Selenium only to load the page and harvest
#   the session cookies + headers Pinterest expects. It then calls Pinterest's
#   internal BoardFeedResource JSON API directly, paginating with bookmark tokens
#   until all pins are collected. This bypasses the virtualization problem entirely
#   and also avoids capturing any non-board images (profile pics, suggestions, etc.)
#   because the API only returns actual board pins.
#
# Examples:
#   Download a whole board:
#       python pinterest_purge_merged.py --url "https://www.pinterest.com/username/board-name/"
#
#   Download a board section:
#       python pinterest_purge_merged.py --url "https://www.pinterest.com/username/board/section-name/"
#
#   Download multiple sections into one folder:
#       python pinterest_purge_merged.py --url \
#         "https://www.pinterest.com/username/board/section-one/" \
#         "https://www.pinterest.com/username/board/section-two/"
#
#   Interactive mode:
#       python pinterest_purge_merged.py
#
# Notes:
#   - This script is for PUBLIC Pinterest pages only.
#   - /originals/ URLs increasingly return 403 errors from Pinterest's CDN as of 2025,
#     so images are fetched at /736x/ resolution (still high quality) with a fallback
#     to /originals/ if that fails.
#   - Pinterest can change its internal API at any time, which may break this script.

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set
from urllib.parse import urlparse, urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = "pinterest_downloads"   # where downloaded images land
DEFAULT_WINDOW_SIZE = "1920,1080"            # browser window size for Selenium
DEFAULT_PAGE_LOAD_WAIT = 20                  # seconds to wait for page to load
DEFAULT_REQUEST_TIMEOUT = 30                 # seconds per image download request
API_PAGE_SIZE = 250                          # pins per API page (Pinterest max ~250)
MAX_API_PAGES = 40                           # hard cap: 40 pages × 250 = 10,000 pins
PREFERRED_RESOLUTION = "736x"               # CDN resolution to request (736x = high quality, rarely 403s)

# Pinterest's internal JSON endpoints — these are what the browser calls under the hood
PINTEREST_BOARD_FEED_URL = "https://www.pinterest.com/resource/BoardFeedResource/get/"
PINTEREST_SECTION_FEED_URL = "https://www.pinterest.com/resource/BoardSectionPinsResource/get/"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

# Frozen dataclass = immutable + hashable, so we can throw these into a set for deduplication
@dataclass(frozen=True)
class ImageCandidate:
    url: str          # the image CDN URL we'll download
    source_page: str  # the Pinterest board URL this came from
    alt: str = ""     # pin description, used as alt text


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

# Matches any resolution segment in a Pinterest CDN URL, e.g. /736x/, /236x/, /originals/
SIZE_SEGMENT_PATTERN = re.compile(r"/(?:\d+x(?:\d+)?|originals)/")


def upgrade_resolution(url: str, target: str = PREFERRED_RESOLUTION) -> str:
    """Swap whatever resolution is in a Pinterest CDN URL for our preferred one."""
    if not url:
        return url
    upgraded = SIZE_SEGMENT_PATTERN.sub(f"/{target}/", url)
    return upgraded.split("?")[0]  # strip query string junk while we're here


def parse_username_and_board(page_url: str):
    """Crack a Pinterest URL into (username, board_slug, section_slug_or_None)."""
    path = urlparse(page_url).path.strip("/")
    parts = [p for p in path.split("/") if p]
    # e.g. /someuser/cool-board/           → ['someuser', 'cool-board']
    # e.g. /someuser/cool-board/my-section/ → ['someuser', 'cool-board', 'my-section']
    if len(parts) < 2:
        return None, None, None
    username = parts[0]
    board = parts[1]
    section = parts[2] if len(parts) >= 3 else None  # None if it's a whole board, not a section
    return username, board, section


def slug_from_url(url: str) -> str:
    """Turn a URL path into a safe folder name, e.g. for --auto-subdir."""
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if not path_parts:
        return "pinterest"
    slug = "__".join(path_parts[-3:])                      # grab last 3 path segments
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", slug)         # replace anything weird with _
    return slug[:80] or "pinterest"                        # cap length, never return empty


# ---------------------------------------------------------------------------
# HTTP / Selenium setup
# ---------------------------------------------------------------------------

def build_requests_session() -> requests.Session:
    """Make a requests Session with auto-retry and browser-like headers."""
    session = requests.Session()
    retry = Retry(
        total=4,                                       # retry up to 4 times total
        backoff_factor=1.5,                            # wait 1.5s, 3s, 4.5s... between retries
        status_forcelist=[429, 500, 502, 503, 504],    # retry on these HTTP error codes
        allowed_methods=["HEAD", "GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/135.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",  # we want JSON back
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",  # tells Pinterest this is an XHR call
        "Referer": "https://www.pinterest.com/",
    })
    return session


def build_driver(headless: bool = True, window_size: str = DEFAULT_WINDOW_SIZE) -> webdriver.Chrome:
    """Spin up a Chrome browser via Selenium."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")          # invisible browser (newer headless mode)
    options.add_argument("--no-sandbox")                # required in some Linux environments
    options.add_argument("--disable-dev-shm-usage")     # prevents crashes in low-memory environments
    options.add_argument("--disable-gpu")               # GPU not needed in headless mode
    options.add_argument(f"--window-size={window_size}")
    options.add_argument("--lang=en-US")                # keep Pinterest in English
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=options)


def harvest_session_state(driver: webdriver.Chrome, page_url: str) -> Dict:
    """Open the board page in Chrome and steal the cookies + board ID we need for the API.

    Pinterest's internal API won't respond without valid session cookies and a CSRF token.
    We also dig the board/section numeric ID out of the page's Redux state blob, since
    the API needs the ID, not the human-readable slug from the URL.
    """
    print(f"  Loading page to harvest session cookies: {page_url}")
    driver.get(page_url)

    wait = WebDriverWait(driver, DEFAULT_PAGE_LOAD_WAIT)
    try:
        # Don't proceed until at least one real pin image is in the DOM
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-test-id='pinWrapper'] img")))
    except TimeoutException:
        print("  Warning: timed out waiting for pin images. Proceeding anyway.")

    time.sleep(3)  # give XHR calls a moment to finish before we grab cookies

    # Grab all browser cookies as a plain dict {name: value}
    cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
    csrf = cookies.get("csrftoken", "")  # we'll echo this back as X-CSRFToken header

    # Pinterest bakes the board/section numeric IDs into the page's initial JS state
    board_id = None
    section_id = None
    try:
        # Try two common global variable names Pinterest has used for its Redux state blob
        state_json = driver.execute_script(
            "return window.__PWS_INITIAL_PROPS__ ? "
            "JSON.stringify(window.__PWS_INITIAL_PROPS__) : "
            "(window.__PWS_DATA__ ? JSON.stringify(window.__PWS_DATA__) : null);"
        )
        if state_json:
            state = json.loads(state_json)
            # Search the whole object tree because the exact path changes periodically
            board_id = _deep_find(state, "board_id") or _deep_find(state, "boardId")
            section_id = _deep_find(state, "section_id") or _deep_find(state, "sectionId")
    except Exception as exc:
        print(f"  Could not extract IDs from page state: {exc}")

    return {
        "cookies": cookies,
        "csrf": csrf,
        "board_id": board_id,
        "section_id": section_id,
    }


def _deep_find(obj, key: str, _depth: int = 0):
    """Recursively hunt through a nested dict/list for a key, return first value found."""
    if _depth > 8:
        return None  # don't go infinitely deep into crazy nested structures
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], (str, int)) and obj[key]:
            return str(obj[key])  # found it
        for v in obj.values():
            result = _deep_find(v, key, _depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _deep_find(item, key, _depth + 1)
            if result:
                return result
    return None


# ---------------------------------------------------------------------------
# Pinterest internal API pagination
# ---------------------------------------------------------------------------

def _extract_images_from_api_response(data: dict, source_url: str) -> Set[ImageCandidate]:
    """Parse one page of the API response JSON and pull out all the pin image URLs."""
    candidates: Set[ImageCandidate] = set()

    # The actual pin objects live nested at resource_response → data
    try:
        pins = data["resource_response"]["data"]
    except (KeyError, TypeError):
        return candidates  # unexpected response shape, bail cleanly

    if not isinstance(pins, list):
        return candidates

    for pin in pins:
        if not isinstance(pin, dict):
            continue

        # Each pin has an 'images' block with multiple resolution variants
        images_block = pin.get("images") or {}

        # Walk from best to worst resolution and take the first one that has a URL
        for res_key in (PREFERRED_RESOLUTION, "originals", "474x", "236x"):
            img = images_block.get(res_key)
            if img and isinstance(img, dict) and img.get("url"):
                raw_url = img["url"].split("?")[0]  # drop query string
                alt = pin.get("description") or pin.get("title") or ""
                candidates.add(ImageCandidate(url=raw_url, source_page=source_url, alt=str(alt)))
                break  # got one for this pin, move on

    return candidates


def fetch_board_pins_via_api(
    session: requests.Session,
    session_state: Dict,
    page_url: str,
    username: str,
    board_slug: str,
    section_slug: Optional[str],
) -> Set[ImageCandidate]:
    """Hit Pinterest's internal API repeatedly until we have every pin in the board.

    Pinterest paginates with 'bookmarks': each response contains a bookmark token,
    and you pass it on the next request to get the next batch. When the bookmark
    comes back as '-end-', the board is exhausted.
    """
    cookies = session_state["cookies"]
    csrf = session_state["csrf"]
    board_id = session_state.get("board_id")
    section_id = session_state.get("section_id")

    # Pick the right endpoint: sections have their own separate API resource
    is_section = bool(section_slug and section_id)
    endpoint = PINTEREST_SECTION_FEED_URL if is_section else PINTEREST_BOARD_FEED_URL

    all_candidates: Set[ImageCandidate] = set()
    bookmark = None   # starts as None (first page), then gets set from each response
    page_num = 0

    print(f"\n  Paginating Pinterest API ({'section' if is_section else 'board'} feed)...")

    while page_num < MAX_API_PAGES:
        # Pinterest wants the query options as a JSON string inside the 'data' query param
        if is_section:
            options = {
                "section_id": section_id,
                "isPrefetch": False,
                "page_size": API_PAGE_SIZE,
                "redux_normalize_feed": True,
            }
        else:
            options = {
                "board_id": board_id,
                "board_url": f"/{username}/{board_slug}/",
                "currentFilter": -1,
                "field_set_key": "react_grid_pin",   # tells Pinterest which fields to include
                "filter_section_pins": True,          # exclude section pins from the main board feed
                "layout": "default",
                "page_size": API_PAGE_SIZE,
                "redux_normalize_feed": True,
            }

        if bookmark:
            options["bookmarks"] = [bookmark]  # cursor for the next page

        params = {
            "source_url": f"/{username}/{board_slug}/" + (f"{section_slug}/" if section_slug else ""),
            "data": json.dumps({"options": options, "context": {}}),
            "_": str(int(time.time() * 1000)),  # cache-buster timestamp
        }

        headers = {
            "X-CSRFToken": csrf,                      # CSRF protection — must match the cookie
            "X-Pinterest-AppState": "active",         # tells Pinterest the app is foregrounded
            "X-Requested-With": "XMLHttpRequest",     # identifies this as an AJAX request
        }

        try:
            resp = session.get(
                endpoint,
                params=params,
                cookies=cookies,
                headers=headers,
                timeout=DEFAULT_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"  API request failed on page {page_num + 1}: {exc}")
            break

        page_candidates = _extract_images_from_api_response(data, page_url)
        all_candidates.update(page_candidates)

        # Read the bookmark out of the response to know what to ask for next
        try:
            bookmarks = data["resource_response"]["bookmark"]
            if not bookmarks or bookmarks == "-end-":
                print(f"  Page {page_num + 1}: {len(page_candidates)} pins — reached end.")
                break  # Pinterest says we're done
            bookmark = bookmarks  # save it for the next loop iteration
        except (KeyError, TypeError):
            print(f"  Page {page_num + 1}: {len(page_candidates)} pins — no bookmark, stopping.")
            break

        print(f"  Page {page_num + 1}: {len(page_candidates)} pins (+{len(all_candidates)} total so far)")

        if len(page_candidates) == 0:
            print("  No new pins in this page, stopping.")
            break

        page_num += 1
        time.sleep(1.2)  # be polite, don't hammer the API

    print(f"  API collection done: {len(all_candidates)} unique pin images.")
    return all_candidates


# ---------------------------------------------------------------------------
# Top-level page collector
# ---------------------------------------------------------------------------

def collect_images_from_page(
    driver: webdriver.Chrome,
    page_url: str,
) -> Set[ImageCandidate]:
    """Orchestrate everything for one URL: browser → cookies → API → images."""
    print(f"\n{'=' * 80}")
    print(f"Processing: {page_url}")
    print(f"{'=' * 80}")

    username, board_slug, section_slug = parse_username_and_board(page_url)
    if not username or not board_slug:
        print(f"  Could not parse username/board from URL: {page_url}")
        return set()

    # Step 1: open the page in Chrome to pick up the cookies and board ID
    session_state = harvest_session_state(driver, page_url)

    if not session_state["csrf"]:
        print("  Warning: could not get CSRF token. API calls may fail.")

    if not session_state.get("board_id") and not section_slug:
        print("  Warning: could not extract board_id from page state. API call may fail.")
        print("  Hint: try running with --show-browser to see if the page is loading correctly.")

    # Step 2: use those cookies to paginate Pinterest's internal API
    session = build_requests_session()
    candidates = fetch_board_pins_via_api(
        session=session,
        session_state=session_state,
        page_url=page_url,
        username=username,
        board_slug=board_slug,
        section_slug=section_slug,
    )

    # Step 3: if the API came up empty, fall back to scraping the visible DOM
    if not candidates:
        print("  API returned no results — falling back to DOM scrape.")
        candidates = _dom_fallback(driver, page_url)

    return candidates


def _dom_fallback(driver: webdriver.Chrome, page_url: str) -> Set[ImageCandidate]:
    """Last resort: scrape images from pin elements currently visible in the DOM.

    This has the virtualization problem (only gets ~50% of pins on big boards),
    but it's better than nothing if the API path fails completely.
    """
    print("  DOM fallback: scraping pinWrapper images from current page...")
    # Run JS in the browser to collect src/alt from every img inside a pin card
    raw_items = driver.execute_script(
        """
        const wrappers = Array.from(document.querySelectorAll("div[data-test-id='pinWrapper']"));
        const items = [];
        for (const w of wrappers) {
            for (const img of w.querySelectorAll('img')) {
                const src = img.currentSrc || img.src || '';
                if (src) items.push({ src, alt: img.alt || '' });
            }
        }
        return items;
        """
    )
    candidates: Set[ImageCandidate] = set()
    for item in raw_items:
        src = (item.get("src") or "").strip()
        if not src or "pinimg.com" not in src:
            continue  # skip anything that isn't a Pinterest CDN image
        upgraded = upgrade_resolution(src)  # bump to 736x if we can
        if upgraded:
            candidates.add(ImageCandidate(url=upgraded, source_page=page_url, alt=item.get("alt", "")))
    print(f"  DOM fallback collected {len(candidates)} images.")
    return candidates


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def infer_extension_from_response(response: requests.Response, fallback_url: str) -> str:
    """Figure out the right file extension from the Content-Type header (or the URL)."""
    content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(content_type) if content_type else None

    # mimetypes sometimes returns .jpe or .jpeg — normalize those to .jpg
    if guessed in {".jpe", ".jpeg"}:
        return ".jpg"
    if guessed in {".jpg", ".png", ".gif", ".webp", ".bmp", ".tiff"}:
        return guessed

    # Fall back to reading the extension directly from the URL path
    url_ext = os.path.splitext(urlparse(fallback_url).path)[1].lower()
    if url_ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}:
        if url_ext == ".jpeg":
            return ".jpg"
        if url_ext == ".tif":
            return ".tiff"
        return url_ext

    return ".jpg"  # if all else fails, assume JPEG (most Pinterest images are)


def download_images(
    image_candidates: Iterable[ImageCandidate],
    output_dir: str,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> None:
    """Download every collected image URL to disk, skipping ones already saved."""
    os.makedirs(output_dir, exist_ok=True)
    session = build_requests_session()

    # Deduplicate URLs in case multiple boards had the same pin
    unique_urls = sorted({candidate.url for candidate in image_candidates})
    total = len(unique_urls)
    print(f"\nStarting download of {total} unique images into: {output_dir}\n")

    downloaded = 0
    skipped_existing = 0
    failed = 0

    for index, url in enumerate(unique_urls, start=1):
        # Use a hash of the URL as the filename so re-runs skip already-downloaded files
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
        basename = f"pin_{url_hash}"

        # Build a fallback list: try 736x first, then /originals/ if we get a 403
        urls_to_try = [url]
        if PREFERRED_RESOLUTION in url:
            urls_to_try.append(url.replace(f"/{PREFERRED_RESOLUTION}/", "/originals/"))

        success = False
        for attempt_url in urls_to_try:
            try:
                response = session.get(attempt_url, timeout=timeout)
                if response.status_code == 403 and attempt_url != urls_to_try[-1]:
                    continue  # 403 on preferred res → try originals next
                response.raise_for_status()
                ext = infer_extension_from_response(response, attempt_url)
                filepath = os.path.join(output_dir, basename + ext)

                if os.path.exists(filepath):
                    skipped_existing += 1
                    print(f"[{index}/{total}] Skipping existing: {os.path.basename(filepath)}")
                    success = True
                    break

                with open(filepath, "wb") as f:
                    f.write(response.content)  # write raw bytes

                downloaded += 1
                print(f"[{index}/{total}] Saved: {os.path.basename(filepath)}")
                success = True
                break

            except requests.RequestException:
                continue  # network error on this URL, try the next one

        if not success:
            failed += 1
            print(f"[{index}/{total}] Failed: {url}")

    print("\nDone.")
    print(f"Downloaded:      {downloaded}")
    print(f"Already existed: {skipped_existing}")
    print(f"Failed:          {failed}")
    print(f"Output folder:   {output_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Define and parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Download images from public Pinterest boards and sections."
    )
    parser.add_argument(
        "--url",
        nargs="+",                 # accepts one or more URLs
        help="One or more Pinterest board or section URLs.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Folder where images will be saved. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",       # flag, no value needed
        help="Show Chrome instead of running headless (useful for debugging).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_REQUEST_TIMEOUT,
        help=f"Per-image HTTP timeout in seconds. Default: {DEFAULT_REQUEST_TIMEOUT}",
    )
    parser.add_argument(
        "--auto-subdir",
        action="store_true",
        help=(
            "Create a subfolder inside --output-dir based on the first URL. "
            "Useful when you want separate folders for different runs."
        ),
    )
    return parser.parse_args(argv)


def prompt_for_urls() -> List[str]:
    """Ask the user to paste URLs if none were provided on the command line."""
    print("Paste one or more Pinterest board/section URLs separated by spaces:")
    raw = input("> ").strip()
    return [item for item in raw.split() if item]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point: parse args, run the browser, collect pins, download images."""
    args = parse_args(argv)
    urls = args.url or prompt_for_urls()  # use CLI args or fall into interactive mode

    if not urls:
        print("No URLs provided.")
        return 1

    # Basic sanity check before starting Chrome
    invalid_urls = [url for url in urls if not url.startswith(("http://", "https://"))]
    if invalid_urls:
        print("These URLs do not look valid:")
        for url in invalid_urls:
            print(f"  - {url}")
        return 1

    output_dir = args.output_dir
    if args.auto_subdir:
        output_dir = os.path.join(output_dir, slug_from_url(urls[0]))  # e.g. pinterest_downloads/username__boardname

    try:
        driver = build_driver(headless=not args.show_browser)
    except WebDriverException as exc:
        print("Failed to start Chrome via Selenium.")
        print("Make sure Chrome is installed, then upgrade Selenium:")
        print("  pip install -U selenium")
        print(f"\nOriginal error:\n{exc}")
        return 2

    try:
        all_candidates: Set[ImageCandidate] = set()
        for url in urls:
            all_candidates.update(collect_images_from_page(driver=driver, page_url=url))
    finally:
        driver.quit()  # always close the browser, even if something crashed

    if not all_candidates:
        print("No Pinterest images were found.")
        print("Possible reasons: the page is private, Pinterest changed its API, or board_id could not be found.")
        print("Try running with --show-browser to debug.")
        return 3

    download_images(all_candidates, output_dir=output_dir, timeout=args.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())  # pass the return code to the shell (0 = success, nonzero = error)