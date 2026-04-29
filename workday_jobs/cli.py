from __future__ import annotations

import argparse
import json
from pathlib import Path

from .client import WorkdayClient
from .config import WorkdaySiteConfig, facets_from_query
from .exporters import write_ranked_csv, write_ranked_json
from .ranker import KeywordRanker


def _parse_facets(values: list[str] | None) -> dict[str, list[str]]:
    facets: dict[str, list[str]] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"Facet must be key=value, got: {value!r}")
        key, raw = value.split("=", 1)
        facets.setdefault(key, []).append(raw)
    return facets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape and rank jobs from a Workday-powered career site.")
    parser.add_argument("--url", help="Public Workday URL. Facets in the query string are reused automatically.")
    parser.add_argument("--base-url", help="Example: https://draper.wd5.myworkdayjobs.com")
    parser.add_argument("--tenant", help="Example: draper")
    parser.add_argument("--site", help="Example: Draper_Careers")
    parser.add_argument("--locale", default="en-US")
    parser.add_argument("--facet", action="append", help="Applied facet as key=value. Repeat for multiple values.")
    parser.add_argument("--query", default="", help="Workday searchText value.")
    parser.add_argument("--pages", type=int, default=3, help="Max pages to fetch.")
    parser.add_argument("--page-size", type=int, default=20, help="Jobs per Workday list request.")
    parser.add_argument("--max-jobs", type=int, default=50, help="Max jobs to hydrate/rank.")
    parser.add_argument("--no-hydrate", action="store_true", help="Only use list-page data; faster but weaker ranking.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between list pages.")
    parser.add_argument("--csv", help="Optional output CSV path.")
    parser.add_argument("--json", help="Optional output JSON path.")
    parser.add_argument("--top", type=int, default=25, help="Number of ranked jobs to print.")
    return parser


def config_from_args(args: argparse.Namespace) -> WorkdaySiteConfig:
    cli_facets = _parse_facets(args.facet)

    if args.url:
        config = WorkdaySiteConfig.from_public_url(args.url, locale=args.locale)
        merged_facets = dict(config.default_facets)
        for key, values in cli_facets.items():
            merged_facets.setdefault(key, []).extend(values)
        return WorkdaySiteConfig(
            base_url=config.base_url,
            tenant=config.tenant,
            site=config.site,
            locale=config.locale,
            default_facets=merged_facets,
            default_search_text=args.query,
            page_size=args.page_size,
        )

    missing = [name for name in ["base_url", "tenant", "site"] if getattr(args, name) is None]
    if missing:
        raise SystemExit(f"Either provide --url or provide --base-url, --tenant, and --site. Missing: {missing}")

    return WorkdaySiteConfig(
        base_url=args.base_url,
        tenant=args.tenant,
        site=args.site,
        locale=args.locale,
        default_facets=cli_facets,
        default_search_text=args.query,
        page_size=args.page_size,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    client = WorkdayClient(config)
    jobs = client.discover_jobs(
        max_pages=args.pages,
        limit=args.page_size,
        max_jobs=args.max_jobs,
        hydrate=not args.no_hydrate,
        sleep_seconds=args.sleep,
    )
    ranked = KeywordRanker().rank(jobs)

    for item in ranked[: args.top]:
        job = item.job
        print(f"Score: {item.score}\nTitle: {job.title}\nReq: {job.req_id}\nLocation: {job.location}\nURL: {job.url}")
        if item.matches.get("core"):
            print("Core:", ", ".join(item.matches["core"][:10]))
        print("---")

    if args.csv:
        write_ranked_csv(args.csv, ranked)
        print(f"Wrote CSV: {Path(args.csv).resolve()}")
    if args.json:
        write_ranked_json(args.json, ranked)
        print(f"Wrote JSON: {Path(args.json).resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
