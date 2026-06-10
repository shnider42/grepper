from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import Flask, render_template_string, request

from .client import WorkdayClient
from .config import WorkdaySiteConfig
from .facets import FacetOption, merge_facets, normalize_for_match
from .filtering import job_matches_location
from .models import JobPosting
from .parsing import build_public_job_url, compact_location, compact_posted_on, parse_req_id_from_path
from .ranker import KeywordRanker, Profile, default_profile


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
}

PROFILE_LABELS = {
    "chris-default": "Chris: solutions / QE / customer-facing engineering",
    "surveying-legal-property": "Surveying / zoning / legal property",
}

SURVEYING_LEGAL_PROPERTY_PROFILE = Profile(
    name="surveying-legal-property",
    core_plus={
        "surveying": 4.0,
        "zoning": 3.5,
        "property": 2.0,
        "permitting": 2.0,
        "land use": 3.0,
    },
    nice={
        "legal": 1.0,
        "compliance": 1.2,
        "real estate": 1.5,
    },
    light_neg={
        "intern": -2.0,
        "sales": -2.5,
    },
    title_boost=1.35,
    length_bonus_cap=1.25,
    length_bonus_divisor=900.0,
)

PROFILE_PRESETS = {
    "chris-default": default_profile(),
    "surveying-legal-property": SURVEYING_LEGAL_PROPERTY_PROFILE,
}


@dataclass
class SearchForm:
    url: str = DEFAULT_EXAMPLES["Cisco"]
    location: str = ""
    query: str = ""
    title_keywords: str = ""
    profile_key: str = "chris-default"
    core_plus_weights: str = ""
    nice_weights: str = ""
    light_neg_weights: str = ""
    title_boost: float = 1.35
    length_bonus_cap: float = 1.25
    length_bonus_divisor: float = 900.0
    pages: int = 10
    page_size: int = 20
    max_jobs: int = 50
    top: int = 25
    location_matches: int = 1
    hydrate: bool = True
    action: str = "rank"


def parse_terms(raw: str) -> list[str]:
    """Accept comma/newline separated form values."""
    terms: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        value = chunk.strip()
        if value:
            terms.append(value)
    return terms


def parse_location_queries(raw: str) -> list[str]:
    return parse_terms(raw)


def parse_title_keywords(raw: str) -> list[str]:
    return parse_terms(raw)


def title_matches_keywords(title: str, keywords: list[str]) -> bool:
    """Return True when no title filter exists, or any keyword/phrase is in the title."""
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


def _safe_float(value: str | None, default: float, *, minimum: float = 0.0, maximum: float = 10_000.0) -> float:
    try:
        parsed = float(value or default)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def clone_profile(profile: Profile) -> Profile:
    return Profile.from_dict(profile.to_dict())


def profile_preset(key: str) -> Profile:
    return clone_profile(PROFILE_PRESETS.get(key, PROFILE_PRESETS["chris-default"]))


def profile_to_weight_text(weights: dict[str, float]) -> str:
    return "\n".join(f"{term} = {weight:g}" for term, weight in weights.items())


def apply_profile_defaults(form: SearchForm, profile_key: str) -> SearchForm:
    profile = profile_preset(profile_key)
    form.profile_key = profile_key if profile_key in PROFILE_PRESETS else "chris-default"
    form.core_plus_weights = profile_to_weight_text(profile.core_plus)
    form.nice_weights = profile_to_weight_text(profile.nice)
    form.light_neg_weights = profile_to_weight_text(profile.light_neg)
    form.title_boost = profile.title_boost
    form.length_bonus_cap = profile.length_bonus_cap
    form.length_bonus_divisor = profile.length_bonus_divisor
    return form


def parse_weight_text(raw: str, field_name: str) -> dict[str, float]:
    """Parse editable Profile weights from one `term = number` entry per line.

    Commas are accepted too, but newlines are easier to read in the browser.
    """
    weights: dict[str, float] = {}
    for line_number, chunk in enumerate(raw.replace(",", "\n").splitlines(), start=1):
        value = chunk.strip()
        if not value:
            continue
        if "=" not in value:
            raise ValueError(f"{field_name} line {line_number} must look like term = weight: {value!r}")
        term, raw_weight = value.split("=", 1)
        term = term.strip()
        if not term:
            raise ValueError(f"{field_name} line {line_number} has an empty term")
        try:
            weights[term.casefold()] = float(raw_weight.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} line {line_number} has a non-numeric weight: {raw_weight!r}") from exc
    return weights


