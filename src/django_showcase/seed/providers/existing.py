from __future__ import annotations

from django_showcase.seed.plan import SeedPlan


class ExistingProvider:
    name = "existing"

    def plan(self) -> SeedPlan:
        return SeedPlan()
