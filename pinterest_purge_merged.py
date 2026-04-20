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
#   - If Selenium still fails to launch Chrome on your machine, the usual causes are:
#       1) Chrome is not installed
#       2) Chrome is blocked by corporate / local environment policy
#       3) Selenium is very old
#     In that case, first upgrade Selenium:
#         pip install -U selenium
#
# Examples:
#   Download a whole board:
#       python pinterest_purge_merged.py --url "https://www.pinterest.com/username/board-name/"
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
#   - This script is for PUBLIC Pinterest pages.
#   - Board or section does not matter much here. The script just opens the Pinterest page
#     you give it and scrapes whatever pin images are loaded there.
#   - Because of that, it is not perfect. It may download extra images, such as
#     Pinterest recommendation content or other page images that happen to load.
#   - It may also miss some images if Pinterest does not load them, lazy-loads them
#     differently, or changes its page structure.
#   - Pinterest can change its page structure at any time, which may break scraping.
#   - If a board is very large, you may need to raise --max-scrolls or --idle-scroll-limit.

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

PINTEREST_HOST_SNIPPET = "pinimg.com"
DEFAULT_OUTPUT_DIR = "pinterest_downloads"
DEFAULT_WINDOW_SIZE = "1920,3000"
DEFAULT_PAGE_LOAD_WAIT = 15
DEFAULT_SCROLL_PAUSE = 2.5
DEFAULT_MAX_SCROLLS = 60
DEFAULT_IDLE_SCROLL_LIMIT = 4
DEFAULT_REQUEST_TIMEOUT = 30


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    source_page: str
    alt: str = ""


SIZE_SEGMENT_PATTERN = re.compile(r"/(?:\d+x|originals)/")


