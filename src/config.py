"""
Loads everything a marketer can change without touching Python.

Prompts, brand rules and the component manifest live as flat files. This module
is the only thing that knows where they are, and it records a fingerprint of each
so a trace can be tied back to the exact version of the config that produced it.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
BRAND = ROOT / "brand"
COMPONENTS = ROOT / "components"
PARTIALS = COMPONENTS / "partials"
EVALS = ROOT / "evals"

# Everything the app WRITES lives under DATA_DIR; everything it READS
# (prompts, brand rules, components) stays in the repo.
#
# Separating them is what makes a mounted volume work: point DATA_DIR at the
# mount and the queue, traces and database survive restarts and redeploys,
# while the config still ships with the code and stays version-controlled.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT)))
TRACES = DATA_DIR / "traces"
OUT = DATA_DIR / "out"
DB_FILE = DATA_DIR / "email_agent.db"


def ensure_data_dirs() -> None:
    for path in (TRACES, OUT, OUT / "syncs", OUT / "threads"):
        path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=None)
def prompt(name: str) -> str:
    path = PROMPTS / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **values: Any) -> str:
    """
    Deliberately dumb {{ token }} substitution rather than full Jinja.

    Prompts are reviewed by non-engineers. Keeping the templating trivial means
    a marketer editing a prompt cannot accidentally introduce control flow, and
    a reviewer can see exactly what will be sent.
    """
    text = prompt(name)
    for key, value in values.items():
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        text = text.replace("{{ " + key + " }}", "" if value is None else str(value))
    return text


@lru_cache(maxsize=None)
def brand_rules() -> dict[str, Any]:
    return yaml.safe_load((BRAND / "rules.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def voice_guidance() -> str:
    return (BRAND / "voice.md").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def manifest() -> dict[str, Any]:
    return yaml.safe_load((COMPONENTS / "manifest.yaml").read_text(encoding="utf-8"))


def component_ids() -> list[str]:
    return list(manifest()["components"].keys())


def component(component_id: str) -> dict[str, Any]:
    comps = manifest()["components"]
    if component_id not in comps:
        raise KeyError(component_id)
    return comps[component_id]


def sequence_for(campaign_type: str | None) -> list[str] | None:
    """None means no deterministic mapping — the model fallback path."""
    if not campaign_type:
        return None
    return manifest().get("sequences", {}).get(campaign_type)


def config_fingerprint() -> dict[str, str]:
    """Version stamp recorded on every run."""
    def h(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]

    fp = {
        "brand_rules": brand_rules().get("version", "?"),
        "manifest": manifest().get("version", "?"),
        "brand_rules_hash": h(BRAND / "rules.yaml"),
        "manifest_hash": h(COMPONENTS / "manifest.yaml"),
        "voice_hash": h(BRAND / "voice.md"),
    }
    for p in sorted(PROMPTS.glob("*.md")):
        fp[f"prompt:{p.stem}"] = h(p)
    return fp
