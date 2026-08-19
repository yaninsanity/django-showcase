from __future__ import annotations

from django_showcase.seed.plan import SeedPlan


class StaticProvider:
    name = "static"

    def plan(self, seed_plan: SeedPlan) -> SeedPlan:
        return seed_plan
