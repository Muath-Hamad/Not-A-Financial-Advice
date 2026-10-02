"""Where the console finds things. Every path can be overridden from the
environment so the container can point at its own ledger clone (docs/08 §3.3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
# NASDAQ/ in the repository; /app/NASDAQ in the container.
DEFAULT_PKG = HERE.parents[2]


@dataclass(frozen=True)
class Settings:
    pkg: Path = field(default_factory=lambda: Path(os.environ.get("CONSOLE_PKG_DIR") or DEFAULT_PKG))
    ledger: Path | None = None
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("CONSOLE_DB") or (HERE.parent / "console.db")))
    static_dir: Path | None = field(default_factory=lambda: Path(p) if (p := os.environ.get("CONSOLE_STATIC_DIR")) else None)
    # Pull the ledger clone with `git pull --ff-only` on every index pass.
    git_pull: bool = field(default_factory=lambda: os.environ.get("CONSOLE_GIT_PULL", "0") == "1")
    index_every_s: int = field(default_factory=lambda: int(os.environ.get("CONSOLE_INDEX_EVERY_S", "60")))
    # M0 has no login yet (M1 adds argon2 + TOTP); the role is fixed per deployment.
    role: str = field(default_factory=lambda: os.environ.get("CONSOLE_ROLE", "owner"))
    user: str = field(default_factory=lambda: os.environ.get("CONSOLE_USER", "owner@console"))

    @property
    def ledger_dir(self) -> Path:
        if self.ledger:
            return self.ledger
        env = os.environ.get("LIVE_LEDGER_DIR")
        return Path(env) if env else self.pkg / "live" / "ledger"

    @property
    def repo_root(self) -> Path:
        return self.pkg.parent
