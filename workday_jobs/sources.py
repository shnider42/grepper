from __future__ import annotations

from dataclasses import replace
from typing import TypeAlias

from .client import WorkdayClient
from .config import WorkdaySiteConfig
from .icims import IcimsClient, IcimsSiteConfig, is_icims_url


SiteConfig: TypeAlias = WorkdaySiteConfig | IcimsSiteConfig
JobClient: TypeAlias = WorkdayClient | IcimsClient


def config_from_public_url(
    url: str,
    *,
    locale: str = "en-US",
    page_size: int = 20,
    search_text: str = "",
) -> SiteConfig:
    """Infer a provider-specific config from a public careers URL."""
    if is_icims_url(url):
        parsed = IcimsSiteConfig.from_public_url(url)
        return replace(
            parsed,
            default_search_text=search_text or parsed.default_search_text,
            page_size=page_size,
        )

    parsed = WorkdaySiteConfig.from_public_url(url, locale=locale)
    return WorkdaySiteConfig(
        base_url=parsed.base_url,
        tenant=parsed.tenant,
        site=parsed.site,
        locale=parsed.locale,
        public_path_prefix=parsed.public_path_prefix,
        default_facets=parsed.default_facets,
        default_search_text=search_text,
        page_size=page_size,
    )


def client_from_config(config: SiteConfig) -> JobClient:
    if isinstance(config, IcimsSiteConfig):
        return IcimsClient(config)
    return WorkdayClient(config)


def provider_name(config: SiteConfig) -> str:
    if isinstance(config, IcimsSiteConfig):
        return "iCIMS"
    return "Workday"


def supports_workday_facets(config: SiteConfig) -> bool:
    return isinstance(config, WorkdaySiteConfig)
