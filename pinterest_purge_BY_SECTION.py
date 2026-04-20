# 🌸🌼🌷 PROGRAMMING IN POPPY FIELDS 🌷🌼🌸
# pinterest_purge_BY_SECTION.py
#
# Downloads every image from one or more Pinterest board SECTIONS
# (Not whole boards — just specific sections within a board)
#
# HOW TO USE:
# 1. Go to a Pinterest section in your browser
# 2. Copy the URL — it'll look like: https://www.pinterest.com/username/board-name/section-name/
# 3. Run this script and paste your URLs separated by spaces when prompted
# 4. Images land in a folder called "pinterest_images"
#
# REQUIREMENTS: pip install selenium requests
# You also need Chrome installed on your computer


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import requests
import os
from urllib.parse import unquote


def download_pinterest_sections(section_urls, output_folder="pinterest_images"):
    # TODO: Adjust output_folder to rename the folder where images get saved

    # Create the output folder if it doesn't already exist
    os.makedirs(output_folder, exist_ok=True)

    # Configure Chrome to run invisibly in the background (no browser window will pop up)
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')

    # Launch the invisible Chrome browser
    driver = webdriver.Chrome(options=options)

    # This is a set — it automatically ignores duplicates so the same image never gets downloaded twice,
    # even across multiple sections
    all_image_urls = set()

    try:
        for url in section_urls:
            url = url.strip()

            # Skip any blank entries (e.g. if someone accidentally typed an extra space)
            if not url:
                continue

            # Make sure the URL is a real web address before trying to open it
            if not url.startswith('http'):
                print(f"Skipping invalid URL: {url}")
                continue

            print(f"\n{'='*60}")
            print(f"SECTION: {url}")
            print(f"{'='*60}")

            # Tell the browser to navigate to this section's URL
            driver.get(url)

            # TODO: Adjust this wait time (seconds) if the page isn't fully loading before the script starts scrolling
            print("Page loaded, waiting 5 seconds for content...")
            time.sleep(5)

            # Track the page height so we can detect when we've hit the bottom
            last_height = driver.execute_script("return document.body.scrollHeight")

            scroll_attempts = 0

            # TODO: Adjust max_scrolls — how many times to scroll before giving up on a section
            max_scrolls = 50

            # Counter for how many scrolls in a row found zero new images
            no_new_images_count = 0

            while scroll_attempts < max_scrolls:

                # Record how many images we have before this scroll so we can compare after
                images_before = len(all_image_urls)

                # Find every image element currently visible on the page
                images = driver.find_elements(By.TAG_NAME, 'img')

                for img in images:
                    src = img.get_attribute('src')

                    # "pinimg.com" is Pinterest's image hosting domain — if it's not from there, skip it
                    # "/originals/" in the URL means it's already the highest quality version
                    if src and 'pinimg.com' in src and '/originals/' in src:
                        if src not in all_image_urls:
                            all_image_urls.add(src)
                            print(f"  ✓ NEW IMAGE: {src}")

                    elif src and 'pinimg.com' in src:
                        # This image URL has a size code in it (like /236x/ or /474x/) — swap it
                        # for /originals/ to get the full resolution version instead
                        original_src = src.replace('/236x/', '/originals/').replace('/474x/', '/originals/')
                        if original_src not in all_image_urls:
                            all_image_urls.add(original_src)
                            print(f"  ✓ NEW IMAGE: {original_src}")

                images_after = len(all_image_urls)
                new_images = images_after - images_before

                print(f"\n  📊 Scroll #{scroll_attempts + 1}: {len(all_image_urls)} total images (+{new_images} new this scroll)")

                if new_images == 0:
                    no_new_images_count += 1

                    # If three scrolls in a row found nothing new, assume this section is fully loaded
                    if no_new_images_count >= 3:
                        print("  ⚠️  No new images after 3 attempts, moving on!")
                        break

                    # TODO: Adjust this extra wait time (seconds) when a scroll finds no new images
                    print("  ⏳ No new images, waiting 2 more seconds...")
                    time.sleep(2)

                else:
                    # Reset the counter since we did find something new
                    no_new_images_count = 0

                # Scroll the page down by 1000 pixels to reveal the next batch of pins
                # TODO: Adjust 1000 if you want bigger or smaller scroll steps
                print("  ⬇️  Scrolling down 1000 pixels...")
                driver.execute_script("window.scrollBy(0, 1000);")

                # TODO: Adjust this wait time (seconds) between scrolls — too short and images won't load in time
                print("  ⏳ Waiting 3 seconds for new content to load...")
                time.sleep(3)

                # Check if the page got taller after scrolling (taller = more pins loaded below)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height and no_new_images_count > 0:
                    print("  ✅ Reached the bottom!")
                    break

                last_height = new_height
                scroll_attempts += 1

            # Do one final pass after scrolling is done to catch anything we might have missed
            print("\n  🔍 Final sweep for any remaining images...")
            images = driver.find_elements(By.TAG_NAME, 'img')
            for img in images:
                src = img.get_attribute('src')
                if src and 'pinimg.com' in src and '/originals/' in src:
                    if src not in all_image_urls:
                        all_image_urls.add(src)
                        print(f"  ✓ NEW IMAGE: {src}")
                elif src and 'pinimg.com' in src:
                    original_src = src.replace('/236x/', '/originals/').replace('/474x/', '/originals/')
                    if original_src not in all_image_urls:
                        all_image_urls.add(original_src)
                        print(f"  ✓ NEW IMAGE: {original_src}")

            print(f"\n  📦 Section complete: {len(all_image_urls)} total images collected")

    finally:
        # Always close the invisible browser when done, even if something went wrong
        driver.quit()

    print(f"\n{'='*60}")
    print(f"Total images found across all sections: {len(all_image_urls)}")
    print(f"{'='*60}\n")

    print("Starting downloads...\n")

    # Send a browser-like header with each request so Pinterest doesn't block us as a bot
    headers = {'User-Agent': 'Mozilla/5.0'}

    for idx, img_url in enumerate(all_image_urls, 1):
        try:
            print(f"Downloading {idx}/{len(all_image_urls)}: {img_url}")

            # Fetch the image from the internet
            img_data = requests.get(img_url, headers=headers).content

            # Name the file sequentially (pin_1.jpg, pin_2.jpg, etc)
            filename = f"pin_{idx}.jpg"
            filepath = os.path.join(output_folder, filename)

            # Write the image data to a file on your computer
            with open(filepath, 'wb') as f:
                f.write(img_data)

            print(f"  ✓ Saved as {filename}")

        except Exception as e:
            print(f"  ✗ Failed: {e}")

    print(f"\n{'='*60}")
    print(f"Done! Images saved to '{output_folder}' folder")
    print(f"{'='*60}")


if __name__ == "__main__":
    # Ask the user to paste in one or more section URLs, split them on spaces into a list
    urls_input = input("Enter Pinterest section URLs (separated by spaces): ")
    section_urls = urls_input.split()
    download_pinterest_sections(section_urls)
