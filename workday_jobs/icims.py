from __future__ import annotations

from dataclasses import dataclass
import re
import time
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from .models import JobPosting
from .parsing import clean_description, extract_json_ld, html_to_text, normalize_text


ICIMS_JOB_PATH_RE = re.compile(r"/jobs/(?P<job_id>\d+)/job(?:/|$)", re.I)
ICIMS_JOB_LINK_RE = re.compile(r"""href=["'](?P<href>[^"']*/jobs/(?P<job_id>\d+)/job[^"']*)["']""", re.I)


@dataclass(frozen=True)
class IcimsSiteConfig:
    """Configuration for an iCIMS-hosted careers site.

    iCIMS public URLs commonly look like:
        https://careers-suffolkconstruction.icims.com/jobs/11113/job
        https://careers-suffolkconstruction.icims.com/jobs/search
    """

    base_url: str
    company_slug: str
    job_id: str | None = None
    default_search_text: str = ""
    page_size: int = 20
    timeout_seconds: int = 30

    @property
    def source_name(self) -> str:
        return self.company_slug

    @property
    def search_url(self) -> str:
        return f"{self.base_url}/jobs/search"

    @property
    def public_site_prefix(self) -> str:
        return "/jobs"

    @property
    def api_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Grepper iCIMS research tool)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.search_url,
        }

    @property
    def html_headers(self) -> dict[str, str]:
        return self.api_headers

    def job_url(self, job_id: str | None = None) -> str:
        resolved_job_id = job_id or self.job_id
        if not resolved_job_id:
            return self.search_url
        return f"{self.base_url}/jobs/{resolved_job_id}/job"

    @classmethod
    def from_public_url(cls, url: str) -> "IcimsSiteConfig":
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Expected absolute iCIMS URL, got: {url!r}")
        if not is_icims_host(parsed.netloc):
            raise ValueError(f"Expected iCIMS URL, got: {url!r}")

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        host_label = parsed.netloc.split(".", 1)[0]
        company_slug = host_label.removeprefix("careers-") or host_label

        match = ICIMS_JOB_PATH_RE.search(parsed.path or "")
        job_id = match.group("job_id") if match else None
        query = parse_qs(parsed.query or "")
        default_search_text = (query.get("searchKeyword") or query.get("q") or [""])[0]

        return cls(
            base_url=base_url,
            company_slug=company_slug,
            job_id=job_id,
            default_search_text=default_search_text,
        )


class _IcimsLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._active_href: str | None = None
        self._active_job_id: str | None = None
        self._active_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._active_href is not None:
            return
        raw_attrs = {name.lower(): value for name, value in attrs if value is not None}
        href = raw_attrs.get("href") or ""
        match = ICIMS_JOB_PATH_RE.search(href)
        if not match:
            return

        self._active_href = urljoin(self.base_url, href)
        self._active_job_id = match.group("job_id")
        self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._active_href is not None and data:
            self._active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._active_href is None:
            return

        self.links.append(
            {
                "job_id": self._active_job_id or "",
                "url": self._active_href,
                "title": normalize_text(" ".join(self._active_text)),
            }
        )
        self._active_href = None
        self._active_job_id = None
        self._active_text = []


