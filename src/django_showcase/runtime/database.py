from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from django.db import transaction


@dataclass(slots=True)
class RuntimeSession:
    isolated: bool


@contextmanager
def scenario_runtime(enabled: bool = False) -> Iterator[RuntimeSession]:
    yield RuntimeSession(isolated=enabled)


@contextmanager
def scenario_transaction(session: RuntimeSession) -> Iterator[None]:
    """Seeds live only inside this block; isolated sessions always roll back."""
    if not session.isolated:
        yield
        return
    with transaction.atomic():
        yield
        transaction.set_rollback(True)
