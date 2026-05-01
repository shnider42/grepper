from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .models import JobPosting, RankedJob


def _coerce_weight_table(raw: object, field_name: str) -> dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Profile field {field_name!r} must be an object mapping terms to weights")

    table: dict[str, float] = {}
    for term, weight in raw.items():
        if not isinstance(term, str) or not term.strip():
            raise ValueError(f"Profile field {field_name!r} contains an invalid term: {term!r}")
        try:
            table[term.casefold()] = float(weight)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Profile field {field_name!r} contains a non-numeric weight for {term!r}: {weight!r}"
            ) from exc
    return table


@dataclass
class Profile:
    """Weighted keyword settings used to rank job postings.

    A Profile is the reusable matching personality for a search. It groups strong
    positive terms, softer positive terms, and light negative terms, plus a few
    scoring knobs that control title and description behavior.
    """

    name: str = "default"
    core_plus: dict[str, float] = field(default_factory=dict)
    nice: dict[str, float] = field(default_factory=dict)
    light_neg: dict[str, float] = field(default_factory=dict)
    title_boost: float = 1.35
    length_bonus_cap: float = 1.25
    length_bonus_divisor: float = 900.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        if not isinstance(data, dict):
            raise ValueError("Profile JSON must be an object")

        return cls(
            name=str(data.get("name") or "custom"),
            core_plus=_coerce_weight_table(data.get("core_plus"), "core_plus"),
            nice=_coerce_weight_table(data.get("nice"), "nice"),
            light_neg=_coerce_weight_table(data.get("light_neg"), "light_neg"),
            title_boost=float(data.get("title_boost", cls.title_boost)),
            length_bonus_cap=float(data.get("length_bonus_cap", cls.length_bonus_cap)),
            length_bonus_divisor=float(data.get("length_bonus_divisor", cls.length_bonus_divisor)),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "Profile":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def override(self, weights: dict[str, float] | None) -> "Profile":
        """Return a copy with term-level weight overrides applied.

        Existing terms keep their bucket. New positive weights are added to
        ``nice`` by default; new negative weights are added to ``light_neg``.
        """
        if not weights:
            return self
        profile = Profile(
            name=self.name,
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
            elif weight < 0:
                profile.light_neg[key] = weight
            else:
                profile.nice[key] = weight
        return profile


# Backward-compatible name for older imports.
KeywordProfile = Profile


def load_profile(path: str | Path | None = None) -> Profile:
    return Profile.from_json_file(path) if path else default_profile()


def default_profile() -> Profile:
    """Default ranking profile tuned for Chris's background.

    The intent is not to perfectly classify every job. It is to push the first page
    toward roles that combine quality engineering, automation, systems/SRE, Linux,
    networking/storage, customer-facing problem solving, and technical leadership.
    """
    return Profile(
        name="chris-default",
        core_plus={
            "quality engineering": 3.4,
            "quality engineer": 3.0,
            "quality assurance": 2.6,
            "software quality": 2.8,
            "qa": 2.4,
            "qe": 1.8,
            "sdet": 3.0,
            "test automation": 3.2,
            "automation": 2.2,
            "software testing": 2.4,
            "systems test": 2.4,
            "system test": 2.4,
            "integration and test": 2.7,
            "integration & test": 2.7,
            "validation": 2.4,
            "verification": 2.1,
            "debug": 1.4,
            "troubleshooting": 1.6,
            "failure analysis": 1.6,
            "lab": 1.0,
            "python": 2.5,
            "linux": 2.5,
            "unix": 1.1,
            "bash": 1.4,
            "shell": 1.0,
            "kubernetes": 2.6,
            "openshift": 2.6,
            "containers": 1.8,
            "container": 1.5,
            "docker": 1.8,
            "helm": 1.3,
            "fedora": 1.0,
            "red hat": 1.0,
            "sre": 2.4,
            "site reliability": 2.4,
            "devops": 2.0,
            "devsecops": 2.0,
            "ci/cd": 1.8,
            "jenkins": 1.2,
            "gitlab": 1.0,
            "github actions": 1.0,
            "observability": 1.4,
            "prometheus": 1.2,
            "grafana": 1.0,
            "terraform": 1.4,
            "infrastructure as code": 1.5,
            "enterprise storage": 3.4,
            "storage": 2.4,
            "distributed storage": 1.8,
            "block storage": 1.4,
            "file storage": 1.4,
            "san": 1.2,
            "nas": 1.2,
            "vmware": 1.4,
            "virtualization": 1.3,
            "kvm": 0.8,
            "esxi": 0.8,
            "network os": 2.8,
            "network operating system": 2.8,
            "networking": 2.0,
            "routing": 1.4,
            "switching": 1.4,
            "protocols": 1.2,
            "tcp/ip": 1.4,
            "ethernet": 1.2,
            "dns": 0.8,
            "systems engineering": 1.7,
            "system integration": 2.0,
            "solutions engineer": 2.4,
            "solutions engineering": 2.4,
            "solutions": 1.4,
            "consulting engineer": 1.8,
            "customer-facing": 2.0,
            "customer facing": 2.0,
            "customer": 1.0,
            "field": 0.8,
            "technical leader": 1.7,
            "technical leadership": 1.7,
            "leadership": 0.9,
            "agile": 1.0,
            "scrum": 0.8,
            "cross-functional": 1.4,
            "cross functional": 1.4,
            "stakeholder": 1.2,
            "coaching": 1.0,
            "enablement": 0.8,
            "cloud": 1.4,
            "aws": 1.0,
            "azure": 1.0,
            "gcp": 0.8,
        },
        nice={
            "requirements": 1.0,
            "risk management": 0.5,
            "fault tolerance": 0.6,
            "resiliency": 0.7,
            "reliability": 1.0,
            "hardware": 0.9,
            "hardware test": 1.3,
            "embedded": 1.0,
            "firmware": 1.0,
            "c++": 0.8,
            "c/c++": 0.8,
            "go": 0.5,
            "simulation": 0.8,
            "modeling": 0.6,
            "matlab": 0.5,
            "simulink": 0.5,
            "mbse": 0.6,
            "sysml": 0.6,
            "digital engineering": 0.7,
            "linux kernel": 0.9,
            "kernel driver": 0.8,
            "cyber": 0.5,
            "security": 0.6,
            "encryption": 0.5,
            "enterprise": 0.7,
            "program management": 0.5,
            "product": 0.5,
        },
        light_neg={
            "intern": -2.0,
            "internship": -2.0,
            "new grad": -1.5,
            "account executive": -2.0,
            "sales development": -2.0,
            "inside account": -1.8,
            "finance": -2.0,
            "accountant": -2.0,
            "legal": -2.0,
            "counsel": -2.0,
            "recruiter": -2.0,
            "asic": -0.8,
            "dft": -1.0,
            "physical design": -1.2,
            "timing constraints": -0.8,
            "photonic": -1.0,
            "photonics": -1.0,
            "rf": -0.5,
            "fpga": -0.6,
            "analog": -0.6,
            "mixed signal": -0.7,
            "semiconductor": -0.6,
            "power electronics": -0.6,
            "mechanical": -0.7,
            "hypersonic": -0.8,
            "missile": -0.7,
            "weapon": -0.7,
            "munitions": -0.6,
            "gnc": -0.5,
            "guidance": -0.4,
            "avionics": -0.4,
            "deterrent": -0.4,
            "war-fighter": -0.3,
        },
    )


class KeywordRanker:
    def __init__(self, profile: Profile | None = None) -> None:
        self.profile = profile or default_profile()

    @staticmethod
    def _prep(text: str | None) -> str:
        return (text or "").casefold()

    @staticmethod
    def _term_pattern(term: str) -> str:
        escaped = re.escape(term.casefold())
        escaped = escaped.replace(r"\ ", r"[\s\-/]+")
        escaped = escaped.replace(r"\/", r"[\s\-/]+")
        escaped = escaped.replace(r"\-", r"[\s\-/]+")
        return r"(?<!\w)" + escaped + r"(?!\w)"

    @classmethod
    def _score_text(
        cls,
        text: str,
        table: dict[str, float],
        *,
        title: bool,
        title_boost: float,
    ) -> tuple[float, list[str]]:
        score = 0.0
        hits: list[str] = []
        for term, weight in table.items():
            if re.search(cls._term_pattern(term), text):
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
                    notes=f"profile='{profile.name}' title='{job.title[:80]}' url='{job.url}'",
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked
