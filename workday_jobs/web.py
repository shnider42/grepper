from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import Flask, render_template_string, request

from .client import WorkdayClient
from .facets import FacetOption, merge_facets, normalize_for_match
from .filtering import filter_jobs_by_locations, job_matches_location
from .icims import IcimsClient, IcimsSiteConfig
from .models import JobPosting
from .parsing import build_public_job_url, compact_location, compact_posted_on, parse_req_id_from_path
from .ranker import KeywordRanker
from .sources import SiteConfig, client_from_config, config_from_public_url, provider_name, supports_workday_facets


DEFAULT_EXAMPLES = {
    "Cisco": "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers",
    "NVIDIA": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
    "Draper": "https://draper.wd5.myworkdayjobs.com/en-US/Draper_Careers",
    "Fidelity": "https://wd1.myworkdaysite.com/en-US/recruiting/fmr/FidelityCareers",
    "Netflix": "https://explore.jobs.netflix.net/careers",
    "Cushman & Wakefield": "https://cw.wd1.myworkdayjobs.com/en-US/External",
    "Dalcour Maclaren": "https://dalcourmaclaren.wd3.myworkdayjobs.com/Dalcour-Maclaren-Careers",
    "Pape-Dawson": "https://papedawson.wd12.myworkdayjobs.com/pde",
    "Old Republic Title": "https://oldrepublic.wd1.myworkdayjobs.com/oldrepublictitle",
    "Suffolk Construction iCIMS": "https://careers-suffolkconstruction.icims.com/jobs/search",
}


@dataclass
class SearchForm:
    url: str = DEFAULT_EXAMPLES["Cisco"]
    location: str = ""
    query: str = ""
    title_keywords: str = ""
    pages: int = 10
    page_size: int = 20
    max_jobs: int = 50
    top: int = 25
    location_matches: int = 1
    hydrate: bool = True
    action: str = "rank"


def parse_terms(raw: str) -> list[str]:
    return [chunk.strip() for chunk in raw.replace("\n", ",").split(",") if chunk.strip()]


def parse_location_queries(raw: str) -> list[str]:
    return parse_terms(raw)


def parse_title_keywords(raw: str) -> list[str]:
    return parse_terms(raw)