def build_requests_session() -> requests.Session:
    """Create a requests session with retries and a browser-like user agent."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            )
        }
    )
    return session


def build_driver(headless: bool = True, window_size: str = DEFAULT_WINDOW_SIZE) -> webdriver.Chrome:
    """Create a Chrome WebDriver instance.

    Modern Selenium uses Selenium Manager, so ChromeDriver usually does not need to be installed manually.
    """
    options = Options()
    if headless:
        # `--headless=new` is preferred on recent Chrome builds.
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(f"--window-size={window_size}")
    options.add_argument("--lang=en-US")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=options)


def normalize_pin_image_url(url: str) -> Optional[str]:
    """Convert Pinterest image URLs to originals when possible and strip query strings."""
    if not url or PINTEREST_HOST_SNIPPET not in url:
        return None

    parsed = urlparse(url)
    clean_path = SIZE_SEGMENT_PATTERN.sub("/originals/", parsed.path)
    clean_url = f"{parsed.scheme}://{parsed.netloc}{clean_path}"
    return clean_url


def is_probably_real_pin_image(url: str, alt: str = "") -> bool:
    """Filter out obvious non-pin assets like avatars, logos, and placeholders."""
    lowered = url.lower()
    alt_lower = alt.lower()

    if PINTEREST_HOST_SNIPPET not in lowered:
        return False

    skip_words = ["avatar", "profile", "logo", "75x75rs", "icons", "static"]
    if any(word in lowered for word in skip_words):
        return False

    skip_alt_words = ["recommended", "similar", "more like this"]
    if any(word in alt_lower for word in skip_alt_words):
        return False

    return True


def infer_extension_from_response(response: requests.Response, fallback_url: str) -> str:
    """Choose a safe file extension from the HTTP content type or URL."""
    content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(content_type) if content_type else None

    if guessed in {".jpe", ".jpeg"}:
        return ".jpg"
    if guessed in {".jpg", ".png", ".gif", ".webp", ".bmp", ".tiff"}:
        return guessed

    url_ext = os.path.splitext(urlparse(fallback_url).path)[1].lower()
    if url_ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}:
        if url_ext == ".jpeg":
            return ".jpg"
        if url_ext == ".tif":
            return ".tiff"
        return url_ext

    return ".jpg"


def slug_from_url(url: str) -> str:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if not path_parts:
        return "pinterest"
    slug = "__".join(path_parts[-3:])
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", slug)
    return slug[:80] or "pinterest"


def gather_image_candidates_from_dom(driver: webdriver.Chrome, page_url: str) -> Set[ImageCandidate]:
    """Extract candidate image URLs from the current DOM.

    JS is used here because it is faster than repeatedly calling WebElement methods from Python.
    """
    raw_items = driver.execute_script(
        """
        const nodes = Array.from(document.querySelectorAll('img'));
        return nodes.map(img => ({
            src: img.currentSrc || img.src || '',
            alt: img.alt || ''
        }));
        """
    )

    results: Set[ImageCandidate] = set()
    for item in raw_items:
        src = (item.get("src") or "").strip()
        alt = (item.get("alt") or "").strip()
        if not src or not is_probably_real_pin_image(src, alt):
            continue

        normalized = normalize_pin_image_url(src)
        if not normalized:
            continue

        results.add(ImageCandidate(url=normalized, source_page=page_url, alt=alt))

    return results


def collect_images_from_page(
    driver: webdriver.Chrome,
    page_url: str,
    page_load_wait: float,
    scroll_pause: float,
    max_scrolls: int,
    idle_scroll_limit: int,
) -> Set[ImageCandidate]:
    """Visit one board or section URL and collect pin image URLs."""
    print(f"\n{'=' * 80}")
    print(f"Loading: {page_url}")
    print(f"{'=' * 80}")

    driver.get(page_url)

    wait = WebDriverWait(driver, page_load_wait)
    try:
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "img")))
    except TimeoutException:
        print("Timed out waiting for Pinterest images to appear on the page.")

    time.sleep(scroll_pause)

    found: Set[ImageCandidate] = set()
    idle_scrolls = 0
    last_height = driver.execute_script("return document.body.scrollHeight")

    for scroll_index in range(max_scrolls):
        before_count = len(found)
        found.update(gather_image_candidates_from_dom(driver, page_url))
        after_count = len(found)
        new_count = after_count - before_count

        print(
            f"Scroll {scroll_index + 1}/{max_scrolls}: "
            f"{after_count} total unique images (+{new_count} this round)"
        )

        if new_count == 0:
            idle_scrolls += 1
        else:
            idle_scrolls = 0

        if idle_scrolls >= idle_scroll_limit:
            print("Stopping early: hit idle scroll limit with no new images.")
            break

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_pause)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height and idle_scrolls > 0:
            print("Reached bottom of page or Pinterest stopped loading more content.")
            break
        last_height = new_height

    # Final sweep after scrolling finishes.
    final_before = len(found)
    found.update(gather_image_candidates_from_dom(driver, page_url))
    final_added = len(found) - final_before
    if final_added:
        print(f"Final sweep added {final_added} more images.")

    print(f"Collected {len(found)} unique images from this page.")
    return found


def download_images(
    image_candidates: Iterable[ImageCandidate],
    output_dir: str,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> None:
    """Download unique images to disk, preserving type and avoiding duplicate files."""
    os.makedirs(output_dir, exist_ok=True)
    session = build_requests_session()

    unique_urls = sorted({candidate.url for candidate in image_candidates})
    total = len(unique_urls)
    print(f"\nStarting download of {total} unique images into: {output_dir}\n")

    downloaded = 0
    skipped_existing = 0
    failed = 0

    for index, url in enumerate(unique_urls, start=1):
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
        basename = f"pin_{url_hash}"

        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            ext = infer_extension_from_response(response, url)
            filepath = os.path.join(output_dir, basename + ext)

            if os.path.exists(filepath):
                skipped_existing += 1
                print(f"[{index}/{total}] Skipping existing file: {os.path.basename(filepath)}")
                continue

            with open(filepath, "wb") as f:
                f.write(response.content)

            downloaded += 1
            print(f"[{index}/{total}] Saved: {os.path.basename(filepath)}")

        except requests.RequestException as exc:
            failed += 1
            print(f"[{index}/{total}] Failed to download {url}\n  -> {exc}")

    print("\nDone.")
    print(f"Downloaded: {downloaded}")
    print(f"Already existed: {skipped_existing}")
    print(f"Failed: {failed}")
    print(f"Output folder: {output_dir}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download images from public Pinterest boards and sections."
    )
    parser.add_argument(
        "--url",
        nargs="+",
        help="One or more Pinterest board or section URLs.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Folder where images will be saved. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=DEFAULT_MAX_SCROLLS,
        help=f"Maximum number of scroll cycles per page. Default: {DEFAULT_MAX_SCROLLS}",
    )
    parser.add_argument(
        "--scroll-pause",
        type=float,
        default=DEFAULT_SCROLL_PAUSE,
        help=f"Seconds to wait after each scroll. Default: {DEFAULT_SCROLL_PAUSE}",
    )
    parser.add_argument(
        "--idle-scroll-limit",
        type=int,
        default=DEFAULT_IDLE_SCROLL_LIMIT,
        help=(
            "Stop early after this many scrolls in a row with no new images. "
            f"Default: {DEFAULT_IDLE_SCROLL_LIMIT}"
        ),
    )
    parser.add_argument(
        "--page-load-wait",
        type=float,
        default=DEFAULT_PAGE_LOAD_WAIT,
        help=f"Seconds to wait for the page to start rendering images. Default: {DEFAULT_PAGE_LOAD_WAIT}",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Show Chrome instead of running headless.",
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
    print("Paste one or more Pinterest board/section URLs separated by spaces:")
    raw = input("> ").strip()
    return [item for item in raw.split() if item]


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    urls = args.url or prompt_for_urls()

    if not urls:
        print("No URLs provided.")
        return 1

    invalid_urls = [url for url in urls if not url.startswith(("http://", "https://"))]
    if invalid_urls:
        print("These URLs do not look valid:")
        for url in invalid_urls:
            print(f"  - {url}")
        return 1

    output_dir = args.output_dir
    if args.auto_subdir:
        output_dir = os.path.join(output_dir, slug_from_url(urls[0]))

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
            all_candidates.update(
                collect_images_from_page(
                    driver=driver,
                    page_url=url,
                    page_load_wait=args.page_load_wait,
                    scroll_pause=args.scroll_pause,
                    max_scrolls=args.max_scrolls,
                    idle_scroll_limit=args.idle_scroll_limit,
                )
            )
    finally:
        driver.quit()

    if not all_candidates:
        print("No Pinterest images were found.")
        print("Possible reasons: the page is private, Pinterest changed its DOM, or more scrolls are needed.")
        return 3

    download_images(all_candidates, output_dir=output_dir, timeout=args.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