def profile_from_form(form: SearchForm) -> Profile:
    base_profile = profile_preset(form.profile_key)
    return Profile(
        name=base_profile.name,
        core_plus=parse_weight_text(form.core_plus_weights, "Core weights"),
        nice=parse_weight_text(form.nice_weights, "Nice weights"),
        light_neg=parse_weight_text(form.light_neg_weights, "Negative weights"),
        title_boost=form.title_boost,
        length_bonus_cap=form.length_bonus_cap,
        length_bonus_divisor=form.length_bonus_divisor,
    )


def profile_presets_for_template() -> dict[str, dict[str, Any]]:
    presets: dict[str, dict[str, Any]] = {}
    for key, profile in PROFILE_PRESETS.items():
        presets[key] = {
            "label": PROFILE_LABELS[key],
            "name": profile.name,
            "core_plus_weights": profile_to_weight_text(profile.core_plus),
            "nice_weights": profile_to_weight_text(profile.nice),
            "light_neg_weights": profile_to_weight_text(profile.light_neg),
            "title_boost": profile.title_boost,
            "length_bonus_cap": profile.length_bonus_cap,
            "length_bonus_divisor": profile.length_bonus_divisor,
        }
    return presets


def form_from_request() -> SearchForm:
    if request.method != "POST":
        return apply_profile_defaults(SearchForm(), "chris-default")

    profile_key = request.form.get("profile_key") or "chris-default"
    preset = profile_preset(profile_key)
    return SearchForm(
        url=(request.form.get("url") or "").strip(),
        location=(request.form.get("location") or "").strip(),
        query=(request.form.get("query") or "").strip(),
        title_keywords=(request.form.get("title_keywords") or "").strip(),
        profile_key=profile_key if profile_key in PROFILE_PRESETS else "chris-default",
        core_plus_weights=(request.form.get("core_plus_weights") or "").strip(),
        nice_weights=(request.form.get("nice_weights") or "").strip(),
        light_neg_weights=(request.form.get("light_neg_weights") or "").strip(),
        title_boost=_safe_float(request.form.get("title_boost"), preset.title_boost, minimum=0.0, maximum=10.0),
        length_bonus_cap=_safe_float(request.form.get("length_bonus_cap"), preset.length_bonus_cap, minimum=0.0, maximum=10.0),
        length_bonus_divisor=_safe_float(
            request.form.get("length_bonus_divisor"),
            preset.length_bonus_divisor,
            minimum=1.0,
            maximum=100_000.0,
        ),
        pages=_safe_int(request.form.get("pages"), 10, minimum=1, maximum=100),
        page_size=_safe_int(request.form.get("page_size"), 20, minimum=1, maximum=100),
        max_jobs=_safe_int(request.form.get("max_jobs"), 50, minimum=1, maximum=500),
        top=_safe_int(request.form.get("top"), 25, minimum=1, maximum=100),
        location_matches=_safe_int(request.form.get("location_matches"), 1, minimum=1, maximum=50),
        hydrate=request.form.get("hydrate") == "on",
        action=request.form.get("action") or "rank",
    )


def lightweight_job_from_summary(client: WorkdayClient, summary: dict[str, Any]) -> JobPosting:
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


def job_matches_browser_filters(
    job: JobPosting,
    *,
    location_queries: list[str],
    title_keywords: list[str],
) -> bool:
    if not title_matches_keywords(job.title, title_keywords):
        return False
    if location_queries and not any(job_matches_location(job, query) for query in location_queries):
        return False
    return True


def discover_filtered_jobs(
    client: WorkdayClient,
    *,
    location_queries: list[str],
    title_keywords: list[str],
    applied_facets: dict[str, list[str]],
    max_pages: int,
    page_size: int,
    max_jobs: int,
    hydrate: bool,
) -> tuple[list[JobPosting], int]:
    """Scan cheap list summaries first, then hydrate only browser-filtered jobs.

    Workday's own searchText searches broadly across postings. This browser layer lets
    title keywords mean exactly title keywords and avoids hydrating irrelevant postings.
    """
    matched_summaries: list[dict[str, Any]] = []
    scanned = 0

    for summary in client.iter_summaries(
        max_pages=max_pages,
        limit=page_size,
        applied_facets=applied_facets,
    ):
        scanned += 1
        lightweight_job = lightweight_job_from_summary(client, summary)
        if job_matches_browser_filters(
            lightweight_job,
            location_queries=location_queries,
            title_keywords=title_keywords,
        ):
            matched_summaries.append(summary)
            if len(matched_summaries) >= max_jobs:
                break

    if hydrate:
        return [client.hydrate_posting(summary) for summary in matched_summaries], scanned
    return [lightweight_job_from_summary(client, summary) for summary in matched_summaries], scanned


