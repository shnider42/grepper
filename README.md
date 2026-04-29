# Grepper Workday Modular

A cleaned-up modular version of the Workday job scraper/ranker experiments.

## What changed from the chicken scratch version

The old scripts had the right instincts, but too many things lived in one file:

- Workday tenant/site config
- list-page API calls
- public job URL construction
- JSON-LD job detail scraping
- employer-specific description cleanup
- location/facet lookup
- ranking logic
- printing/exporting
- browser UI

This project separates those concerns.

## Structure

```text
workday_jobs/
  config.py      # WorkdaySiteConfig and URL/facet inference
  client.py      # Workday CXS list API + public JSON-LD hydration
  models.py      # JobPosting and RankedJob dataclasses
  parsing.py     # req_id/location/posted/JSON-LD/description cleanup
  facets.py      # tenant-specific facet discovery/search, especially locations
  ranker.py      # keyword scoring profile
  exporters.py   # CSV/JSON output
  cli.py         # command-line wrapper
  web.py         # local Flask browser UI
examples/
  run_cisco.py
  run_draper.py
  run_nvidia.py
tests/
  test_config.py
  test_facets.py
  test_parsing.py
  test_ranker.py
```

## Install

From the project folder:

```bash
python -m venv .venv
. .venv/Scripts/activate   # Windows PowerShell/Git Bash may differ
pip install -e .
```

On Windows PowerShell, activation is usually:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Run the browser UI

After installing, start the local web app:

```bash
workday-jobs-web
```

Then open this in your browser:

```text
http://127.0.0.1:5000
```

The browser UI lets you paste a Workday careers URL, search for locations like `US`, `Boston`, or `Massachusetts`, preview matched location facets, and rank jobs without typing the full CLI command.

## Run from a public Workday URL

This is the easiest CLI path. Facets in the URL query string are reused automatically.

```bash
workday-jobs \
  --url "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?locationHierarchy1=2fcb99c455831013ea52fb338f2932d8&jobFamilyGroup=0c40f6bd1d8f10ae43ffaefd46dc7e78&jobFamilyGroup=0c40f6bd1d8f10ae43ffbd1459047e84" \
  --pages 5 \
  --max-jobs 75 \
  --csv nvidia_ranked.csv
```

## Location search instead of hardcoded location IDs

Different Workday tenants expose location facets differently. NVIDIA may have a country-level `locationHierarchy1` value for the United States, while Cisco may expose many city-level `locations` values whose labels contain `(US)` or `US`.

Use `--location` to resolve human text into whatever facet values that tenant exposes:

```bash
workday-jobs \
  --url "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite" \
  --location US \
  --list-locations
```

Then run the actual scrape/rank with the resolved location applied:

```bash
workday-jobs \
  --url "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers" \
  --location "Boston" \
  --location-matches 3 \
  --pages 5 \
  --max-jobs 75
```

`--location-matches` matters because some tenants only have city-level values. For a broad query like `US`, a tenant with no country-level option may return many city values; for a focused query like `Boston`, one match is usually enough.

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

### 3. Location is now a search problem, not a hardcoded variable

Use `--location US`, `--location Boston`, or `--location Massachusetts` and let the tenant-specific facet resolver find the correct Workday facet key/value pair.

### 4. Description cleanup has a safe fallback

The old version sometimes returned `None` when the employer did not use the exact expected heading. This version tries known headings, trims known boilerplate, but otherwise falls back to the full cleaned schema.org JobPosting description.

### 5. Ranking is replaceable

`KeywordRanker` is intentionally simple, but the default profile is now tuned toward Chris-style roles: quality engineering, test automation, Linux/Python, SRE/DevOps, Kubernetes/OpenShift, enterprise storage, network OS/networking, customer-facing solutions work, and technical leadership. Later, it can be replaced or complemented by embeddings/LLM scoring without touching the Workday scraping layer.

## Suggested next step

Add one tiny `sites.yaml` or `sites.json` file so you can store named configs like `cisco`, `nvidia`, `draper`, `redhat`, etc., then call:

```bash
workday-jobs --site-config cisco --pages 5
```

That would make this feel like an actual product instead of a script collection.
