from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class WorkdaySiteConfig:
    """Everything that varies from one Workday careers site to another.

    Examples:
        Cisco:   base_url=https://cisco.wd5.myworkdayjobs.com, tenant=cisco, site=Cisco_Careers
        Draper:  base_url=https://draper.wd5.myworkdayjobs.com, tenant=draper, site=Draper_Careers
        NVIDIA:  base_url=https://nvidia.wd5.myworkdayjobs.com, tenant=nvidia, site=NVIDIAExternalCareerSite
        Fidelity: base_url=https://wd1.myworkdaysite.com, tenant=fmr, site=FidelityCareers
    """

    base_url: str
    tenant: str
    site: str
    locale: str = "en-US"
    public_path_prefix: str | None = None
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
        if self.public_path_prefix:
            return self.public_path_prefix if self.public_path_prefix.startswith("/") else f"/{self.public_path_prefix}"
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
            https://wd1.myworkdaysite.com/en-US/recruiting/fmr/FidelityCareers
        """
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Expected absolute Workday URL, got: {url!r}")

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        tenant = parsed.netloc.split(".", 1)[0]

        path_parts = [p for p in parsed.path.split("/") if p]
        site = None
        public_path_prefix = None

        remaining_parts = path_parts
        prefix_parts_before_site = 0
        if path_parts:
            if _is_locale_path_part(path_parts[0]) and len(path_parts) > 1:
                locale = path_parts[0]
                remaining_parts = path_parts[1:]
                prefix_parts_before_site = 1

            if len(remaining_parts) >= 3 and remaining_parts[0].lower() == "recruiting":
                # Newer shared Workday host shape:
                # /en-US/recruiting/{tenant}/{site}/...
                tenant = remaining_parts[1]
                site = remaining_parts[2]
                public_path_prefix = "/" + "/".join(path_parts[: prefix_parts_before_site + 3])
            elif remaining_parts:
                site = remaining_parts[0]

        if not site:
            raise ValueError(f"Could not infer Workday site name from URL: {url!r}")

        facets = facets_from_query(parsed.query)
        return cls(
            base_url=base_url,
            tenant=tenant,
            site=site,
            locale=locale,
            public_path_prefix=public_path_prefix,
            default_facets=facets,
        )


def _is_locale_path_part(part: str) -> bool:
    return part.lower() in {"en-us", "en_us", "fr-fr", "de-de"}


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
