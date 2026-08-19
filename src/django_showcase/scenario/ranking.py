from __future__ import annotations

from django_showcase.scenario.scenario import Scenario


def score_scenario(scenario: Scenario) -> int:
    score = 10
    score += 5 if scenario.actor else 0
    score += 3 if scenario.seed else 0
    score += 3 if scenario.goal else 0
    score += 2 if "empty" in scenario.id else 0
    score += 3 if "high_volume" in scenario.id else 0
    score += 4 if any(flag in scenario.id for flag in ("failed", "error", "denied")) else 0
    return score
