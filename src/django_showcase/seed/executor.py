from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.utils import timezone

from django_showcase.runtime.database import RuntimeSession
from django_showcase.seed.plan import SeedPlan

_MAX_RELATION_DEPTH = 3


@dataclass(slots=True)
class SeedExecutionResult:
    objects_created: int
    skipped: bool = False


class SeedExecutor:
    """Writes demo objects only inside an isolated (rollback) session."""

    def __init__(self, session: RuntimeSession) -> None:
        self.session = session

    def execute(self, plan: SeedPlan) -> SeedExecutionResult:
        if not self.session.isolated:
            return SeedExecutionResult(objects_created=0, skipped=True)
        created = 0
        for seed in plan.models:
            model = apps.get_model(seed.model)
            for _ in range(seed.count):
                self._create(model, seed.fields)
                created += 1
        return SeedExecutionResult(objects_created=created)

    def _create(self, model, overrides: dict[str, object], depth: int = 0):
        if depth > _MAX_RELATION_DEPTH:
            raise ValidationError(
                f"Related seed chain too deep for {model._meta.label}."
            )
        values = dict(overrides)
        for field in model._meta.get_fields():
            if not getattr(field, "concrete", False) or field.auto_created:
                continue
            if (
                getattr(field, "many_to_many", False)
                or field.primary_key
                or field.name in values
            ):
                continue
            if field.has_default() or field.null:
                continue
            if field.is_relation:
                related = field.related_model
                values[field.name] = related.objects.first() or self._create(
                    related, {}, depth + 1
                )
                continue
            if getattr(field, "blank", False):
                continue
            values[field.name] = _demo_value(field)
        return model.objects.create(**values)


def _demo_value(field) -> object:
    choices = [choice for choice, _ in (field.choices or [])]
    if choices:
        return choices[0]
    return {
        "CharField": f"Demo {field.name}",
        "SlugField": f"demo-{field.name}",
        "TextField": f"Demo {field.name}",
        "EmailField": "demo@example.com",
        "URLField": "https://example.com",
        "IntegerField": 1,
        "PositiveIntegerField": 1,
        "PositiveSmallIntegerField": 1,
        "SmallIntegerField": 1,
        "BigIntegerField": 1,
        "FloatField": 1.0,
        "DecimalField": Decimal("1.0"),
        "BooleanField": False,
        "DateField": date.today(),
        "DateTimeField": timezone.now(),
        "JSONField": {},
    }.get(field.get_internal_type(), f"demo-{field.name}")
