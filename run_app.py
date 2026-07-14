"""Desktop entry point for PyInstaller bundles.

Dev workflow:     uvicorn app.main:app --reload
Release build:    make build
"""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

import uvicorn

import app.main  # ensures PyInstaller bundles FastAPI + deps
from app.config import _user_env_dir


def _is_bundled() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_root() -> Path:
    if _is_bundled():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


if __name__ == "__main__":
    # Credentials always live in the OS user-data folder, never next to source files.
    env_dir = _user_env_dir()
    env_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TASTIER_ENV_DIR"] = str(env_dir)

    # When PyInstaller builds with console=False, stdout/stderr are None and
    # uvicorn's logging crashes; redirect them to a per-user log file.
    # Line-buffered so a hard crash doesn't swallow the buffered tail, and
    # with faulthandler enabled so silent/native deaths leave a traceback.
    if _is_bundled():
        import faulthandler
        log_path = env_dir / "tastier.log"
        sys.stdout = sys.stderr = open(log_path, "a", encoding="utf-8",
                                       buffering=1)
        faulthandler.enable(sys.stderr)

    # In release builds we change cwd so static files and logos resolve.
    os.chdir(bundle_root())

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8420"))
    url = f"http://{host}:{port}"
    print(f"Tastier starting at {url}")
    print(f"Config directory: {env_dir}")
    webbrowser.open(url)
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
