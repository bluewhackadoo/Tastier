"""Configuration: loads credentials from .env, never from code.

Security model (localhost):
- Credentials live only in .env inside the OS user-data folder:
    Windows: %LOCALAPPDATA%\Tastier\.env
    macOS:   ~/Library/Application Support/Tastier/.env
    Linux:   ~/.local/share/Tastier/.env
- Server binds 127.0.0.1 only.
- Browser never receives tokens; it talks only to this backend.
- OAuth grant should be created with the read-only scope.
"""

import os
import stat
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _user_env_dir() -> Path:
    """Per-user directory for the local .env file.

    Windows: %LOCALAPPDATA%\Tastier
    macOS:   ~/Library/Application Support/Tastier
    Linux:   ~/.local/share/Tastier
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / "Tastier"


# Credentials live outside the project folder so they are never mixed with
# source files or accidentally committed. Override with TASTIER_ENV_DIR.
ENV_DIR = Path(os.environ.get("TASTIER_ENV_DIR", _user_env_dir()))
ENV_PATH = ENV_DIR / ".env"

load_dotenv(ENV_PATH)


class Settings:
    def __init__(self) -> None:
        self.tt_secret: str = os.environ.get("TT_SECRET", "")
        self.tt_refresh: str = os.environ.get("TT_REFRESH", "")
        # "paper" -> cert environment (sandbox), "live" -> production (still read-only)
        self.tt_env: str = os.environ.get("TT_ENV", "paper").lower()
        self.host: str = "127.0.0.1"  # hard-coded on purpose; do not expose
        self.port: int = int(os.environ.get("PORT", "8420"))

    @property
    def is_test(self) -> bool:
        return self.tt_env != "live"

    def validate(self) -> list[str]:
        """Return a list of human-readable problems; empty list means OK."""
        problems: list[str] = []
        if not self.tt_secret:
            problems.append("TT_SECRET is missing from .env")
        if not self.tt_refresh:
            problems.append("TT_REFRESH is missing from .env")
        if self.tt_env not in ("paper", "live"):
            problems.append(f"TT_ENV must be 'paper' or 'live', got '{self.tt_env}'")
        if os.name != "nt" and ENV_PATH.exists():
            mode = stat.S_IMODE(ENV_PATH.stat().st_mode)
            if mode & 0o077:
                problems.append(
                    f".env permissions are {oct(mode)}; run: chmod 600 {ENV_PATH}"
                )
        return problems


def save_credentials(secret: str, refresh: str, env: str) -> None:
    """Persist user-supplied tastytrade credentials to the local .env file.

    This is only used by the release binary setup flow. The browser talks to
    the local backend, so the credentials never leave the user's machine.
    """
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    seen = {"TT_SECRET", "TT_REFRESH", "TT_ENV"}
    if ENV_PATH.exists():
        # keep one generation of backup so a bad save can't destroy the only
        # copy of working credentials
        backup = ENV_PATH.parent / ".env.bak"
        backup.write_bytes(ENV_PATH.read_bytes())
        if os.name != "nt":
            backup.chmod(0o600)
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip()
            if key in seen:
                continue
            lines.append(line)
    lines.append(f'TT_SECRET={secret}')
    lines.append(f'TT_REFRESH={refresh}')
    lines.append(f'TT_ENV={env}')
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        ENV_PATH.chmod(0o600)


settings = Settings()
