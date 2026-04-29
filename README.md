# Grepper Workday Modular

A cleaned-up modular version of the Workday job scraper/ranker experiments.

## What changed from the chicken scratch version

The old scripts had the right instincts, but too many things lived in one file:

- Workday tenant/site config
- list-page API calls
- public job URL construction
- JSON-LD job detail scraping
- employer-specific description cleanup
- ranking logic
- printing/exporting

This project separates those concerns.

## Structure

```text
workday_jobs/
  config.py      # WorkdaySiteConfig and URL/facet inference
  client.py      # Workday CXS list API + public JSON-LD hydration
  models.py      # JobPosting and RankedJob dataclasses
  parsing.py     # req_id/location/posted/JSON-LD/description cleanup
  ranker.py      # keyword scoring profile
  exporters.py   # CSV/JSON output
  cli.py         # command-line wrapper
examples/
  run_cisco.py
  run_draper.py
  run_nvidia.py
tests/
  test_config.py
  test_parsing.py
```

## Install

From the project folder:

```bash
python -m venv .venv
. .venv/Scripts/activate   # Windows PowerShell/Git Bash may differ
pip install -e .
```

## Run from a public Workday URL

This is the easiest path. Facets in the URL query string are reused automatically.

```bash
workday-jobs \
  --url "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?locationHierarchy1=2fcb99c455831013ea52fb338f2932d8&jobFamilyGroup=0c40f6bd1d8f10ae43ffaefd46dc7e78&jobFamilyGroup=0c40f6bd1d8f10ae43ffbd1459047e84" \
  --pages 5 \
  --max-jobs 75 \
  --csv nvidia_ranked.csv
```

## Run from explicit config

```bash
workday-jobs \
  --base-url "https://draper.wd5.myworkdayjobs.com" \
  --tenant draper \
  --site Draper_Careers \
  --facet locations=137100679bc6100117f740f986e00000 \
  --facet jobFamilyGroup=b9bd15164d241000c3f13e0445530002 \
  --pages 6 \
  --max-jobs 120
```

## Why this should generalize better

### 1. Site details are config, not code

Cisco, NVIDIA, Draper, Red Hat, etc. should become different `WorkdaySiteConfig` values rather than different Python scripts.

### 2. Repeated facet query params are parsed correctly

A Workday URL may contain repeated values like:

```text
jobFamilyGroup=A&jobFamilyGroup=B&jobFamilyGroup=C
```

Those become:

```python
{"jobFamilyGroup": ["A", "B", "C"]}
```

Do **not** collapse those into one string containing `&jobFamilyGroup=`.

### 3. Description cleanup has a safe fallback

The old version sometimes returned `None` when the employer did not use the exact expected heading. This version tries known headings, trims known boilerplate, but otherwise falls back to the full cleaned schema.org JobPosting description.

### 4. Ranking is replaceable

`KeywordRanker` is intentionally simple. Later, it can be replaced or complemented by embeddings/LLM scoring without touching the Workday scraping layer.

## Suggested next step

Add one tiny `sites.yaml` or `sites.json` file so you can store named configs like `cisco`, `nvidia`, `draper`, `redhat`, etc., then call:

```bash
workday-jobs --site-config cisco --pages 5
```

That would make this feel like an actual product instead of a script collection.
