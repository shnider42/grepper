from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import Flask, render_template_string, request

from .client import WorkdayClient
from .config import WorkdaySiteConfig
from .facets import FacetOption, merge_facets
from .models import RankedJob
from .ranker import KeywordRanker


DEFAULT_EXAMPLES = {
    "Cisco": "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers",
    "NVIDIA": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
    "Draper": "https://draper.wd5.myworkdayjobs.com/en-US/Draper_Careers",
}


@dataclass
class SearchForm:
    url: str = DEFAULT_EXAMPLES["Cisco"]
    location: str = ""
    query: str = ""
    pages: int = 3
    page_size: int = 20
    max_jobs: int = 50
    top: int = 25
    location_matches: int = 1
    hydrate: bool = True
    action: str = "rank"


def parse_location_queries(raw: str) -> list[str]:
    """Accept comma/newline separated location searches from the browser form."""
    queries: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        value = chunk.strip()
        if value:
            queries.append(value)
    return queries


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
        pages=_safe_int(request.form.get("pages"), 3, minimum=1, maximum=25),
        page_size=_safe_int(request.form.get("page_size"), 20, minimum=1, maximum=100),
        max_jobs=_safe_int(request.form.get("max_jobs"), 50, minimum=1, maximum=500),
        top=_safe_int(request.form.get("top"), 25, minimum=1, maximum=100),
        location_matches=_safe_int(request.form.get("location_matches"), 1, minimum=1, maximum=50),
        hydrate=request.form.get("hydrate") == "on",
        action=request.form.get("action") or "rank",
    )


def run_search(form: SearchForm) -> dict[str, Any]:
    config = WorkdaySiteConfig.from_public_url(form.url)
    config = WorkdaySiteConfig(
        base_url=config.base_url,
        tenant=config.tenant,
        site=config.site,
        locale=config.locale,
        default_facets=config.default_facets,
        default_search_text=form.query,
        page_size=form.page_size,
    )
    client = WorkdayClient(config)
    runtime_facets = dict(config.default_facets)

    location_matches: dict[str, list[FacetOption]] = {}
    for query in parse_location_queries(form.location):
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
        }

    jobs = client.discover_jobs(
        max_pages=form.pages,
        limit=form.page_size,
        max_jobs=form.max_jobs,
        hydrate=form.hydrate,
        applied_facets=runtime_facets,
    )
    ranked = KeywordRanker().rank(jobs)[: form.top]
    return {
        "config": config,
        "runtime_facets": runtime_facets,
        "location_matches": location_matches,
        "ranked": ranked,
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
    input:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(255, 138, 61, .12); }
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
      <p>Search a Workday-powered careers site, resolve messy tenant-specific location facets, and rank jobs against the current Chris-tuned profile.</p>
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

        <label for="query">Keyword searchText sent to Workday</label>
        <input id="query" name="query" type="text" value="{{ form.query }}" placeholder="optional: SDET, Kubernetes, storage...">

        <div class="row">
          <div>
            <label for="pages">Pages</label>
            <input id="pages" name="pages" type="number" value="{{ form.pages }}" min="1" max="25">
          </div>
          <div>
            <label for="page_size">Page size</label>
            <input id="page_size" name="page_size" type="number" value="{{ form.page_size }}" min="1" max="100">
          </div>
        </div>

        <div class="row">
          <div>
            <label for="max_jobs">Max jobs</label>
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
          Hydrate job detail pages for better description-based ranking
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
            <strong>Applied facets:</strong>
            <code>{{ result.runtime_facets }}</code>

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
        )

    return app


def main() -> int:
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
