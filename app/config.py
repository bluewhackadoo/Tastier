"""Configuration: loads credentials from .env, never from code.

Security model (localhost):
- Credentials live only in .env (chmod 600, gitignored).
- Server binds 127.0.0.1 only.
- Browser never receives tokens; it talks only to this backend.
- OAuth grant should be created with the read-only scope.
"""

import os
import stat
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

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


settings = Settings()
