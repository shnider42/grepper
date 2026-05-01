from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import requests

from .models import JobPosting
from .parsing import clean_description


NETFLIX_API_URL = "https://explore.jobs.netflix.net/api/apply/v2/jobs"
NETFLIX_CAREERS_URL = "https://explore.jobs.netflix.net/careers"


class NetflixClient:
    """Small adapter for Netflix's branded jobs API.

    Netflix's public site looks Workday-adjacent, but the visible careers page exposes
    jobs through `/api/apply/v2/jobs` rather than the normal Workday CXS list API.
    This adapter returns Workday-like summaries so the existing Grepper web UI,
    browser-side filters, and ranker can keep working.
    """

    def __init__(self, config: Any, *, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    @property
    def api_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Grepper jobs research tool)",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": NETFLIX_CAREERS_URL,
        }

    def fetch_page(
        self,
        page: int = 1,
        *,
        limit: int | None = None,
        search_text: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if page < 1:
            raise ValueError("page must be >= 1")

        actual_limit = limit or getattr(self.config, "page_size", 20)
        query = self.config.default_search_text if search_text is None else search_text
        params: dict[str, Any] = {
            "domain": "netflix.com",
            "query": query,
            "sort_by": "new",
            "start": (page - 1) * actual_limit,
            "num": actual_limit,
        }

        response = self.session.get(
            NETFLIX_API_URL,
            headers=self.api_headers,
            params=params,
            timeout=getattr(self.config, "timeout_seconds", 30),
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            preview = response.text[:500].replace("\n", " ")
            content_type = response.headers.get("Content-Type", "unknown content type")
            raise ValueError(
                "Expected JSON from Netflix jobs API but got "
                f"{response.status_code} {content_type} from {response.url}. "
                f"Body preview: {preview!r}"
            ) from exc

        positions = data.get("positions") or data.get("records") or data.get("jobs") or []
        if not isinstance(positions, list):
            positions = []

        return {
            "jobPostings": [self._summary_from_position(position) for position in positions if isinstance(position, dict)],
            "total": data.get("count") or data.get("total") or len(positions),
            "raw": data,
        }

    def iter_summaries(
        self,
        *,
        max_pages: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> Iterable[dict[str, Any]]:
        page = 1
        actual_limit = limit or getattr(self.config, "page_size", 20)
        while True:
            if max_pages is not None and page > max_pages:
                return

            data = self.fetch_page(page=page, limit=actual_limit, **kwargs)
            postings = data.get("jobPostings") or []
            if not postings:
                return

            for posting in postings:
                if isinstance(posting, dict):
                    yield posting

            if len(postings) < actual_limit:
                return
            page += 1

    def search_location_options(self, query: str, **_: Any) -> list[Any]:
        """Netflix does not expose Workday-style location facets through this API.

        Returning no facet matches lets the existing browser-side location filter work
        against the normalized `locationsText` value from each result.
        """
        return []

    def hydrate_posting(self, summary: dict[str, Any]) -> JobPosting:
        description_html = str(summary.get("description_html") or "")
        description_text = str(summary.get("description_text") or clean_description(description_html))
        return JobPosting(
            source="Netflix",
            req_id=str(summary.get("req_id") or summary.get("id") or ""),
            title=str(summary.get("title") or ""),
            location=str(summary.get("locationsText") or ""),
            posted=str(summary.get("postedOn") or ""),
            url=str(summary.get("externalPath") or NETFLIX_CAREERS_URL),
            job_id=str(summary.get("id") or ""),
            date_posted=str(summary.get("datePosted") or "") or None,
            hiring_organization="Netflix",
            description_html=description_html or None,
            description_text=description_text,
            raw_summary=summary,
            raw_json_ld={},
        )

    def discover_jobs(
        self,
        *,
        max_pages: int | None = None,
        limit: int | None = None,
        max_jobs: int | None = None,
        hydrate: bool = True,
        **kwargs: Any,
    ) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        for summary in self.iter_summaries(max_pages=max_pages, limit=limit, **kwargs):
            jobs.append(self.hydrate_posting(summary))
            if max_jobs is not None and len(jobs) >= max_jobs:
                break
        return jobs

    def _summary_from_position(self, position: dict[str, Any]) -> dict[str, Any]:
        job_id = str(position.get("id") or position.get("external_id") or "")
        locations = position.get("locations") or position.get("location") or []
        if isinstance(locations, str):
            location_text = locations
        elif isinstance(locations, list):
            location_text = ", ".join(str(location) for location in locations if location)
        else:
            location_text = ""

        title = str(position.get("name") or position.get("title") or "")
        posted = _format_posted(position.get("t_create") or position.get("created_at"))
        canonical_url = str(
            position.get("canonicalPositionUrl")
            or position.get("url")
            or (f"{NETFLIX_CAREERS_URL}/job/{job_id}" if job_id else NETFLIX_CAREERS_URL)
        )
        description = str(position.get("description") or position.get("job_description") or "")

        return {
            "id": job_id,
            "jobId": job_id,
            "req_id": job_id,
            "title": title,
            "titleSimple": title,
            "locationsText": location_text,
            "postedOn": posted,
            "datePosted": posted,
            "externalPath": canonical_url,
            "description_html": description,
            "description_text": clean_description(description),
            "raw_position": position,
        }


def _format_posted(raw: Any) -> str:
    if raw in (None, ""):
        return ""

    if isinstance(raw, (int, float)):
        timestamp = float(raw)
        if timestamp > 10_000_000_000:  # tolerate milliseconds
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
        except (OSError, ValueError):
            return ""

    if isinstance(raw, str):
        if raw.isdigit():
            return _format_posted(int(raw))
        return raw.split("T", 1)[0]

    return ""
