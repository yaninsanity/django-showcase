from __future__ import annotations

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist, ValidationError

from django_showcase.seed.plan import SeedPlan
from django_showcase.seed.validator import SeedPlanValidator


class SeedPlanGuardrails:
    """Validates agent output against the real schema before anything executes."""

    def __init__(self, max_objects: int = 500) -> None:
        self._volume = SeedPlanValidator(max_objects=max_objects)

    def check(self, plan: SeedPlan) -> SeedPlan:
        for seed in plan.models:
            try:
                model = apps.get_model(seed.model)
            except (LookupError, ValueError) as exc:
                raise ValidationError(f"Unknown model in seed plan: {seed.model!r}") from exc
            self._check_fields(model, seed.model, seed.fields)
        return self._volume.validate(plan)

    def _check_fields(self, model, label: str, fields: dict[str, object]) -> None:
        for name, value in fields.items():
            try:
                field = model._meta.get_field(name)
            except FieldDoesNotExist as exc:
                raise ValidationError(f"Unknown field {label}.{name}") from exc
            choices = [choice for choice, _ in (field.choices or [])]
            if choices and value not in choices:
                raise ValidationError(
                    f"Invalid choice for {label}.{name}: {value!r} (allowed: {choices})"
                )
