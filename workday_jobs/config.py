from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class WorkdaySiteConfig:
    """Everything that varies from one Workday careers site to another.

    Examples:
        Cisco:  base_url=https://cisco.wd5.myworkdayjobs.com, tenant=cisco, site=Cisco_Careers
        Draper: base_url=https://draper.wd5.myworkdayjobs.com, tenant=draper, site=Draper_Careers
        NVIDIA: base_url=https://nvidia.wd5.myworkdayjobs.com, tenant=nvidia, site=NVIDIAExternalCareerSite
    """

    base_url: str
    tenant: str
    site: str
    locale: str = "en-US"
    default_facets: dict[str, list[str]] = field(default_factory=dict)
    default_search_text: str = ""
    page_size: int = 20
    timeout_seconds: int = 30

    @property
    def list_url(self) -> str:
        return f"{self.base_url}/wday/cxs/{self.tenant}/{self.site}/jobs"

    @property
    def detail_json_url(self) -> str:
        return f"{self.base_url}/wday/cxs/{self.tenant}/{self.site}/job"

    @property
    def public_site_prefix(self) -> str:
        return f"/{self.locale}/{self.site}"

    @property
    def referer(self) -> str:
        return f"{self.base_url}{self.public_site_prefix}"

    @property
    def api_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Grepper Workday research tool)",
            "Accept": "application/json, text/plain, */*",
            "Origin": self.base_url,
            "Referer": self.referer,
        }

    @property
    def html_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Grepper Workday research tool)",
            "Accept-Language": "en-US,en;q=0.9",
        }

    @classmethod
    def from_public_url(cls, url: str, *, locale: str = "en-US") -> "WorkdaySiteConfig":
        """Infer base URL, tenant, site, and facet query params from a Workday public URL.

        This handles URLs like:
            https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?locationHierarchy1=...
            https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers/details/...
        """
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Expected absolute Workday URL, got: {url!r}")

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        tenant = parsed.netloc.split(".", 1)[0]

        path_parts = [p for p in parsed.path.split("/") if p]
        site = None
        if path_parts:
            if path_parts[0].lower() in {"en-us", "en_us", "fr-fr", "de-de"} and len(path_parts) > 1:
                locale = path_parts[0]
                site = path_parts[1]
            else:
                site = path_parts[0]

        if not site:
            raise ValueError(f"Could not infer Workday site name from URL: {url!r}")

        facets = facets_from_query(parsed.query)
        return cls(base_url=base_url, tenant=tenant, site=site, locale=locale, default_facets=facets)


def facets_from_query(query: str | Mapping[str, list[str] | str]) -> dict[str, list[str]]:
    """Convert URL query params to Workday's appliedFacets shape.

    Repeated query keys become lists. That matters for Workday URLs like:
        ?jobFamilyGroup=A&jobFamilyGroup=B
    """
    if isinstance(query, str):
        raw = parse_qs(query, keep_blank_values=False)
    else:
        raw = dict(query)

    facets: dict[str, list[str]] = {}
    for key, value in raw.items():
        if key in {"q", "query", "searchText"}:
            continue
        if isinstance(value, str):
            facets[key] = [value]
        else:
            facets[key] = [str(v) for v in value if str(v)]
    return facets
