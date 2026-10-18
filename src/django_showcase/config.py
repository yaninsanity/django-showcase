from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from django.conf import settings


@dataclass(slots=True)
class ShowcaseConfig:
    output_dir: Path
    report_dir: Path
    screenshots_dir: Path
    frontend_dir: Path
    frontend_dirs: list[Path]
    max_scenarios_per_module: int = 6
    max_choices_per_field: int = 4
    max_seed_objects: int = 500
    agent_enabled: bool = False
    agent_provider: str = "openai"
    agent_model: str = "gpt-4.1-mini"
    agent_timeout_seconds: float = 30.0
    agent_max_retries: int = 2
    capture_backend: Literal["auto", "playwright", "placeholder"] = "auto"
    capture_base_url: str | None = None
    capture_timeout_seconds: float = 20.0
    agentic_seed_strategy: Literal["goal_only", "all_pages"] = "all_pages"
    archive_filename: str = "showcase.zip"
    prompt_overrides: dict[str, str] | None = None
    scenario_mode: bool = False

    @classmethod
    def from_settings(cls) -> "ShowcaseConfig":
        raw = getattr(settings, "SHOWCASE", {})
        base_dir = Path(raw.get("OUTPUT_DIR", ".showcase"))
        frontend_dir = Path(raw.get("FRONTEND_DIR", getattr(settings, "BASE_DIR", ".")))
        frontend_dirs = [Path(item) for item in raw.get("FRONTEND_DIRS", [])] or [
            frontend_dir
        ]
        prompt_overrides = dict(raw.get("PROMPTS", {}))
        prompt_file = raw.get("PROMPT_FILE")
        if prompt_file:
            prompt_overrides.update(_load_prompt_file(Path(prompt_file)))
        return cls(
            output_dir=base_dir,
            report_dir=base_dir / "report",
            screenshots_dir=base_dir / "screenshots",
            frontend_dir=frontend_dir,
            frontend_dirs=frontend_dirs,
            max_scenarios_per_module=raw.get("MAX_SCENARIOS_PER_MODULE", 6),
            max_choices_per_field=raw.get("MAX_CHOICES_PER_FIELD", 4),
            max_seed_objects=raw.get("MAX_SEED_OBJECTS", 500),
            agent_enabled=raw.get("AGENT_ENABLED", False),
            agent_provider=raw.get("AGENT_PROVIDER", "openai"),
            agent_model=raw.get("AGENT_MODEL", "gpt-4.1-mini"),
            agent_timeout_seconds=raw.get("AGENT_TIMEOUT_SECONDS", 30.0),
            agent_max_retries=raw.get("AGENT_MAX_RETRIES", 2),
            capture_backend=raw.get("CAPTURE_BACKEND", "auto"),
            capture_base_url=raw.get("CAPTURE_BASE_URL"),
            capture_timeout_seconds=raw.get("CAPTURE_TIMEOUT_SECONDS", 20.0),
            agentic_seed_strategy=raw.get("AGENTIC_SEED_STRATEGY", "all_pages"),
            archive_filename=raw.get("ARCHIVE_FILENAME", "showcase.zip"),
            prompt_overrides=prompt_overrides,
            scenario_mode=raw.get("SCENARIO_MODE", False),
        )


def _load_prompt_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {key: str(value) for key, value in data.items() if isinstance(key, str)}
