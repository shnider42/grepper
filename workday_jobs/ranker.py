from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .models import JobPosting, RankedJob


@dataclass
class KeywordProfile:
    core_plus: dict[str, float] = field(default_factory=dict)
    nice: dict[str, float] = field(default_factory=dict)
    light_neg: dict[str, float] = field(default_factory=dict)
    title_boost: float = 1.2
    length_bonus_cap: float = 1.0
    length_bonus_divisor: float = 800.0

    def override(self, weights: dict[str, float] | None) -> "KeywordProfile":
        if not weights:
            return self
        profile = KeywordProfile(
            core_plus=dict(self.core_plus),
            nice=dict(self.nice),
            light_neg=dict(self.light_neg),
            title_boost=self.title_boost,
            length_bonus_cap=self.length_bonus_cap,
            length_bonus_divisor=self.length_bonus_divisor,
        )
        for term, weight in weights.items():
            key = term.casefold()
            if key in profile.core_plus:
                profile.core_plus[key] = weight
            elif key in profile.nice:
                profile.nice[key] = weight
            elif key in profile.light_neg:
                profile.light_neg[key] = weight
            else:
                profile.nice[key] = weight
        return profile


def default_profile() -> KeywordProfile:
    return KeywordProfile(
        core_plus={
            "python": 2.5,
            "linux": 2.0,
            "unix": 1.0,
            "bash": 1.0,
            "kubernetes": 3.0,
            "openshift": 2.5,
            "docker": 2.0,
            "helm": 1.2,
            "devops": 2.0,
            "sre": 2.0,
            "ci/cd": 1.6,
            "jenkins": 1.0,
            "gitlab": 1.0,
            "github actions": 1.0,
            "observability": 1.3,
            "prometheus": 1.2,
            "grafana": 1.0,
            "terraform": 1.5,
            "infrastructure as code": 1.5,
            "virtualization": 1.2,
            "vmware": 1.2,
            "kvm": 0.8,
            "esxi": 0.8,
            "networking": 1.2,
            "tcp/ip": 1.0,
            "dns": 0.9,
            "testing": 2.0,
            "test automation": 2.2,
            "qa": 2.0,
            "quality engineering": 2.0,
            "systems engineering": 1.6,
            "system integration": 1.6,
            "cloud": 1.2,
            "aws": 1.0,
            "azure": 1.0,
            "gcp": 0.8,
            "solutions": 1.4,
            "customer": 0.9,
        },
        nice={
            "matlab": 0.8,
            "simulink": 0.8,
            "c++": 0.8,
            "c/c++": 0.8,
            "simulation": 1.0,
            "modeling": 0.9,
            "mbse": 0.9,
            "sysml": 0.9,
            "digital engineering": 0.8,
            "linux kernel": 1.0,
            "kernel driver": 0.9,
            "requirements": 0.6,
            "risk management": 0.4,
            "fault tolerance": 0.4,
            "cyber": 0.6,
            "encryption": 0.6,
            "storage": 1.2,
            "enterprise": 0.7,
            "agile": 0.5,
        },
        light_neg={
            "hypersonic": -0.8,
            "missile": -0.7,
            "weapon": -0.7,
            "munitions": -0.6,
            "gnc": -0.6,
            "guidance": -0.4,
            "navigation": -0.3,
            "avionics": -0.4,
            "deterrent": -0.4,
            "war-fighter": -0.3,
        },
    )


class KeywordRanker:
    def __init__(self, profile: KeywordProfile | None = None) -> None:
        self.profile = profile or default_profile()

    @staticmethod
    def _prep(text: str | None) -> str:
        return (text or "").casefold()

    @staticmethod
    def _score_text(
        text: str,
        table: dict[str, float],
        *,
        title: bool,
        title_boost: float,
    ) -> tuple[float, list[str]]:
        score = 0.0
        hits: list[str] = []
        for term, weight in table.items():
            pattern = r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)"
            if re.search(pattern, text):
                value = weight * (title_boost if title else 1.0)
                score += value
                hits.append(f"{term}({value:+.1f})")
        return score, hits

    def rank(self, jobs: Iterable[JobPosting], *, weights: dict[str, float] | None = None) -> list[RankedJob]:
        profile = self.profile.override(weights)
        ranked: list[RankedJob] = []

        for job in jobs:
            title = self._prep(job.title)
            description = self._prep(job.description_text)
            both = f"{title}\n{description}"
            score = 0.0
            matches = {"core": [], "nice": [], "neg": []}

            sc, hit = self._score_text(title, profile.core_plus, title=True, title_boost=profile.title_boost)
            score += sc
            matches["core"].extend(hit)
            sc, hit = self._score_text(both, profile.core_plus, title=False, title_boost=profile.title_boost)
            score += sc
            matches["core"].extend(hit)

            sc, hit = self._score_text(title, profile.nice, title=True, title_boost=profile.title_boost)
            score += sc
            matches["nice"].extend(hit)
            sc, hit = self._score_text(both, profile.nice, title=False, title_boost=profile.title_boost)
            score += sc
            matches["nice"].extend(hit)

            sc, hit = self._score_text(both, profile.light_neg, title=False, title_boost=profile.title_boost)
            score += sc
            matches["neg"].extend(hit)

            length_bonus = min(len(description) / profile.length_bonus_divisor, profile.length_bonus_cap)
            score += length_bonus

            ranked.append(
                RankedJob(
                    score=round(score, 3),
                    job=job,
                    matches=matches,
                    notes=f"title='{job.title[:80]}' url='{job.url}'",
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked
