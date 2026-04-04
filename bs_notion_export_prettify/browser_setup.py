import importlib.util
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright


def _find_playwright_cli() -> Path:
    """Locate the playwright CLI entry point via its package metadata.

    sys.executable is unreliable in frozen/bundled applications because it
    points to the bundle itself rather than a Python interpreter, which would
    cause the subprocess call to re-launch the bundle instead of running the
    installer. Resolving the path through the installed package is consistent
    regardless of how the application was launched.
    """
    spec = importlib.util.find_spec("playwright")
    if spec is None or spec.origin is None:
        raise RuntimeError("playwright package not found in the current environment")

    # The playwright package lives at <site-packages>/playwright/__init__.py;
    # its CLI entry point is the adjacent __main__.py.
    cli_path = Path(spec.origin).parent / "__main__.py"
    if not cli_path.exists():
        raise RuntimeError(f"playwright CLI not found at expected path: {cli_path}")
    return cli_path


def _find_python_executable() -> Path:
    """Find a reliable Python executable, independent of the current process.

    In a frozen bundle sys.executable points to the bundle; sys._base_executable
    may as well. Instead, locate the interpreter that owns the playwright
    package by walking up from its site-packages directory.
    """
    import shutil

    # Prefer the system 'python3' / 'python' on PATH, which is independent of
    # the running process and therefore safe to use for subprocess calls.
    for candidate in ("python3", "python"):
        found = shutil.which(candidate)
        if found:
            return Path(found)

    raise RuntimeError("No Python executable found on PATH to run playwright install")


def ensure_chromium_installed():
    """Check if Playwright's Chromium browser is installed and install it if not."""
    with sync_playwright() as p:
        executable = p.chromium.executable_path

    if Path(executable).exists():
        return

    print("Playwright Chromium browser not found. Installing now...")
    python_exe = _find_python_executable()
    cli_path = _find_playwright_cli()
    subprocess.run(
        [str(python_exe), str(cli_path), "install", "chromium"],
        check=True,
    )
    print("Chromium installation complete.")
