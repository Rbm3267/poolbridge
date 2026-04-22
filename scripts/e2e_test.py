"""End-to-end Playwright test: upload real NC survey CSV and run conversion."""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

CSV_PATH = str(Path("test_data/medway/Medway GIS/medway corners.csv").resolve())
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=CHROMIUM,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8502", wait_until="networkidle")
    time.sleep(4)
    page.wait_for_selector("[data-testid='stSidebar']", timeout=15000)
    time.sleep(1)

    # --- Select NC State Plane in sidebar ---
    # Click the CRS selectbox
    page.locator("[data-testid='stSidebar'] [data-baseweb='select']").first.click()
    time.sleep(1)
    # Type NC to filter
    page.keyboard.type("NC State")
    time.sleep(0.5)
    page.keyboard.press("Enter")
    time.sleep(0.5)

    # Uncheck "Convert to US survey feet" (already in ft) — click the label
    checkbox_label = page.locator("[data-testid='stSidebar'] .stCheckbox label").first
    checkbox_input = page.locator("[data-testid='stSidebar'] .stCheckbox input").first
    if checkbox_input.is_checked():
        checkbox_label.click()
    time.sleep(0.3)

    # --- Upload the CSV ---
    file_input = page.locator("[data-testid='stFileUploader'] input[type='file']").first
    file_input.set_input_files(CSV_PATH)
    time.sleep(3)
    page.wait_for_selector("text=24 points loaded", timeout=10000)
    print("File uploaded successfully — 24 points loaded")

    # Screenshot after upload
    page.screenshot(path="assets/screenshot-upload.png")
    print("Saved screenshot-upload.png")

    # --- Click Convert ---
    page.locator("button:has-text('Convert to DXF')").click()
    time.sleep(6)
    page.wait_for_selector("text=24 points", timeout=20000)
    print("Conversion complete")

    # Screenshot of results
    page.screenshot(path="assets/screenshot-results.png")
    print("Saved screenshot-results.png")

    browser.close()

print("Done.")