def run_search(form: SearchForm) -> dict[str, Any]:
    parsed_config = WorkdaySiteConfig.from_public_url(form.url)
    config = WorkdaySiteConfig(
        base_url=parsed_config.base_url,
        tenant=parsed_config.tenant,
        site=parsed_config.site,
        locale=parsed_config.locale,
        public_path_prefix=parsed_config.public_path_prefix,
        default_facets=parsed_config.default_facets,
        default_search_text=form.query,
        page_size=form.page_size,
    )
    client = WorkdayClient(config)
    runtime_facets = dict(config.default_facets)
    location_queries = parse_location_queries(form.location)
    title_keywords = parse_title_keywords(form.title_keywords)
    active_profile = profile_from_form(form)

    location_matches: dict[str, list[FacetOption]] = {}
    for query in location_queries:
        matches = client.search_location_options(
            query,
            applied_facets=runtime_facets,
            limit=form.location_matches,
        )
        location_matches[query] = matches
        runtime_facets = merge_facets(runtime_facets, *(match.as_facet_dict() for match in matches))

    if form.action == "locations":
        return {
            "config": config,
            "runtime_facets": runtime_facets,
            "location_matches": location_matches,
            "ranked": [],
            "raw_job_count": 0,
            "filtered_job_count": 0,
            "browser_filter_applied": False,
            "title_keywords": title_keywords,
            "active_profile": active_profile,
            "profile_label": PROFILE_LABELS.get(form.profile_key, form.profile_key),
        }

    browser_filters_active = bool(location_queries or title_keywords)
    if browser_filters_active:
        filtered_jobs, scanned_count = discover_filtered_jobs(
            client,
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
        filtered_jobs = client.discover_jobs(
            max_pages=form.pages,
            limit=form.page_size,
            max_jobs=form.max_jobs,
            hydrate=form.hydrate,
            applied_facets=runtime_facets,
        )
        raw_job_count = len(filtered_jobs)

    ranked = KeywordRanker(active_profile).rank(filtered_jobs)[: form.top]
    return {
        "config": config,
        "runtime_facets": runtime_facets,
        "location_matches": location_matches,
        "ranked": ranked,
        "raw_job_count": raw_job_count,
        "filtered_job_count": len(filtered_jobs),
        "browser_filter_applied": browser_filters_active,
        "title_keywords": title_keywords,
        "active_profile": active_profile,
        "profile_label": PROFILE_LABELS.get(form.profile_key, form.profile_key),
    }


PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Grepper Workday Ranker</title>
  <style>
    :root {
      --bg: #081018;
      --panel: #0f1720;
      --panel-soft: #131e2a;
      --text: #f3f4f6;
      --muted: #a8b3bf;
      --accent: #ff8a3d;
      --teal: #2d8f8b;
      --border: #233142;
      --bad: #ff6b6b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top left, #112235 0, var(--bg) 42%);
      color: var(--text);
    }
    a { color: #ffb37f; }
    .page { max-width: 1180px; margin: 0 auto; padding: 32px 18px 60px; }
    .hero { margin-bottom: 24px; }
    .hero h1 { margin: 0 0 8px; font-size: clamp(2rem, 4vw, 3.25rem); letter-spacing: -0.05em; }
    .hero p { margin: 0; color: var(--muted); max-width: 760px; line-height: 1.55; }
    .layout { display: grid; grid-template-columns: minmax(300px, 410px) 1fr; gap: 20px; align-items: start; }
    @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
    .card, .form-card {
      background: rgba(15, 23, 32, 0.92);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 18px 50px rgba(0,0,0,.25);
    }
    .form-card { padding: 18px; position: sticky; top: 18px; }
    label { display: block; font-weight: 700; margin: 14px 0 6px; color: #dbe3ec; }
    .hint { color: var(--muted); font-size: .88rem; line-height: 1.4; margin-top: 5px; }
    input[type="text"], input[type="number"], textarea, select {
      width: 100%;
      border: 1px solid #314358;
      background: #09131e;
      color: var(--text);
      border-radius: 12px;
      padding: 11px 12px;
      font: inherit;
      outline: none;
    }
    textarea { min-height: 72px; resize: vertical; }
    .weight-box { min-height: 130px; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: .88rem; }
    .profile-panel { margin-top: 10px; background: #0a1420; border: 1px solid #26384d; border-radius: 14px; padding: 12px; }
    .profile-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
    @media (max-width: 560px) { .profile-grid { grid-template-columns: 1fr; } }
    input:focus, textarea:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(255, 138, 61, .12); }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .check { display: flex; align-items: center; gap: 8px; margin-top: 14px; color: var(--muted); }
    .actions { display: flex; gap: 10px; margin-top: 18px; flex-wrap: wrap; }
    button {
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      font-weight: 800;
      cursor: pointer;
      color: #101010;
      background: linear-gradient(135deg, var(--accent), #ffad72);
    }
    button.secondary { background: #203044; color: var(--text); border: 1px solid #3a4e66; }
    .examples { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    .example-pill { border: 1px solid #33475f; color: var(--muted); background: #0b1420; border-radius: 999px; padding: 6px 9px; font-size: .82rem; cursor: pointer; }
    .summary { padding: 16px; margin-bottom: 16px; }
    .summary code { color: #ffc18f; }
    .error { border-color: rgba(255,107,107,.5); color: #ffd3d3; padding: 16px; margin-bottom: 16px; }
    .warning { border-color: rgba(255, 138, 61, .55); color: #ffd8bd; padding: 14px; margin-top: 12px; background: rgba(255, 138, 61, .08); }
    .results { display: grid; gap: 14px; }
    .job { padding: 16px; }
    .job-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    .job h2 { font-size: 1.1rem; margin: 0 0 8px; letter-spacing: -0.02em; }
    .score { flex: 0 0 auto; background: rgba(45, 143, 139, .16); border: 1px solid rgba(45, 143, 139, .5); color: #a7ffec; border-radius: 999px; padding: 5px 9px; font-weight: 800; }
    .meta { color: var(--muted); font-size: .92rem; display: flex; flex-wrap: wrap; gap: 8px 14px; margin-bottom: 10px; }
    .matches { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    .tag { background: #172537; border: 1px solid #2c4058; color: #dce8f5; border-radius: 999px; padding: 4px 8px; font-size: .8rem; }
    .tag.neg { color: #ffd0d0; border-color: rgba(255,107,107,.35); }
    details { margin-top: 10px; color: var(--muted); }
    summary { cursor: pointer; color: #dbe3ec; font-weight: 700; }
    .description { white-space: pre-wrap; line-height: 1.45; max-height: 260px; overflow: auto; background: #09131e; padding: 12px; border-radius: 12px; border: 1px solid #26384d; margin-top: 8px; }
    .empty { padding: 24px; color: var(--muted); text-align: center; }
    .facet-list { margin: 10px 0 0; padding: 0; list-style: none; display: grid; gap: 7px; }
    .facet-list li { background: #0a1420; border: 1px solid #25384d; border-radius: 12px; padding: 9px; color: var(--muted); }
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>Grepper Workday Ranker</h1>
      <p>Search a Workday-powered careers site, resolve tenant-specific location facets, filter title keywords, and rank jobs against a selected, tunable Profile.</p>
    </section>

    <div class="layout">
      <form class="form-card" method="post">
        <label for="url">Workday careers URL</label>
        <input id="url" name="url" type="text" value="{{ form.url }}" placeholder="https://company.wd5.myworkdayjobs.com/..." required>
        <div class="examples">
          {% for label, url in examples.items() %}
            <button class="example-pill" type="button" onclick="document.getElementById('url').value='{{ url }}'">{{ label }}</button>
          {% endfor %}
        </div>

        <label for="location">Location search</label>
        <textarea id="location" name="location" placeholder="US, Boston, Massachusetts">{{ form.location }}</textarea>
        <div class="hint">Comma or newline separated. The app resolves these to the site's actual Workday location facet IDs.</div>

        <label for="title_keywords">Title keywords</label>
        <input id="title_keywords" name="title_keywords" type="text" value="{{ form.title_keywords }}" placeholder="optional: solutions, SDET, quality, site reliability">
        <div class="hint">Browser-side filter. Comma separated terms match against the role title only.</div>

        <label for="query">Keyword searchText sent to Workday</label>
        <input id="query" name="query" type="text" value="{{ form.query }}" placeholder="optional: Kubernetes, storage, automation...">
        <div class="hint">This is Workday's broader searchText and may search title, description, team, and other fields.</div>

        <label for="profile_key">Profile preset</label>
        <select id="profile_key" name="profile_key">
          {% for key, preset in profile_presets.items() %}
            <option value="{{ key }}" {% if form.profile_key == key %}selected{% endif %}>{{ preset.label }}</option>
          {% endfor %}
        </select>
        <div class="hint">Choose a preset, then tune the weighted keywords below before ranking.</div>

        <div class="profile-panel">
          <label for="core_plus_weights">Core weighted keywords</label>
          <textarea class="weight-box" id="core_plus_weights" name="core_plus_weights" spellcheck="false">{{ form.core_plus_weights }}</textarea>

          <label for="nice_weights">Nice-to-have weighted keywords</label>
          <textarea class="weight-box" id="nice_weights" name="nice_weights" spellcheck="false">{{ form.nice_weights }}</textarea>

          <label for="light_neg_weights">Light negative weighted keywords</label>
          <textarea class="weight-box" id="light_neg_weights" name="light_neg_weights" spellcheck="false">{{ form.light_neg_weights }}</textarea>

          <div class="profile-grid">
            <div>
              <label for="title_boost">Title boost</label>
              <input id="title_boost" name="title_boost" type="number" value="{{ form.title_boost }}" min="0" max="10" step="0.05">
            </div>
            <div>
              <label for="length_bonus_cap">Length bonus cap</label>
              <input id="length_bonus_cap" name="length_bonus_cap" type="number" value="{{ form.length_bonus_cap }}" min="0" max="10" step="0.05">
            </div>
            <div>
              <label for="length_bonus_divisor">Length divisor</label>
              <input id="length_bonus_divisor" name="length_bonus_divisor" type="number" value="{{ form.length_bonus_divisor }}" min="1" max="100000" step="1">
            </div>
          </div>
          <div class="hint">Use one <code>term = weight</code> per line. Positive values lift jobs; negative values push jobs down.</div>
        </div>

        <div class="row">
          <div>
            <label for="pages">Pages to scan</label>
            <input id="pages" name="pages" type="number" value="{{ form.pages }}" min="1" max="100">
          </div>
          <div>
            <label for="page_size">Page size</label>
            <input id="page_size" name="page_size" type="number" value="{{ form.page_size }}" min="1" max="100">
          </div>
        </div>

        <div class="row">
          <div>
            <label for="max_jobs">Max matching jobs</label>
            <input id="max_jobs" name="max_jobs" type="number" value="{{ form.max_jobs }}" min="1" max="500">
          </div>
          <div>
            <label for="top">Top results</label>
            <input id="top" name="top" type="number" value="{{ form.top }}" min="1" max="100">
          </div>
        </div>

        <label for="location_matches">Location matches per query</label>
        <input id="location_matches" name="location_matches" type="number" value="{{ form.location_matches }}" min="1" max="50">

        <label class="check">
          <input name="hydrate" type="checkbox" {% if form.hydrate %}checked{% endif %}>
          Hydrate matching job detail pages for better description-based ranking
        </label>

        <div class="actions">
          <button type="submit" name="action" value="rank">Rank jobs</button>
          <button class="secondary" type="submit" name="action" value="locations">Preview locations</button>
        </div>
      </form>

      <section>
        {% if error %}
          <div class="card error"><strong>Something failed:</strong><br>{{ error }}</div>
        {% endif %}

        {% if result %}
          <div class="card summary">
            <strong>Resolved site:</strong>
            <code>{{ result.config.tenant }}/{{ result.config.site }}</code><br>
            <strong>Profile:</strong>
            <code>{{ result.profile_label }}</code>
            <code>{{ result.active_profile.name }}</code><br>
            <strong>Applied facets:</strong>
            <code>{{ result.runtime_facets }}</code>
            {% if result.title_keywords %}
              <br><strong>Title keywords:</strong>
              <code>{{ result.title_keywords }}</code>
            {% endif %}
            {% if result.browser_filter_applied %}
              <br><strong>Browser-side scan:</strong>
              kept <code>{{ result.filtered_job_count }}</code> matching jobs from <code>{{ result.raw_job_count }}</code> scanned summaries
            {% endif %}

            {% if result.browser_filter_applied and result.raw_job_count > 0 and result.filtered_job_count == 0 %}
              <div class="warning">
                Workday returned/scanned jobs, but none matched the requested browser-side filters. Try increasing Pages to scan, removing Workday searchText, or broadening the title/location filters.
              </div>
            {% endif %}

            {% if result.location_matches %}
              <h3>Location matches</h3>
              {% for query, matches in result.location_matches.items() %}
                <strong>{{ query }}</strong>
                {% if matches %}
                  <ul class="facet-list">
                    {% for match in matches %}
                      <li><code>{{ match.facet_key }}={{ match.value }}</code><br>{{ match.label }} · score {{ match.score }}{% if match.count is not none %} · {{ match.count }} jobs{% endif %}</li>
                    {% endfor %}
                  </ul>
                {% else %}
                  <p class="hint">No matches found.</p>
                {% endif %}
              {% endfor %}
            {% endif %}
          </div>

          {% if result.ranked %}
            <div class="results">
              {% for item in result.ranked %}
                {% set job = item.job %}
                <article class="card job">
                  <div class="job-top">
                    <div>
                      <h2><a href="{{ job.url }}" target="_blank" rel="noreferrer">{{ job.title }}</a></h2>
                      <div class="meta">
                        <span>{{ job.location or "Unknown location" }}</span>
                        <span>{{ job.posted or job.date_posted or "Unknown posted date" }}</span>
                        {% if job.req_id %}<span>Req {{ job.req_id }}</span>{% endif %}
                      </div>
                    </div>
                    <div class="score">{{ item.score }}</div>
                  </div>

                  <div class="matches">
                    {% for hit in item.matches.core[:10] %}<span class="tag">{{ hit }}</span>{% endfor %}
                    {% for hit in item.matches.nice[:5] %}<span class="tag">{{ hit }}</span>{% endfor %}
                    {% for hit in item.matches.neg[:5] %}<span class="tag neg">{{ hit }}</span>{% endfor %}
                  </div>

                  {% if job.description_text %}
                    <details>
                      <summary>Description preview</summary>
                      <div class="description">{{ job.description_text[:1800] }}</div>
                    </details>
                  {% endif %}
                </article>
              {% endfor %}
            </div>
          {% elif form.action == "rank" and not error %}
            <div class="card empty">No jobs returned for this search.</div>
          {% endif %}
        {% else %}
          <div class="card empty">Enter a Workday URL and click <strong>Rank jobs</strong> or <strong>Preview locations</strong>.</div>
        {% endif %}
      </section>
    </div>
  </main>

  <script>
    const PROFILE_PRESETS = {{ profile_presets | tojson }};
    const profileSelect = document.getElementById("profile_key");

    function setField(id, value) {
      const el = document.getElementById(id);
      if (el) el.value = value;
    }

    function applySelectedProfilePreset() {
      const preset = PROFILE_PRESETS[profileSelect.value];
      if (!preset) return;
      setField("core_plus_weights", preset.core_plus_weights);
      setField("nice_weights", preset.nice_weights);
      setField("light_neg_weights", preset.light_neg_weights);
      setField("title_boost", preset.title_boost);
      setField("length_bonus_cap", preset.length_bonus_cap);
      setField("length_bonus_divisor", preset.length_bonus_divisor);
    }

    if (profileSelect) {
      profileSelect.addEventListener("change", applySelectedProfilePreset);
    }
  </script>
</body>
</html>
"""


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def index():
        form = form_from_request()
        result: dict[str, Any] | None = None
        error = ""
        if request.method == "POST":
            try:
                result = run_search(form)
            except Exception as exc:  # pragma: no cover - browser-facing safety net
                error = str(exc)
        return render_template_string(
            PAGE_TEMPLATE,
            form=form,
            result=result,
            error=error,
            examples=DEFAULT_EXAMPLES,
            profile_presets=profile_presets_for_template(),
        )

    return app


def main() -> int:
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
