# 📌 Pinterest Purge

<img src="https://images.unsplash.com/photo-1591178761188-885caa0b4fc3?q=80&w=1758&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D" alt="hero" width="100%" style="height:300px;object-fit:cover;display:block;" />

A simple Pinterest image downloader for **public boards** and **public board sections**.

This project now uses **one merged script**:

- `pinterest_purge_merged.py` — downloads images from one or more Pinterest board or section URLs

Important note:
- The script does not care whether a URL is a board or a section.
- It simply opens the Pinterest page you give it and scrapes whatever pin images are loaded there.

---

## What it does

Given one or more Pinterest URLs, the script:

- opens the page in Chrome using Selenium
- scrolls to load more pins
- finds Pinterest image URLs
- upgrades them to higher-resolution originals when possible
- downloads the images to a local folder
- skips duplicates

It works best for:

- public Pinterest boards
- public Pinterest sections inside boards

It may not work for:

- private boards
- login-gated content
- pages Pinterest changes in the future

---

## Files in this folder

### `pinterest_purge_merged.py`
Use this one.

Handles:
- full boards
- board sections
- multiple URLs in one run

Includes:
- retries
- deduping
- safer filenames
- better scrolling
- command-line options

### `pinterest_purge_BY_BOARD.py`
Older script for downloading from an entire board.

### `pinterest_purge_BY_SECTION.py`
Older script for downloading from one or more board sections.

---

## Requirements

You need:

- Python 3.10+
- Google Chrome installed
- Python packages:
  - `selenium`
  - `requests`

Install the Python packages with:

```bash
pip install -U selenium requests
```

In most cases, you do **not** need to manually install ChromeDriver.
Modern Selenium usually handles that automatically.

---

## How to run

### Download from one board

```bash
python pinterest_purge_merged.py --url "https://www.pinterest.com/username/board-name/"
```

### Download from multiple sections

```bash
python pinterest_purge_merged.py --url \
  "https://www.pinterest.com/username/board-name/section-one/" \
  "https://www.pinterest.com/username/board-name/section-two/"
```

### Show the browser window while it runs

```bash
python pinterest_purge_merged.py --url "PASTE_URL_HERE" --show-browser
```

---

## Useful options

### Choose output folder

```bash
python pinterest_purge_merged.py --url "PASTE_URL_HERE" --output-dir my_images
```

### Control scrolling

```bash
python pinterest_purge_merged.py --url "PASTE_URL_HERE" --max-scrolls 40 --scroll-pause 2.0
```

---

## Notes

- The script downloads from **public Pinterest pages** only.
- Board or section does not matter much to the scraper. It just opens the page and scrapes whatever images are there.
- It is not perfect. You may get extra images, such as Pinterest recommendation content or other page images that happen to load.
- It is also possible to miss some images if Pinterest does not load them, lazy-loads them differently, or changes the page structure.
- Pinterest can change its site structure at any time, so scrapers like this can break.
- If a page stops yielding new images, the script exits early instead of scrolling forever.
- Re-running the script is usually safe because it deduplicates by image URL.

---

## Quick start

1. Install Chrome
2. Install Python packages
3. Run the merged script with a board or section URL
4. Check the output folder for downloaded images

---

## Example

```bash
pip install -U selenium requests
python pinterest_purge_merged.py --url "https://www.pinterest.com/username/cool-board/"
```

---
