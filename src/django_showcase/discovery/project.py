from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(slots=True)
class ProjectContext:
    project_name: str
    installed_apps: list[str]


def build_project_context() -> ProjectContext:
    root_urlconf = getattr(settings, "ROOT_URLCONF", "") or "django-project"
    return ProjectContext(
        project_name=root_urlconf.split(".")[0],
        installed_apps=list(settings.INSTALLED_APPS),
    )
