from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Iterable

import requests

from .config import WorkdaySiteConfig
from .facets import FacetOption, merge_facets, search_facet_options
from .models import JobPosting
from .parsing import (
    build_public_job_url,
    clean_description,
    compact_location,
    compact_posted_on,
    extract_json_ld,
    parse_req_id_from_path,
)


NETFLIX_API_URL = "https://explore.jobs.netflix.net/api/apply/v2/jobs"
NETFLIX_CAREERS_URL = "https://explore.jobs.netflix.net/careers"


class WorkdayClient:
    """Small reusable client for Workday CXS career sites."""

    def __init__(self, config: WorkdaySiteConfig, *, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    @property
    def is_netflix_vanity_site(self) -> bool:
        return self.config.tenant == "netflix" and self.config.site == "Netflix"

    def post_jobs(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        applied_facets: dict[str, list[str]] | None = None,
        search_text: str | None = None,
        include_empty_facets: bool = True,
    ) -> dict[str, Any]:
        if self.is_netflix_vanity_site:
            return self._post_netflix_jobs(limit=limit, offset=offset, search_text=search_text)

        payload: dict[str, Any] = {
            "limit": limit or self.config.page_size,
            "offset": offset,
            "searchText": self.config.default_search_text if search_text is None else search_text,
        }
        facets = applied_facets if applied_facets is not None else self.config.default_facets
        if include_empty_facets or facets:
            payload["appliedFacets"] = facets or {}

        response = self.session.post(
            self.config.list_url,
            headers=self.config.api_headers,
            json=payload,
            timeout=self.config.timeout_seconds,
        )

        # Some Workday tenants reject an explicitly empty appliedFacets dict.
        if response.status_code == 400 and payload.get("appliedFacets") == {}:
            return self.post_jobs(
                limit=limit,
                offset=offset,
                applied_facets=applied_facets,
                search_text=search_text,
                include_empty_facets=False,
            )

        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            preview = response.text[:500].replace("\n", " ")
            content_type = response.headers.get("Content-Type", "unknown content type")
            raise ValueError(
                "Expected JSON from Workday CXS API but got "
                f"{response.status_code} {content_type} from {response.url}. "
                f"Body preview: {preview!r}"
            ) from exc

    def _post_netflix_jobs(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        search_text: str | None = None,
    ) -> dict[str, Any]:
        actual_limit = limit or self.config.page_size
        query = self.config.default_search_text if search_text is None else search_text
        response = self.session.get(
            NETFLIX_API_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Grepper jobs research tool)",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": NETFLIX_CAREERS_URL,
            },
            params={
                "domain": "netflix.com",
                "query": query,
                "sort_by": "new",
                "start": offset,
                "num": actual_limit,
            },
            timeout=self.config.timeout_seconds,
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
            "jobPostings": [self._netflix_summary_from_position(position) for position in positions if isinstance(position, dict)],
            "total": data.get("count") or data.get("total") or len(positions),
            "raw": data,
        }

    def _netflix_summary_from_position(self, position: dict[str, Any]) -> dict[str, Any]:
        job_id = str(position.get("id") or position.get("external_id") or "")
        locations = position.get("locations") or position.get("location") or []
        if isinstance(locations, str):
            location_text = locations
        elif isinstance(locations, list):
            location_text = ", ".join(str(location) for location in locations if location)
        else:
            location_text = ""

        title = str(position.get("name") or position.get("title") or "")
        posted = _format_netflix_posted(position.get("t_create") or position.get("created_at"))
        canonical_url = str(
            position.get("canonicalPositionUrl")
            or position.get("url")
            or (f"{NETFLIX_CAREERS_URL}/job/{job_id}" if job_id else NETFLIX_CAREERS_URL)
        )
        description_html = str(position.get("description") or position.get("job_description") or "")

        return {
            "id": job_id,
            "jobId": job_id,
            "uid": job_id,
            "req_id": job_id,
            "title": title,
            "titleSimple": title,
            "locationsText": location_text,
            "postedOn": posted,
            "datePosted": posted,
            "externalPath": canonical_url,
            "description_html": description_html,
            "description_text": clean_description(description_html),
            "raw_position": position,
        }

    def fetch_facets(
        self,
        *,
        applied_facets: dict[str, list[str]] | None = None,
        search_text: str | None = None,
    ) -> dict[str, Any]:
        """Fetch one lightweight list page and return its facet metadata.

        Workday exposes filter dropdown values in the same CXS jobs response used for
        listing jobs. This lets us resolve human terms like "US" or "Boston" to the
        tenant-specific facet IDs instead of hardcoding `locationHierarchy1` or
        `locations` values per employer.
        """
        return self.post_jobs(
            limit=1,
            offset=0,
            applied_facets=applied_facets if applied_facets is not None else self.config.default_facets,
            search_text=search_text,
        )

    def search_location_options(
        self,
        query: str,
        *,
        applied_facets: dict[str, list[str]] | None = None,
        limit: int = 10,
    ) -> list[FacetOption]:
        """Search tenant-specific location facet values by human text.

        Examples: "US", "United States", "Boston", "Massachusetts", "RTP". The
        returned options include the Workday facet key and ID needed for appliedFacets.
        """
        if self.is_netflix_vanity_site:
            return []

        payload = self.fetch_facets(applied_facets=applied_facets)
        return search_facet_options(payload, query, location_only=True, limit=limit)

    def facets_for_location(
        self,
        query: str,
        *,
        applied_facets: dict[str, list[str]] | None = None,
        max_matches: int = 1,
    ) -> dict[str, list[str]]:
        """Resolve a location query into an appliedFacets dict.

        By default this chooses the single best match. Increase max_matches when a
        provider only exposes cities and you intentionally want several matching
        location values.
        """
        matches = self.search_location_options(query, applied_facets=applied_facets, limit=max_matches)
        return merge_facets(*(match.as_facet_dict() for match in matches))

    def fetch_page(self, page: int = 1, *, limit: int | None = None, **kwargs: Any) -> dict[str, Any]:
        if page < 1:
            raise ValueError("page must be >= 1")
        actual_limit = limit or self.config.page_size
        return self.post_jobs(limit=actual_limit, offset=(page - 1) * actual_limit, **kwargs)

    def iter_summaries(
        self,
        *,
        max_pages: int | None = None,
        limit: int | None = None,
        sleep_seconds: float = 0.0,
        **kwargs: Any,
    ) -> Iterable[dict[str, Any]]:
        """Yield raw list-page job posting summaries until pages run out or max_pages is hit."""
        page = 1
        actual_limit = limit or self.config.page_size
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
            if sleep_seconds:
                time.sleep(sleep_seconds)

    def fetch_json_ld(self, public_url: str) -> dict[str, Any]:
        response = self.session.get(
            public_url,
            headers=self.config.html_headers,
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        return extract_json_ld(response.text)

    def hydrate_posting(self, summary: dict[str, Any]) -> JobPosting:
        external_path = summary.get("externalPath") or summary.get("externalPathAndQuery") or ""
        url = build_public_job_url(
            self.config.base_url,
            self.config.site,
            str(external_path),
            locale=self.config.locale,
            public_path_prefix=self.config.public_site_prefix,
        )

        if self.is_netflix_vanity_site:
            description_html = summary.get("description_html")
            description_text = str(summary.get("description_text") or clean_description(description_html))
            return JobPosting(
                source="Netflix",
                req_id=str(summary.get("req_id") or summary.get("id") or ""),
                title=str(summary.get("title") or summary.get("titleSimple") or ""),
                location=compact_location(summary),
                posted=compact_posted_on(summary),
                url=url,
                job_id=str(summary.get("id") or summary.get("jobId") or summary.get("uid") or ""),
                date_posted=summary.get("datePosted"),
                hiring_organization="Netflix",
                description_html=description_html,
                description_text=description_text,
                raw_summary=summary,
                raw_json_ld={},
            )

        json_ld = self.fetch_json_ld(url)
        description_html = json_ld.get("description") if json_ld else None
        description_text = clean_description(description_html)

        job_location = ""
        job_location_data = json_ld.get("jobLocation") if isinstance(json_ld, dict) else None
        if isinstance(job_location_data, dict):
            address = job_location_data.get("address") or {}
            if isinstance(address, dict):
                job_location = str(address.get("addressLocality") or "")
        elif isinstance(job_location_data, list) and job_location_data:
            first = job_location_data[0]
            if isinstance(first, dict):
                address = first.get("address") or {}
                if isinstance(address, dict):
                    job_location = str(address.get("addressLocality") or "")

        return JobPosting(
            source=self.config.site,
            req_id=parse_req_id_from_path(str(external_path)),
            title=str(summary.get("title") or summary.get("titleSimple") or json_ld.get("title") or ""),
            location=compact_location(summary) or job_location,
            posted=compact_posted_on(summary),
            url=url,
            job_id=str(summary.get("id") or summary.get("jobId") or summary.get("uid") or ""),
            employment_type=json_ld.get("employmentType"),
            date_posted=json_ld.get("datePosted"),
            valid_through=json_ld.get("validThrough"),
            hiring_organization=(json_ld.get("hiringOrganization") or {}).get("name")
            if isinstance(json_ld.get("hiringOrganization"), dict)
            else None,
            description_html=description_html,
            description_text=description_text,
            raw_summary=summary,
            raw_json_ld=json_ld,
        )

    def discover_jobs(
        self,
        *,
        max_pages: int | None = None,
        limit: int | None = None,
        max_jobs: int | None = None,
        hydrate: bool = True,
        sleep_seconds: float = 0.0,
        **kwargs: Any,
    ) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        for summary in self.iter_summaries(
            max_pages=max_pages,
            limit=limit,
            sleep_seconds=sleep_seconds,
            **kwargs,
        ):
            if hydrate:
                job = self.hydrate_posting(summary)
            else:
                external_path = summary.get("externalPath") or summary.get("externalPathAndQuery") or ""
                url = build_public_job_url(
                    self.config.base_url,
                    self.config.site,
                    str(external_path),
                    locale=self.config.locale,
                    public_path_prefix=self.config.public_site_prefix,
                )
                job = JobPosting(
                    source=self.config.site,
                    req_id=parse_req_id_from_path(str(external_path)),
                    title=str(summary.get("title") or summary.get("titleSimple") or ""),
                    location=compact_location(summary),
                    posted=compact_posted_on(summary),
                    url=url,
                    job_id=str(summary.get("id") or summary.get("jobId") or summary.get("uid") or ""),
                    raw_summary=summary,
                )
            jobs.append(job)
            if max_jobs is not None and len(jobs) >= max_jobs:
                break
        return jobs


def _format_netflix_posted(raw: Any) -> str:
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
            return _format_netflix_posted(int(raw))
        return raw.split("T", 1)[0]

    return ""
