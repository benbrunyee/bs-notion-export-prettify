import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def ensure_chromium_installed():
    """Check if Playwright's Chromium browser is installed and install it if not."""
    with sync_playwright() as p:
        executable = p.chromium.executable_path

    if Path(executable).exists():
        return

    print("Playwright Chromium browser not found. Installing now...")
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )
    print("Chromium installation complete.")
