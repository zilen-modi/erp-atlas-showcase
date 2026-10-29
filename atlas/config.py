"""Load config/policy.yaml and resolve its paths against the repo root.

Connection settings the user changes in the UI (python layer URL, UniVerse host for the
VPN check) live in .data/settings.json and override policy.yaml. Env vars still win.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(os.environ.get("ATLAS_HOME", Path(__file__).resolve().parent.parent))
SETTINGS_KEYS = ("python_layer_url", "universe_host", "universe_port")


def settings_path() -> Path:
    return Path(os.environ.get("ATLAS_SETTINGS", ROOT / ".data" / "settings.json"))


def read_settings() -> dict[str, Any]:
    try:
        raw = json.loads(settings_path().read_text())
    except (OSError, ValueError):
        return {}
    return {k: raw[k] for k in SETTINGS_KEYS if raw.get(k) not in (None, "")}


def normalise_settings(body: dict[str, Any]) -> dict[str, Any]:
    """Validate UI input. Raises ValueError with a message fit for a toast."""
    out: dict[str, Any] = {}
    url = str(body.get("python_layer_url") or "").strip().rstrip("/")
    if url:
        u = urlparse(url if "://" in url else f"http://{url}")
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("Python layer URL must look like http://localhost:6000")
        path = u.path.rstrip("/")
        if "/api/" not in path + "/":
            path += "/api/v1"          # users paste the server root; the API lives under /api/v1
        out["python_layer_url"] = f"{u.scheme}://{u.netloc}{path}"
    host = str(body.get("universe_host") or "").strip()
    if host:
        if not re.fullmatch(r"[A-Za-z0-9.\-]+", host):
            raise ValueError("UniVerse host must be a host name or IP address, e.g. 10.0.0.10")
        out["universe_host"] = host
    port = body.get("universe_port")
    if port not in (None, ""):
        try:
            n = int(port)
        except (TypeError, ValueError):
            raise ValueError("UniVerse port must be a number") from None
        if not 0 < n < 65536:
            raise ValueError("UniVerse port must be between 1 and 65535")
        out["universe_port"] = n
    return out


def _raw_settings() -> dict[str, Any]:
    try:
        raw = json.loads(settings_path().read_text())
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(values: dict[str, Any]) -> None:
    """Replace the connection settings; other sections (navigation) are kept."""
    keep = {k: v for k, v in _raw_settings().items() if k not in SETTINGS_KEYS}
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**keep, **values}, indent=2) + "\n")


def hidden_tabs() -> list[str]:
    v = _raw_settings().get("hidden_tabs")
    return [str(x) for x in v] if isinstance(v, list) else []


def save_hidden_tabs(paths: list[str]) -> list[str]:
    clean = sorted({p for p in paths if isinstance(p, str) and p.startswith("/") and p not in ("/", "/settings")})
    raw = _raw_settings()
    raw["hidden_tabs"] = clean
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, indent=2) + "\n")
    return clean


def allow_shared_claude() -> bool:
    """May people who haven't connected their own Claude use the server's Claude Code login?"""
    return bool(_raw_settings().get("allow_shared_claude", False))


def save_allow_shared_claude(on: bool) -> bool:
    raw = _raw_settings()
    raw["allow_shared_claude"] = bool(on)
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, indent=2) + "\n")
    return bool(on)


def policy_path() -> Path:
    """config/policy.yaml is local (git-ignored); config/policy.example.yaml is the template."""
    local = ROOT / "config" / "policy.yaml"
    return local if local.exists() else ROOT / "config" / "policy.example.yaml"


def policy_live() -> dict[str, Any]:
    return dict(yaml.safe_load(policy_path().read_text())["live"])


def cache_dir_for(base: Path, url: str, default_url: str) -> Path:
    """Live cache per server: a different python layer may front different data."""
    if url.rstrip("/") == default_url.rstrip("/"):
        return base
    return base / ("_" + re.sub(r"[^A-Za-z0-9]+", "_", urlparse(url).netloc).strip("_"))


@dataclass
class LiveConfig:
    base_url: str
    timeout_s: float
    min_interval_s: float
    cache_dir: Path
    deny_tables: list[str]
    universe_host: str = ""
    universe_port: int = 31438
    parallel: int = 4              # record reads in flight at once (capture, quick compare)


@dataclass
class GitConfig:
    origin: str
    local_fallback: Path
    mirror: Path
    branch: str
    index_paths: list[str]
    filename_map: str


@dataclass
class SliceConfig:
    seeds: list[str]
    menus: list[str] = field(default_factory=list)
    dicts: list[str] = field(default_factory=list)
    expand_calls: int = 1


@dataclass
class ChatConfig:
    model: str = "claude-opus-5"
    effort: str = "high"
    max_tool_rounds: int = 25


@dataclass
class Config:
    environment: str
    live: LiveConfig
    git: GitConfig
    store: Path
    live_budget: int
    slices: dict[str, SliceConfig]
    chat: ChatConfig = field(default_factory=ChatConfig)
    organisation: str = ""          # shown on signs in the network view; set in config/policy.yaml


def _path(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else (ROOT / q).resolve()


def load(path: Path | None = None) -> Config:
    raw: dict[str, Any] = yaml.safe_load((path or policy_path()).read_text())
    lv, gt = raw["live"], raw["git"]
    user = read_settings()
    url = os.environ.get("UNIVERSE_API_URL") or user.get("python_layer_url") or lv["base_url"]
    return Config(
        environment=raw.get("environment", "TEST"),
        live=LiveConfig(
            base_url=url.rstrip("/"),
            timeout_s=float(lv.get("timeout_s", 120)),
            min_interval_s=float(lv.get("min_interval_s", 1.0)),
            cache_dir=cache_dir_for(_path(lv.get("cache_dir", ".cache/live")), url, lv["base_url"]),
            deny_tables=[t.upper() for t in lv.get("deny_tables", [])],
            universe_host=str(user.get("universe_host") or lv.get("universe_host", "")),
            universe_port=int(user.get("universe_port") or lv.get("universe_port", 31438)),
            parallel=int(lv.get("parallel", 4)),
        ),
        git=GitConfig(
            origin=gt["origin"],
            local_fallback=_path(gt["local_fallback"]),
            mirror=_path(gt["mirror"]),
            branch=gt.get("branch", "main"),
            index_paths=list(gt.get("index_paths", ["src/BP", "src/GUIBP", "src/next/api-helpers",
                                                    "src/next/utilities"])),
            filename_map=gt.get("filename_map", "scripts/filename_map.json"),
        ),
        store=_path(os.environ.get("ATLAS_DB", raw.get("store", ".data/atlas.db"))),
        live_budget=int(raw.get("sync", {}).get("live_budget", 25)),
        slices={k: SliceConfig(**v) for k, v in raw.get("slices", {}).items()},
        chat=ChatConfig(**raw.get("chat", {})),
        organisation=str((raw.get("organisation") or {}).get("name", "")),
    )