def title_matches_keywords(title: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    normalized_title = normalize_for_match(title)
    return any(normalize_for_match(keyword) in normalized_title for keyword in keywords)


def _safe_int(value: str | None, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def form_from_request() -> SearchForm:
    if request.method != "POST":
        return SearchForm()

    return SearchForm(
        url=(request.form.get("url") or "").strip(),
        location=(request.form.get("location") or "").strip(),
        query=(request.form.get("query") or "").strip(),
        title_keywords=(request.form.get("title_keywords") or "").strip(),
        pages=_safe_int(request.form.get("pages"), 10, minimum=1, maximum=100),
        page_size=_safe_int(request.form.get("page_size"), 20, minimum=1, maximum=100),
        max_jobs=_safe_int(request.form.get("max_jobs"), 50, minimum=1, maximum=500),
        top=_safe_int(request.form.get("top"), 25, minimum=1, maximum=100),
        location_matches=_safe_int(request.form.get("location_matches"), 1, minimum=1, maximum=50),
        hydrate=request.form.get("hydrate") == "on",
        action=request.form.get("action") or "rank",
    )


def lightweight_job_from_summary(client: WorkdayClient | IcimsClient, summary: dict[str, Any]) -> JobPosting:
    if isinstance(client, IcimsClient):
        return client.lightweight_job_from_summary(summary)

    external_path = summary.get("externalPath") or summary.get("externalPathAndQuery") or ""
    url = build_public_job_url(
        client.config.base_url,
        client.config.site,
        str(external_path),
        locale=client.config.locale,
        public_path_prefix=client.config.public_site_prefix,
    )
    return JobPosting(
        source=client.config.site,
        req_id=parse_req_id_from_path(str(external_path)),
        title=str(summary.get("title") or summary.get("titleSimple") or ""),
        location=compact_location(summary),
        posted=compact_posted_on(summary),
        url=url,
        job_id=str(summary.get("id") or summary.get("jobId") or summary.get("uid") or ""),
        raw_summary=summary,
    )


def discover_filtered_jobs(
    client: WorkdayClient | IcimsClient,
    config: SiteConfig,
    *,
    location_queries: list[str],
    title_keywords: list[str],
    applied_facets: dict[str, list[str]],
    max_pages: int,
    page_size: int,
    max_jobs: int,
    hydrate: bool,
) -> tuple[list[JobPosting], int]:
    if isinstance(config, IcimsSiteConfig):
        jobs = client.discover_jobs(max_pages=max_pages, limit=page_size, max_jobs=max_jobs, hydrate=True if location_queries else hydrate)
        if title_keywords:
            jobs = [job for job in jobs if title_matches_keywords(job.title, title_keywords)]
        if location_queries:
            jobs = filter_jobs_by_locations(jobs, location_queries)
        return jobs[:max_jobs], len(jobs)

    matched_summaries: list[dict[str, Any]] = []
    scanned = 0
    for summary in client.iter_summaries(max_pages=max_pages, limit=page_size, applied_facets=applied_facets):
        scanned += 1
        lightweight_job = lightweight_job_from_summary(client, summary)
        if not title_matches_keywords(lightweight_job.title, title_keywords):
            continue
        if location_queries and not any(job_matches_location(lightweight_job, query) for query in location_queries):
            continue
        matched_summaries.append(summary)
        if len(matched_summaries) >= max_jobs:
            break

    if hydrate:
        return [client.hydrate_posting(summary) for summary in matched_summaries], scanned
    return [lightweight_job_from_summary(client, summary) for summary in matched_summaries], scanned


def config_label(config: SiteConfig) -> str:
    if isinstance(config, IcimsSiteConfig):
        return config.company_slug
    return config.site


def run_search(form: SearchForm) -> dict[str, Any]:
    config = config_from_public_url(form.url, page_size=form.page_size, search_text=form.query)
    client = client_from_config(config)
    runtime_facets = dict(config.default_facets) if supports_workday_facets(config) else {}
    location_queries = parse_location_queries(form.location)
    title_keywords = parse_title_keywords(form.title_keywords)

    location_matches: dict[str, list[FacetOption]] = {}
    if supports_workday_facets(config):
        for query in location_queries:
            matches = client.search_location_options(query, applied_facets=runtime_facets, limit=form.location_matches)
            location_matches[query] = matches
            runtime_facets = merge_facets(runtime_facets, *(match.as_facet_dict() for match in matches))
    else:
        location_matches = {query: [] for query in location_queries}

    if form.action == "locations":
        return _result(config, runtime_facets, location_matches, [], 0, 0, False, title_keywords)

    browser_filters_active = bool(location_queries or title_keywords)
    if browser_filters_active:
        filtered_jobs, scanned_count = discover_filtered_jobs(
            client,
            config,
            location_queries=location_queries,
            title_keywords=title_keywords,
            applied_facets=runtime_facets,
            max_pages=form.pages,
            page_size=form.page_size,
            max_jobs=form.max_jobs,
            hydrate=form.hydrate,
        )
        raw_job_count = scanned_count
    else:
        discover_kwargs = {"applied_facets": runtime_facets} if supports_workday_facets(config) else {}
        filtered_jobs = client.discover_jobs(
            max_pages=form.pages,
            limit=form.page_size,
            max_jobs=form.max_jobs,
            hydrate=form.hydrate,
            **discover_kwargs,
        )
        raw_job_count = len(filtered_jobs)

    ranked = KeywordRanker().rank(filtered_jobs)[: form.top]
    return _result(config, runtime_facets, location_matches, ranked, raw_job_count, len(filtered_jobs), browser_filters_active, title_keywords)


def _result(
    config: SiteConfig,
    runtime_facets: dict[str, list[str]],
    location_matches: dict[str, list[FacetOption]],
    ranked: list[Any],
    raw_job_count: int,
    filtered_job_count: int,
    browser_filter_applied: bool,
    title_keywords: list[str],
) -> dict[str, Any]:
    return {
        "config": config,
        "provider": provider_name(config),
        "config_label": config_label(config),
        "runtime_facets": runtime_facets,
        "location_matches": location_matches,
        "ranked": ranked,
        "raw_job_count": raw_job_count,
        "filtered_job_count": filtered_job_count,
        "browser_filter_applied": browser_filter_applied,
        "title_keywords": title_keywords,
        "supports_facets": supports_workday_facets(config),
    }


PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Grepper Jobs Ranker</title>
  <style>
    :root { --bg:#081018; --panel:#0f1720; --text:#f3f4f6; --muted:#a8b3bf; --accent:#ff8a3d; --border:#233142; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:radial-gradient(circle at top left,#112235 0,var(--bg) 42%); color:var(--text); }
    a { color:#ffb37f; }
    .page { max-width:1180px; margin:0 auto; padding:32px 18px 60px; }
    .hero { margin-bottom:24px; }
    .hero h1 { margin:0 0 8px; font-size:clamp(2rem,4vw,3.25rem); letter-spacing:-.05em; }
    .hero p,.hint,.meta { color:var(--muted); }
    .layout { display:grid; grid-template-columns:minmax(300px,410px) 1fr; gap:20px; align-items:start; }
    @media (max-width:900px){ .layout{grid-template-columns:1fr;} }
    .card,.form-card { background:rgba(15,23,32,.92); border:1px solid var(--border); border-radius:18px; box-shadow:0 18px 50px rgba(0,0,0,.25); }
    .form-card { padding:18px; position:sticky; top:18px; }
    label { display:block; font-weight:700; margin:14px 0 6px; color:#dbe3ec; }
    input[type="text"],input[type="number"],textarea { width:100%; border:1px solid #314358; background:#09131e; color:var(--text); border-radius:12px; padding:11px 12px; font:inherit; outline:none; }
    textarea { min-height:72px; resize:vertical; }
    .row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .check { display:flex; align-items:center; gap:8px; margin-top:14px; color:var(--muted); }
    .actions,.examples { display:flex; gap:10px; margin-top:18px; flex-wrap:wrap; }
    button { border:0; border-radius:999px; padding:11px 16px; font-weight:800; cursor:pointer; color:#101010; background:linear-gradient(135deg,var(--accent),#ffad72); }
    button.secondary { background:#203044; color:var(--text); border:1px solid #3a4e66; }
    .example-pill { border:1px solid #33475f; color:var(--muted); background:#0b1420; border-radius:999px; padding:6px 9px; font-size:.82rem; cursor:pointer; }
    .summary,.job,.error { padding:16px; margin-bottom:16px; }
    .error { border-color:rgba(255,107,107,.55); color:#ffd1d1; }
    .job h3 { margin:0 0 6px; }
    .score { color:#7dff9b; font-weight:900; }
    .matches { margin-top:10px; color:#c6d0da; font-size:.9rem; }
    code { background:#081018; padding:2px 5px; border-radius:6px; color:#ffc18f; }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero"><h1>Grepper Jobs Ranker</h1><p>Paste a supported careers URL. Workday uses CXS APIs; iCIMS starts from public job/search pages.</p></section>
    <div class="layout">
      <form class="form-card" method="post">
        <label for="url">Careers URL</label><input id="url" name="url" type="text" value="{{ form.url }}">
        <div class="hint">Supports Workday and iCIMS URLs like <code>careers-suffolkconstruction.icims.com/jobs/11113/job</code>.</div>
        <div class="examples">{% for label, url in examples.items() %}<button type="button" class="example-pill" onclick="document.getElementById('url').value='{{ url }}'">{{ label }}</button>{% endfor %}</div>
        <label for="query">Provider search text</label><input id="query" name="query" type="text" value="{{ form.query }}">
        <label for="location">Locations</label><textarea id="location" name="location">{{ form.location }}</textarea>
        <div class="hint">Workday resolves to facets. iCIMS filters hydrated jobs.</div>
        <label for="title_keywords">Title keywords</label><textarea id="title_keywords" name="title_keywords">{{ form.title_keywords }}</textarea>
        <div class="row"><div><label for="pages">Pages</label><input id="pages" name="pages" type="number" value="{{ form.pages }}"></div><div><label for="page_size">Page size</label><input id="page_size" name="page_size" type="number" value="{{ form.page_size }}"></div></div>
        <div class="row"><div><label for="max_jobs">Max jobs</label><input id="max_jobs" name="max_jobs" type="number" value="{{ form.max_jobs }}"></div><div><label for="top">Show top</label><input id="top" name="top" type="number" value="{{ form.top }}"></div></div>
        <label for="location_matches">Workday location matches</label><input id="location_matches" name="location_matches" type="number" value="{{ form.location_matches }}">
        <label class="check"><input type="checkbox" name="hydrate" {% if form.hydrate %}checked{% endif %}> Hydrate job detail pages</label>
        <div class="actions"><button name="action" value="rank" type="submit">Rank jobs</button><button class="secondary" name="action" value="locations" type="submit">Check locations</button></div>
      </form>
      <main>
        {% if error %}<div class="card error">{{ error }}</div>{% endif %}
        {% if result %}
          <section class="card summary"><div><strong>Provider:</strong> {{ result.provider }}</div><div><strong>Source:</strong> <code>{{ result.config_label }}</code></div><div><strong>Scanned:</strong> {{ result.raw_job_count }} · <strong>Filtered:</strong> {{ result.filtered_job_count }} · <strong>Shown:</strong> {{ result.ranked|length }}</div>{% if not result.supports_facets and form.location %}<div class="hint">iCIMS has no Workday-style facets, so location filtering uses hydrated job details.</div>{% endif %}</section>
          {% if result.location_matches %}<section class="card summary"><strong>Location matches</strong>{% for query, matches in result.location_matches.items() %}<p><code>{{ query }}</code></p>{% if matches %}<ul>{% for match in matches %}<li><code>{{ match.facet_key }}={{ match.value }}</code> {{ match.label }} score={{ match.score }} count={{ match.count }}</li>{% endfor %}</ul>{% else %}<p class="hint">No provider facet matches. For iCIMS, this is expected.</p>{% endif %}{% endfor %}</section>{% endif %}
          {% for item in result.ranked %}<article class="card job"><h3><a href="{{ item.job.url }}" target="_blank" rel="noopener">{{ item.job.title or "(untitled)" }}</a></h3><div class="meta"><span class="score">Score {{ item.score }}</span> · Req {{ item.job.req_id or item.job.job_id or "n/a" }} · {{ item.job.location or "Location not listed" }} · {{ item.job.posted or item.job.date_posted or "Posted date unknown" }}</div>{% if item.matches %}<div class="matches">{% if item.matches.get("core") %}<div><strong>Core:</strong> {{ ", ".join(item.matches["core"][:10]) }}</div>{% endif %}{% if item.matches.get("nice") %}<div><strong>Nice:</strong> {{ ", ".join(item.matches["nice"][:10]) }}</div>{% endif %}{% if item.matches.get("neg") %}<div><strong>Negative:</strong> {{ ", ".join(item.matches["neg"][:10]) }}</div>{% endif %}</div>{% endif %}</article>{% endfor %}
          {% if result.ranked|length == 0 and not error %}<section class="card summary">No ranked jobs found for this search.</section>{% endif %}
        {% else %}<section class="card summary">Start with one of the examples or paste a Workday/iCIMS URL.</section>{% endif %}
      </main>
    </div>
  </div>
</body>
</html>
"""


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def index() -> str:
        form = form_from_request()
        result: dict[str, Any] | None = None
        error: str | None = None
        if request.method == "POST":
            try:
                result = run_search(form)
            except Exception as exc:  # pragma: no cover - browser-friendly failure surface
                error = f"{type(exc).__name__}: {exc}"
        return render_template_string(PAGE_TEMPLATE, form=form, examples=DEFAULT_EXAMPLES, result=result, error=error)

    return app


def main() -> None:
    app = create_app()
    app.run(debug=True)


if __name__ == "__main__":
    main()
