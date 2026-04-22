"""Take screenshots of the Poolbridge Streamlit app for the README."""

from playwright.sync_api import sync_playwright
import time

CHROMIUM_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=CHROMIUM_PATH,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8501", wait_until="networkidle")

    # Give Streamlit's React UI time to fully paint
    time.sleep(4)
    page.wait_for_selector("[data-testid='stSidebar']", timeout=15000)
    time.sleep(2)

    # 1. Full-app overview
    page.screenshot(path="assets/screenshot-full.png", full_page=False)
    print("Saved screenshot-full.png")

    # 2. Sidebar close-up (top: CRS + localization)
    sidebar = page.locator("[data-testid='stSidebar']")
    sidebar.screenshot(path="assets/screenshot-sidebar.png")
    print("Saved screenshot-sidebar.png")

    # 3. Scroll sidebar to show Z datum + contour controls
    page.locator("[data-testid='stSidebar']").evaluate(
        "el => el.scrollTop = el.scrollHeight"
    )
    time.sleep(0.5)
    sidebar.screenshot(path="assets/screenshot-sidebar-bottom.png")
    print("Saved screenshot-sidebar-bottom.png")

    browser.close()

print("Done.")