class IcimsClient:
    """Small reusable client for iCIMS career sites.

    The iCIMS support deliberately starts from public HTML:
    - direct job URLs hydrate from the job page's JSON-LD when present
    - search pages are scanned for /jobs/{id}/job links, then hydrated as needed
    """

    def __init__(self, config: IcimsSiteConfig, *, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def fetch_search_page(
        self,
        *,
        page: int = 1,
        search_text: str | None = None,
    ) -> str:
        query = self.config.default_search_text if search_text is None else search_text
        params = {
            "ss": "1",
            "pr": max(page - 1, 0),
        }
        if query:
            params["searchKeyword"] = query

        response = self.session.get(
            self.config.search_url,
            headers=self.config.html_headers,
            params=params,
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        return response.text

    def fetch_page(
        self,
        page: int = 1,
        *,
        limit: int | None = None,
        search_text: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        html_text = self.fetch_search_page(page=page, search_text=search_text)
        summaries = self._summaries_from_search_html(html_text)
        actual_limit = limit or self.config.page_size
        return {
            "jobPostings": summaries[:actual_limit],
            "total": len(summaries),
            "raw": {"page": page},
        }

    def iter_summaries(
        self,
        *,
        max_pages: int | None = None,
        limit: int | None = None,
        sleep_seconds: float = 0.0,
        search_text: str | None = None,
        **_: Any,
    ) -> Iterable[dict[str, Any]]:
        if self.config.job_id:
            yield self._summary_for_job_id(self.config.job_id)
            return

        seen_job_ids: set[str] = set()
        page = 1
        actual_limit = limit or self.config.page_size
        while True:
            if max_pages is not None and page > max_pages:
                return

            data = self.fetch_page(page=page, limit=actual_limit, search_text=search_text)
            postings = data.get("jobPostings") or []
            if not postings:
                return

            yielded_on_page = 0
            for posting in postings:
                if not isinstance(posting, dict):
                    continue
                job_id = str(posting.get("jobId") or posting.get("id") or "")
                if job_id in seen_job_ids:
                    continue
                seen_job_ids.add(job_id)
                yielded_on_page += 1
                yield posting

            if yielded_on_page == 0 or len(postings) < actual_limit:
                return

            page += 1
            if sleep_seconds:
                time.sleep(sleep_seconds)

    def hydrate_posting(self, summary: dict[str, Any]) -> JobPosting:
        job_id = str(summary.get("jobId") or summary.get("id") or summary.get("uid") or self.config.job_id or "")
        url = str(summary.get("url") or summary.get("externalPath") or self.config.job_url(job_id))
        if not url.startswith(("http://", "https://")):
            url = urljoin(self.config.base_url, url)

        response = self.session.get(url, headers=self.config.html_headers, timeout=self.config.timeout_seconds)
        response.raise_for_status()
        html_text = response.text
        json_ld = _job_posting_from_json_ld(extract_json_ld(html_text))

        description_html = str(json_ld.get("description") or "")
        if not description_html:
            description_html = _extract_icims_description_html(html_text)
        description_text = clean_description(description_html) or html_to_text(description_html)

        identifier = _identifier_value(json_ld.get("identifier"))
        title = str(json_ld.get("title") or summary.get("title") or summary.get("titleSimple") or "")
        location = _location_text(json_ld.get("jobLocation")) or str(summary.get("locationsText") or "")

        return JobPosting(
            source=self.config.source_name,
            req_id=identifier or str(summary.get("req_id") or job_id),
            title=title,
            location=location,
            posted=str(summary.get("postedOn") or json_ld.get("datePosted") or ""),
            url=url,
            job_id=job_id,
            employment_type=_string_or_none(json_ld.get("employmentType")),
            date_posted=_string_or_none(json_ld.get("datePosted")),
            valid_through=_string_or_none(json_ld.get("validThrough")),
            hiring_organization=_hiring_organization_name(json_ld.get("hiringOrganization")),
            description_html=description_html or None,
            description_text=description_text,
            raw_summary=summary,
            raw_json_ld=json_ld,
        )

    def lightweight_job_from_summary(self, summary: dict[str, Any]) -> JobPosting:
        job_id = str(summary.get("jobId") or summary.get("id") or summary.get("uid") or "")
        return JobPosting(
            source=self.config.source_name,
            req_id=str(summary.get("req_id") or job_id),
            title=str(summary.get("title") or summary.get("titleSimple") or ""),
            location=str(summary.get("locationsText") or ""),
            posted=str(summary.get("postedOn") or ""),
            url=str(summary.get("url") or self.config.job_url(job_id)),
            job_id=job_id,
            raw_summary=summary,
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
        for summary in self.iter_summaries(max_pages=max_pages, limit=limit, sleep_seconds=sleep_seconds, **kwargs):
            job = self.hydrate_posting(summary) if hydrate else self.lightweight_job_from_summary(summary)
            jobs.append(job)
            if max_jobs is not None and len(jobs) >= max_jobs:
                break
        return jobs

    def search_location_options(self, *_: Any, **__: Any) -> list[Any]:
        # iCIMS search pages do not expose Workday-style location facets. Use post-filtering
        # on hydrated jobs instead.
        return []

    def _summary_for_job_id(self, job_id: str) -> dict[str, Any]:
        return {
            "id": job_id,
            "jobId": job_id,
            "uid": job_id,
            "req_id": job_id,
            "title": "",
            "titleSimple": "",
            "locationsText": "",
            "postedOn": "",
            "externalPath": f"/jobs/{job_id}/job",
            "url": self.config.job_url(job_id),
        }

    def _summaries_from_search_html(self, html_text: str) -> list[dict[str, Any]]:
        links = extract_icims_job_links(html_text, self.config.base_url)
        return [
            {
                "id": link["job_id"],
                "jobId": link["job_id"],
                "uid": link["job_id"],
                "req_id": link["job_id"],
                "title": link["title"],
                "titleSimple": link["title"],
                "locationsText": "",
                "postedOn": "",
                "externalPath": f"/jobs/{link['job_id']}/job",
                "url": link["url"],
            }
            for link in links
        ]


def is_icims_host(host: str) -> bool:
    host = host.lower().split(":", 1)[0]
    return host == "icims.com" or host.endswith(".icims.com")


def is_icims_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.netloc and is_icims_host(parsed.netloc))


def extract_icims_job_links(html_text: str, base_url: str) -> list[dict[str, str]]:
    parser = _IcimsLinkParser(base_url)
    parser.feed(html_text or "")

    links = list(parser.links)
    for match in ICIMS_JOB_LINK_RE.finditer(html_text or ""):
        href = match.group("href")
        job_id = match.group("job_id")
        links.append({"job_id": job_id, "url": urljoin(base_url, href), "title": ""})

    unique: dict[str, dict[str, str]] = {}
    for link in links:
        job_id = link.get("job_id") or ""
        if not job_id:
            continue
        if job_id not in unique or (not unique[job_id].get("title") and link.get("title")):
            unique[job_id] = {
                "job_id": job_id,
                "url": link.get("url") or urljoin(base_url, f"/jobs/{job_id}/job"),
                "title": link.get("title") or "",
            }
    return list(unique.values())


def _job_posting_from_json_ld(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    data_type = data.get("@type")
    if data_type == "JobPosting" or (isinstance(data_type, list) and "JobPosting" in data_type):
        return data

    graph = data.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type")
            if item_type == "JobPosting" or (isinstance(item_type, list) and "JobPosting" in item_type):
                return item

    return data


def _extract_icims_description_html(html_text: str) -> str:
    # Many iCIMS pages wrap the body in an icims_JobContent container. This fallback is
    # intentionally conservative; JSON-LD remains the primary source when available.
    patterns = [
        r'<div[^>]+id=["\']icims_JobContent["\'][^>]*>(?P<body>.*?)(?:<div[^>]+id=["\']icims_JobOptions|</body>)',
        r'<section[^>]+id=["\']icims_JobContent["\'][^>]*>(?P<body>.*?)</section>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text or "", flags=re.I | re.S)
        if match:
            return match.group("body")
    return ""


def _identifier_value(identifier: Any) -> str:
    if isinstance(identifier, dict):
        return str(identifier.get("value") or identifier.get("name") or "")
    if isinstance(identifier, list):
        for item in identifier:
            value = _identifier_value(item)
            if value:
                return value
    return str(identifier or "")


def _location_text(job_location: Any) -> str:
    if isinstance(job_location, list):
        return ", ".join(part for part in (_location_text(item) for item in job_location) if part)
    if isinstance(job_location, str):
        return job_location
    if not isinstance(job_location, dict):
        return ""

    address = job_location.get("address") if isinstance(job_location, dict) else None
    if isinstance(address, str):
        return address
    if not isinstance(address, dict):
        address = job_location

    parts: list[str] = []
    for key in ("addressLocality", "addressRegion", "addressCountry", "streetAddress"):
        value = address.get(key)
        if isinstance(value, dict):
            value = value.get("name")
        if value:
            parts.append(str(value))
    return ", ".join(dict.fromkeys(parts))


def _hiring_organization_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _string_or_none(value.get("name"))
    return _string_or_none(value)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value)
