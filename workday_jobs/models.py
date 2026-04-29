from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class JobPosting:
    source: str
    req_id: str
    title: str
    location: str
    posted: str
    url: str
    job_id: str = ""
    employment_type: str | None = None
    date_posted: str | None = None
    valid_through: str | None = None
    hiring_organization: str | None = None
    description_html: str | None = None
    description_text: str = ""
    raw_summary: dict[str, Any] = field(default_factory=dict)
    raw_json_ld: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RankedJob:
    score: float
    job: JobPosting
    matches: dict[str, list[str]]
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "job": self.job.to_dict(),
            "matches": self.matches,
            "notes": self.notes,
        }
