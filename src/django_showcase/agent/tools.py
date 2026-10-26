"""Read-only structured introspection tools exposed to agents."""
from __future__ import annotations

from django.apps import apps


def inspect_model(label: str) -> dict[str, object]:
    model = apps.get_model(label)
    fields = []
    for field in model._meta.get_fields():
        if not hasattr(field, "name") or not getattr(field, "concrete", False):
            continue
        raw_choices = getattr(field, "choices", None) or []
        fields.append(
            {
                "name": field.name,
                "kind": field.get_internal_type(),
                "choices": [
                    choice for choice, _ in raw_choices if choice not in {None, ""}
                ],
            }
        )
    return {"label": model._meta.label, "fields": fields}


def inspect_relationships(label: str) -> list[dict[str, str]]:
    model = apps.get_model(label)
    return [
        {
            "source": f"{model._meta.label}.{field.name}",
            "target": field.related_model._meta.label,
        }
        for field in model._meta.get_fields()
        if getattr(field, "concrete", False)
        and field.is_relation
        and field.related_model
    ]


def build_schema_summary() -> dict[str, object]:
    labels = [model._meta.label for model in apps.get_models()]
    return {
        "models": {label: inspect_model(label) for label in labels},
        "relationships": [
            item for label in labels for item in inspect_relationships(label)
        ],
    }
