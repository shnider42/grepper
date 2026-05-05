from __future__ import annotations

import argparse
from pathlib import Path

from .config import WorkdaySiteConfig
from .exporters import write_ranked_csv, write_ranked_json
from .facets import merge_facets
from .filtering import filter_jobs_by_locations
from .ranker import KeywordRanker, load_profile
from .sources import (
    SiteConfig,
    client_from_config,
    config_from_public_url as infer_config_from_public_url,
    provider_name,
    supports_workday_facets,
)


def _parse_facets(values: list[str] | None) -> dict[str, list[str]]:
    facets: dict[str, list[str]] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"Facet must be key=value, got: {value!r}")
        key, raw = value.split("=", 1)
        facets.setdefault(key, []).append(raw)
    return facets


def _parse_weights(values: list[str] | None) -> dict[str, float]:
    weights: dict[str, float] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"Weight must be term=number, got: {value!r}")
        term, raw_weight = value.split("=", 1)
        term = term.strip()
        if not term:
            raise ValueError(f"Weight term cannot be empty: {value!r}")
        try:
            weights[term] = float(raw_weight)
        except ValueError as exc:
            raise ValueError(f"Weight must be numeric for {term!r}, got: {raw_weight!r}") from exc
    return weights


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape and rank jobs from supported career sites.")
    parser.add_argument("--url", help="Public Workday or iCIMS URL. Workday facets in the query string are reused automatically.")
    parser.add_argument("--base-url", help="Explicit Workday base URL, e.g. https://draper.wd5.myworkdayjobs.com")
    parser.add_argument("--tenant", help="Explicit Workday tenant, e.g. draper")
    parser.add_argument("--site", help="Explicit Workday site, e.g. Draper_Careers")
    parser.add_argument("--locale", default="en-US")
    parser.add_argument("--facet", action="append", help="Workday applied facet as key=value. Repeat for multiple values.")
    parser.add_argument("--query", default="", help="Provider search text value.")
    parser.add_argument(
        "--profile",
        help="Path to a JSON Profile file containing weighted keywords and scoring settings.",
    )
    parser.add_argument(
        "--weight",
        action="append",
        help="Temporary Profile override as term=number. Repeat for multiple terms.",
    )
    parser.add_argument(
        "--location",
        action="append",
        help=(
            "Human location search. Workday resolves this to provider facets; iCIMS applies it "
            "as a post-filter after hydrated jobs are fetched."
        ),
    )
    parser.add_argument(
        "--location-matches",
        type=int,
        default=1,
        help="Number of matching Workday location facet values to apply for each --location.",
    )
    parser.add_argument(
        "--list-locations",
        action="store_true",
        help="Resolve Workday --location terms and print matching facet values without scraping jobs.",
    )
    parser.add_argument("--pages", type=int, default=3, help="Max pages to fetch.")
    parser.add_argument("--page-size", type=int, default=20, help="Jobs per list/search request.")
    parser.add_argument("--max-jobs", type=int, default=50, help="Max jobs to hydrate/rank.")
    parser.add_argument("--no-hydrate", action="store_true", help="Only use list-page data; faster but weaker ranking.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between list pages.")
    parser.add_argument("--csv", help="Optional output CSV path.")
    parser.add_argument("--json", help="Optional output JSON path.")
    parser.add_argument("--top", type=int, default=25, help="Number of ranked jobs to print.")
    return parser


def config_from_args(args: argparse.Namespace) -> SiteConfig:
    cli_facets = _parse_facets(args.facet)

    if args.url:
        parsed_config = infer_config_from_public_url(
            args.url,
            locale=args.locale,
            page_size=args.page_size,
            search_text=args.query,
        )
        if supports_workday_facets(parsed_config) and cli_facets:
            merged_facets = dict(parsed_config.default_facets)
            for key, values in cli_facets.items():
                merged_facets.setdefault(key, []).extend(values)
            return WorkdaySiteConfig(
                base_url=parsed_config.base_url,
                tenant=parsed_config.tenant,
                site=parsed_config.site,
                locale=parsed_config.locale,
                public_path_prefix=parsed_config.public_path_prefix,
                default_facets=merged_facets,
                default_search_text=args.query,
                page_size=args.page_size,
            )
        if cli_facets:
            raise SystemExit("--facet is currently Workday-only; remove --facet for iCIMS URLs.")
        return parsed_config

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

    client = client_from_config(config)
    runtime_facets = dict(config.default_facets) if supports_workday_facets(config) else {}
    location_queries = [query for query in (args.location or []) if query.strip()]

    if location_queries and supports_workday_facets(config):
        resolved_location_facets: dict[str, list[str]] = {}
        for location_query in location_queries:
            matches = client.search_location_options(
                location_query,
                applied_facets=runtime_facets,
                limit=max(args.location_matches, 1),
            )
            if not matches:
                print(f"No Workday location facet match found for: {location_query!r}")
                continue

            print(f"Location matches for {location_query!r}:")
            for match in matches:
                print(
                    f"  {match.facet_key}={match.value}  "
                    f"{match.label}  score={match.score}  count={match.count}"
                )

            resolved_location_facets = merge_facets(
                resolved_location_facets,
                *(match.as_facet_dict() for match in matches[: args.location_matches]),
            )

        runtime_facets = merge_facets(runtime_facets, resolved_location_facets)
    elif location_queries:
        print("iCIMS location facets are not available; applying --location as a post-filter after hydration.")

    if args.list_locations:
        if not supports_workday_facets(config):
            print("--list-locations is currently Workday-only because iCIMS does not expose the same facet metadata.")
        return 0

    discover_kwargs = {"applied_facets": runtime_facets} if supports_workday_facets(config) else {}
    jobs = client.discover_jobs(
        max_pages=args.pages,
        limit=args.page_size,
        max_jobs=args.max_jobs,
        hydrate=not args.no_hydrate,
        sleep_seconds=args.sleep,
        **discover_kwargs,
    )

    if location_queries and not supports_workday_facets(config):
        jobs = filter_jobs_by_locations(jobs, location_queries)

    profile = load_profile(args.profile)
    weights = _parse_weights(args.weight)
    ranked = KeywordRanker(profile).rank(jobs, weights=weights)

    print(f"Provider: {provider_name(config)}")
    for item in ranked[: args.top]:
        job = item.job
        print(f"Score: {item.score}\nTitle: {job.title}\nReq: {job.req_id}\nLocation: {job.location}\nURL: {job.url}")
        if item.matches.get("core"):
            print("Core:", ", ".join(item.matches["core"][:10]))
        if item.matches.get("nice"):
            print("Nice:", ", ".join(item.matches["nice"][:10]))
        if item.matches.get("neg"):
            print("Negative:", ", ".join(item.matches["neg"][:10]))
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
