# 📌 Pinterest Purge

<img src="https://images.unsplash.com/photo-1591178761188-885caa0b4fc3?q=80&w=1758&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D" alt="hero" width="100%" style="height:auto;object-fit:cover;display:block;" />

A Pinterest image downloader for **public boards** and **public board sections**.

This project uses one merged script:

- `pinterest_purge_merged.py` — downloads images from one or more Pinterest board or section URLs

---

## How it works

Instead of scraping the rendered page (which misses pins due to Pinterest's virtual scrolling), the script:

1. Opens the board in Chrome with Selenium — just long enough to harvest session cookies and the board's internal numeric ID
2. Calls Pinterest's internal `BoardFeedResource` JSON API directly, paginating through all pins using bookmark tokens
3. Downloads the collected image URLs to disk

This means it gets **all** pins in a board, not just the ones that happened to be visible on screen — and it only collects actual board pins, not profile pictures, suggested content, or anything else.

---

## What it does

Given one or more Pinterest URLs, the script:

- uses Chrome to authenticate and extract the board ID
- paginates Pinterest's internal API until all pins are collected
- downloads images at 736x resolution (high quality, reliable)
- falls back to `/originals/` if 736x returns a 403
- skips images already saved from a previous run

It works for:

- public Pinterest boards
- public Pinterest sections inside boards

It will not work for:

- private boards
- login-gated content

---

## Requirements

- Python 3.10+
- Google Chrome installed
- Python packages: `selenium`, `requests`

```bash
pip install -U selenium requests
```

Modern Selenium handles ChromeDriver automatically — no manual install needed in most cases.

---

## How to run

### Download a whole board

```bash
python pinterest_purge_merged.py --url "https://www.pinterest.com/username/board-name/"
```

### Download a board section

```bash
python pinterest_purge_merged.py --url "https://www.pinterest.com/username/board-name/section-name/"
```

### Download multiple sections into one folder

```bash
python pinterest_purge_merged.py --url \
  "https://www.pinterest.com/username/board-name/section-one/" \
  "https://www.pinterest.com/username/board-name/section-two/"
```

### Interactive mode (no arguments)

```bash
python pinterest_purge_merged.py
```

---

## Options

| Flag | Default | What it does |
|---|---|---|
| `--url` | *(prompted)* | One or more Pinterest board or section URLs |
| `--output-dir` | `pinterest_downloads` | Folder to save images into |
| `--auto-subdir` | off | Creates a subfolder named after the first URL (good for keeping multiple runs separate) |
| `--show-browser` | off | Shows the Chrome window instead of running headless — useful for debugging |
| `--timeout` | `30` | Per-image download timeout in seconds |

---

## Notes

- **Public pages only.** Private boards and login-gated content are not supported.
- **`/originals/` often 403s** as of 2025. Images download at `736x` resolution with an automatic originals fallback.
- **Re-running is safe.** Already-downloaded files are detected by filename and skipped.
- **Pinterest can change their API.** If the script suddenly stops finding images, run with `--show-browser` to see what's happening, and check for script updates.

---

## Quick start

```bash
pip install -U selenium requests
python pinterest_purge_merged.py --url "https://www.pinterest.com/username/cool-board/"
```

---