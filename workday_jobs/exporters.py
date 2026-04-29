from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .models import RankedJob


def write_ranked_json(path: str | Path, ranked: Iterable[RankedJob]) -> None:
    data = [item.to_dict() for item in ranked]
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_ranked_csv(path: str | Path, ranked: Iterable[RankedJob]) -> None:
    rows = []
    for item in ranked:
        job = item.job
        rows.append(
            {
                "score": item.score,
                "title": job.title,
                "req_id": job.req_id,
                "location": job.location,
                "posted": job.posted,
                "date_posted": job.date_posted or "",
                "source": job.source,
                "url": job.url,
                "core_matches": "; ".join(item.matches.get("core", [])),
                "nice_matches": "; ".join(item.matches.get("nice", [])),
                "neg_matches": "; ".join(item.matches.get("neg", [])),
                "description_preview": job.description_text[:500],
            }
        )

    fieldnames = [
        "score",
        "title",
        "req_id",
        "location",
        "posted",
        "date_posted",
        "source",
        "url",
        "core_matches",
        "nice_matches",
        "neg_matches",
        "description_preview",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
