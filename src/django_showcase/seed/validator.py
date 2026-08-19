from __future__ import annotations

from django.core.exceptions import ValidationError

from django_showcase.seed.plan import SeedPlan


class SeedPlanValidator:
    def __init__(self, max_objects: int = 500) -> None:
        self.max_objects = max_objects

    def validate(self, plan: SeedPlan) -> SeedPlan:
        total = 0
        for item in plan.models:
            if item.count < 0:
                raise ValidationError(f"Seed count cannot be negative for {item.model}.")
            total += item.count

        if total > self.max_objects:
            raise ValidationError(
                f"Seed plan exceeds max_objects={self.max_objects}: got {total}."
            )
        return plan
