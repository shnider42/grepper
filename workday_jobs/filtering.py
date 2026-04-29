from __future__ import annotations

from typing import Any, Iterable

from .facets import aliases_for_query, is_country_query, normalize_for_match
from .models import JobPosting


def _collect_location_parts(value: Any) -> list[str]:
    parts: list[str] = []

    if value is None:
        return parts
    if isinstance(value, str):
        if value.strip():
            parts.append(value.strip())
        return parts
    if isinstance(value, dict):
        for key, child in value.items():
            key_norm = normalize_for_match(str(key))
            if any(token in key_norm for token in ("location", "address", "city", "state", "country", "descriptor")):
                parts.extend(_collect_location_parts(child))
            elif isinstance(child, (dict, list)):
                parts.extend(_collect_location_parts(child))
        return parts
    if isinstance(value, list):
        for child in value:
            parts.extend(_collect_location_parts(child))
        return parts

    return parts


def location_blob(job: JobPosting) -> str:
    """Build searchable location text from display and raw Workday payloads."""
    parts = [job.location]

    summary = job.raw_summary or {}
    for key in ("locationsText", "location", "locations", "subtitles"):
        parts.extend(_collect_location_parts(summary.get(key)))

    json_ld = job.raw_json_ld or {}
    parts.extend(_collect_location_parts(json_ld.get("jobLocation")))

    return normalize_for_match(" ".join(part for part in parts if part))


def job_matches_location(job: JobPosting, query: str) -> bool:
    """Return True when a job's location text matches a human location query.

    This is intentionally a post-filter safety net for Workday tenants whose applied
    facets are inconsistent or ignored for a given endpoint/search combination.
    """
    blob = location_blob(job)
    if not blob:
        return False

    aliases = aliases_for_query(query)
    if not aliases:
        return True

    # For broad country terms, accept country tokens in returned job locations. This is
    # different from facet matching, where broad country terms should not pick cities.
    if is_country_query(query):
        return any(alias in blob.split() or f" {alias} " in f" {blob} " for alias in aliases)

    return any(alias and alias in blob for alias in aliases)


def filter_jobs_by_locations(jobs: Iterable[JobPosting], queries: Iterable[str]) -> list[JobPosting]:
    clean_queries = [query.strip() for query in queries if query.strip()]
    if not clean_queries:
        return list(jobs)

    return [job for job in jobs if any(job_matches_location(job, query) for query in clean_queries)]
