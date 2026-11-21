"""Screenshot of the kit's window, headless (no window opens, focus is not taken).

    python3 docs/gallery/shot_gui.py http://127.0.0.1:8792/ docs/images/tour/gui-window.png

Playwright driving the installed Google Chrome in headless mode, 1440x1000.
make_gui_shot.sh starts the server against stand-in discs first.
New for this kit; nothing borrowed.
"""
import sys

from playwright.sync_api import sync_playwright

url, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                          headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    pg.goto(url)
    pg.wait_for_timeout(2500)
    pg.screenshot(path=out)
    b.close()
