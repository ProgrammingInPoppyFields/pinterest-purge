# 🌸🌼🌷 PROGRAMMING IN POPPY FIELDS 🌷🌼🌸
# pinterest_purge_BY_BOARD.py
#
# Downloads every image from a public Pinterest board
# Paste in a board URL, run the script, walk away
# Images land in a folder called "pinterest_downloads" (or whatever you rename it to)
#
# REQUIREMENTS: pip install selenium requests
# You also need Chrome installed on your computer


import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urlparse, parse_qs
import hashlib


def download_pinterest_board(board_url, output_dir="pinterest_downloads"):
    # TODO: Adjust output_dir to rename the folder where images get saved

    # Create the output folder if it doesn't already exist
    os.makedirs(output_dir, exist_ok=True)

    # Configure Chrome to run invisibly in the background (no browser window will pop up)
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    # TODO: Adjust window size if needed (affects how Pinterest renders the page)
    options.add_argument('--window-size=1920,1080')

    # Launch the invisible Chrome browser
    driver = webdriver.Chrome(options=options)

    try:
        print(f"Loading board: {board_url}")

        # Tell the browser to go to the Pinterest board URL
        driver.get(board_url)

        # Wait up to 10 seconds for at least one image to appear before doing anything else
        # TODO: Adjust the 10 if Pinterest is loading slowly and timing out
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "img")))

        print("Scrolling to load all pins...")

        # This is a set — it automatically ignores duplicates so each image URL only gets stored once
        image_urls = set()

        # TODO: Adjust scroll_pause — how many seconds to wait after each scroll before grabbing images
        scroll_pause = 5

        # TODO: Adjust max_scrolls — how many times to scroll down the page (more scrolls = more pins loaded)
        max_scrolls = 1

        # Loop from 0 up to max_scrolls (inclusive), collecting images at each scroll position
        for scroll_count in range(0, max_scrolls + 1):

            if scroll_count > 0:
                # Jump to the very bottom of the page to trigger Pinterest to load more pins
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

                # Wait for the new pins to actually appear before we try to grab them
                time.sleep(scroll_pause)

            # Run a small snippet of JavaScript inside the browser to find every image on the page
            # and return their URL (src) and description text (alt)
            img_data = driver.execute_script("""
                let imgs = document.querySelectorAll('img');
                let data = [];
                imgs.forEach(img => {
                    if (img.src) {
                        data.push({
                            src: img.src,
                            alt: img.alt || ''
                        });
                    }
                });
                return data;
            """)

            for img_info in img_data:
                src = img_info['src']
                alt = img_info['alt']

                # Pinterest image URLs contain size codes like "236x" or "474x" — we use that
                # to identify actual pin images vs other stuff on the page (icons, UI elements, etc)
                if src and ("236x" in src or "474x" in src or "736x" in src):

                    # Skip profile pictures and site logos — those aren't pins
                    if any(skip in src.lower() for skip in ['avatar', 'profile', 'logo']):
                        continue

                    # Skip images labeled as recommendations or suggestions — those aren't from your board
                    if any(skip in alt.lower() for skip in ['recommended', 'similar', 'more like']):
                        continue

                    # Swap the size code in the URL for "originals" to get the highest quality version
                    high_res_src = src.replace("236x", "originals").replace("474x", "originals").replace("736x", "originals")
                    image_urls.add(high_res_src)

            if scroll_count == 0:
                print(f"Initial load - Found {len(image_urls)} unique images...")
            else:
                print(f"Scroll {scroll_count}/{max_scrolls} - Found {len(image_urls)} unique images so far...")

        print(f"\nTotal images found: {len(image_urls)}")
        print("Downloading images...")

        downloaded = 0
        for idx, url in enumerate(image_urls, 1):
            try:
                # Generate a short unique ID from the image URL so two different images never
                # accidentally get saved with the same filename
                url_hash = hashlib.md5(url.encode()).hexdigest()[:10]

                # Pull the file extension from the URL (usually .jpg), default to .jpg if missing
                ext = os.path.splitext(urlparse(url).path)[1] or '.jpg'

                filename = f"pin_{url_hash}{ext}"
                filepath = os.path.join(output_dir, filename)

                # If this image was already downloaded in a previous run, skip it
                if os.path.exists(filepath):
                    continue

                # Actually fetch the image from the internet and save it to disk
                # TODO: Adjust timeout (10 seconds) if your connection is slow and images are failing
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    downloaded += 1
                    print(f"Downloaded {downloaded}/{len(image_urls)}: {filename}")

            except Exception as e:
                print(f"Error downloading {url}: {e}")

        print(f"\n✓ Download complete! {downloaded} images saved to '{output_dir}'")

    finally:
        # Always close the invisible browser when done, even if something went wrong
        driver.quit()


if __name__ == "__main__":
    board_url = input("Enter Pinterest board URL: ").strip()

    if not board_url:
        print("No URL provided. Example URL format:")
        print("https://www.pinterest.com/username/board-name/")
    else:
        download_pinterest_board(board_url)
