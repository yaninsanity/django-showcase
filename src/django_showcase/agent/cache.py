from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from django_showcase.seed.plan import ActorSeed, ModelSeed, RelationshipSeed, SeedAssertion, SeedPlan


def plan_cache_key(provider: str, goal: str, schema_summary: dict[str, object]) -> str:
    payload = json.dumps(
        {"provider": provider, "goal": goal, "schema": schema_summary},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SeedPlanCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def get(self, key: str) -> SeedPlan | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return SeedPlan(
            models=[ModelSeed(**item) for item in data.get("models", [])],
            actor=ActorSeed(**data["actor"]) if data.get("actor") else None,
            relationships=[RelationshipSeed(**item) for item in data.get("relationships", [])],
            assertions=[SeedAssertion(**item) for item in data.get("assertions", [])],
        )

    def set(self, key: str, plan: SeedPlan) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{key}.json").write_text(
            json.dumps(asdict(plan), indent=2), encoding="utf-8"
        )
