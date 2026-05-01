from __future__ import annotations

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


class WorkdayClient:
    """Small reusable client for Workday CXS career sites."""

    def __init__(self, config: WorkdaySiteConfig, *, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def post_jobs(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        applied_facets: dict[str, list[str]] | None = None,
        search_text: str | None = None,
        include_empty_facets: bool = True,
    ) -> dict[str, Any]:
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
        return response.json()

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
