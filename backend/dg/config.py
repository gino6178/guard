"""Runtime settings, read from environment variables (prefix DG_)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.environ.get(f"DG_{name}", default)


def _read_key_file() -> str:
    p = _ROOT / "infra" / "llm-vm" / ".api_key"
    return p.read_text().strip() if p.exists() else ""


def _data_dir() -> Path:
    return Path(_env("DATA_DIR", str(_ROOT / "var")))


def _secret_key() -> str:
    """DG_SECRET_KEY, else a random key generated once per installation and kept in the data dir."""
    if key := _env("SECRET_KEY", ""):
        return key
    p = _data_dir() / "secret_key"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32))
        p.chmod(0o600)
    return p.read_text().strip()


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=_data_dir)
    secret_key: str = field(default_factory=_secret_key)
    token_hours: int = field(default_factory=lambda: int(_env("TOKEN_HOURS", "12")))

    # OpenAI-compatible endpoint (vLLM on the dedicated VM, reached through tunnel.sh)
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://127.0.0.1:18000/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", "") or _read_key_file())
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "dg-llm"))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "180")))
    llm_concurrency: int = field(default_factory=lambda: int(_env("LLM_CONCURRENCY", "8")))
    llm_enabled: bool = field(default_factory=lambda: _env("LLM_ENABLED", "1") == "1")

    default_retention_days: int = field(default_factory=lambda: int(_env("RETENTION_DAYS", "180")))
    # TEST ONLY: skip password checks; an unknown username signs in as admin
    open_login: bool = field(default_factory=lambda: _env("OPEN_LOGIN", "0") == "1")
    # OCR text-line recogniser (ONNX) and its character dictionary; empty = RapidOCR's bundled PP-OCRv4
    ocr_rec_model: str = field(default_factory=lambda: _env("OCR_REC_MODEL", str(_ROOT / "backend" / "models" / "ocr_rec.onnx")))
    ocr_rec_keys: str = field(default_factory=lambda: _env("OCR_REC_KEYS", str(_ROOT / "backend" / "models" / "ocr_rec_keys.txt")))
    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "50")))

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'dg.sqlite3'}"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"


settings = Settings()
