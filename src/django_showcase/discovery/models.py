from __future__ import annotations

from dataclasses import dataclass, field

from django.apps import apps


@dataclass(slots=True)
class FieldMetadata:
    name: str
    kind: str
    choices: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ModelMetadata:
    label: str
    fields: list[FieldMetadata]


def inspect_models() -> list[ModelMetadata]:
    result: list[ModelMetadata] = []
    for model in apps.get_models():
        fields: list[FieldMetadata] = []
        for field in model._meta.get_fields():
            if not hasattr(field, "name"):
                continue
            raw_choices = getattr(field, "choices", None) or []
            choices = [choice for choice, _label in raw_choices if choice not in {None, ""}]
            fields.append(
                FieldMetadata(
                    name=field.name,
                    kind=field.get_internal_type(),
                    choices=choices,
                )
            )
        result.append(ModelMetadata(label=model._meta.label, fields=fields))
    return result
