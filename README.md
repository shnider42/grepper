# Grepper Jobs Modular

A cleaned-up modular version of the job scraper/ranker experiments. It started with Workday, and now has a first iCIMS provider path as well.

## What changed from the chicken scratch version

The old scripts had the right instincts, but too many things lived in one file:

- provider/site config
- list-page or search-page fetching
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
  config.py      # WorkdaySiteConfig and Workday URL/facet inference
  client.py      # Workday CXS list API + public JSON-LD hydration
  icims.py       # iCIMS URL parsing, search-page link discovery, and JSON-LD hydration
  sources.py     # provider detection/factory helpers
  models.py      # JobPosting and RankedJob dataclasses
  parsing.py     # req_id/location/posted/JSON-LD/description cleanup
  facets.py      # Workday tenant-specific facet discovery/search, especially locations
  ranker.py      # keyword scoring profile
  exporters.py   # CSV/JSON output
  cli.py         # command-line wrapper
  web.py         # local Flask browser UI
examples/
  run_cisco.py
  run_draper.py
  run_fidelity.py
  run_netflix.py
  run_nvidia.py
  run_suffolk_icims.py
tests/
  test_config.py
  test_facets.py
  test_icims.py
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

### Local development in PyCharm

When running locally, this project is usually run through JetBrains PyCharm 2025. Once PyCharm is pointed at the project interpreter / virtual environment, you should not need to manually run the environment activation command every time. The shell activation steps above are mainly for a fresh terminal, first-time setup, or running outside PyCharm.

## Run the browser UI

After installing, start the local web app:

```bash
grepper-jobs-web
```

The old command name still works too:

```bash
workday-jobs-web
```

Then open this in your browser:

```text
http://127.0.0.1:5000
```

The browser UI lets you paste a supported careers URL, search/filter locations, and rank jobs without typing the full CLI command. Workday location filters use Workday facets. iCIMS location filtering is a post-filter against hydrated job details.

## Run from a public Workday URL

This is the easiest CLI path. Facets in the URL query string are reused automatically.

```bash
grepper-jobs \
  --url "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?locationHierarchy1=2fcb99c455831013ea52fb338f2932d8&jobFamilyGroup=0c40f6bd1d8f10ae43ffaefd46dc7e78&jobFamilyGroup=0c40f6bd1d8f10ae43ffbd1459047e84" \
  --pages 5 \
  --max-jobs 75 \
  --csv nvidia_ranked.csv
```

The parser also supports newer shared-host Workday URLs such as Fidelity's:

```bash
grepper-jobs \
  --url "https://wd1.myworkdaysite.com/en-US/recruiting/fmr/FidelityCareers" \
  --pages 5 \
  --max-jobs 75 \
  --csv fidelity_ranked.csv
```

It also supports known branded careers skins such as Netflix's `explore.jobs.netflix.net` careers page. Netflix is parsed from the public URL like a named source, then the client uses Netflix's branded jobs API for listing, pagination, and detail hydration:

```bash
grepper-jobs \
  --url "https://explore.jobs.netflix.net/careers" \
  --pages 5 \
  --max-jobs 75 \
  --csv netflix_ranked.csv
```

## Run from an iCIMS URL

For direct iCIMS job URLs, Grepper parses the host and job id, then hydrates the posting from the public job page JSON-LD when available:

```bash
grepper-jobs \
  --url "https://careers-suffolkconstruction.icims.com/jobs/11113/job" \
  --max-jobs 1
```

For iCIMS search pages, Grepper scans public HTML for `/jobs/{id}/job` links, dedupes them, then hydrates those job detail pages:

```bash
grepper-jobs \
  --url "https://careers-suffolkconstruction.icims.com/jobs/search" \
  --pages 3 \
  --max-jobs 50
```

Important iCIMS caveat: this starts from public HTML and schema.org/JSON-LD because iCIMS does not use Workday's CXS API. It is intentionally more conservative than the Workday path.

## Location search instead of hardcoded location IDs

Different Workday tenants expose location facets differently. NVIDIA may have a country-level `locationHierarchy1` value for the United States, while Cisco may expose many city-level `locations` values whose labels contain `(US)` or `US`.

Use `--location` to resolve human text into whatever facet values that tenant exposes:

```bash
grepper-jobs \
  --url "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite" \
  --location US \
  --list-locations
```

Then run the actual scrape/rank with the resolved location applied:

```bash
grepper-jobs \
  --url "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers" \
  --location "Boston" \
  --location-matches 3 \
  --pages 5 \
  --max-jobs 75
```

`--location-matches` matters because some Workday tenants only have city-level values. For iCIMS, `--location` is applied as a post-filter against hydrated job detail data instead of provider facets.

## Run from explicit Workday config

```bash
grepper-jobs \
  --base-url "https://draper.wd5.myworkdayjobs.com" \
  --tenant draper \
  --site Draper_Careers \
  --facet locations=137100679bc6100117f740f986e00000 \
  --facet jobFamilyGroup=b9bd15164d241000c3f13e0445530002 \
  --pages 6 \
  --max-jobs 120
```

## Why this should generalize better

### 1. Provider details are config and adapters, not one giant script

Cisco, NVIDIA, Draper, Fidelity, Netflix, Red Hat, Suffolk/iCIMS, etc. can become different configs/provider paths while still returning the same `JobPosting` model for ranking and export.

### 2. Repeated Workday facet query params are parsed correctly

A Workday URL may contain repeated values like:

```text
jobFamilyGroup=A&jobFamilyGroup=B&jobFamilyGroup=C
```

Those become:

```python
{"jobFamilyGroup": ["A", "B", "C"]}
```

Do **not** collapse those into one string containing `&jobFamilyGroup=`.

### 3. Newer shared-host, branded careers URLs, and non-Workday providers are parsed separately

Some employers use Workday URLs like:

```text
https://wd1.myworkdaysite.com/en-US/recruiting/fmr/FidelityCareers
```

Those need to map to the CXS API as tenant `fmr` and site `FidelityCareers`, not tenant `wd1` and site `recruiting`.

Other employers use a branded skin in front of a jobs API, such as:

```text
https://explore.jobs.netflix.net/careers
```

Those need a known mapping because the backend source is not visible from the public URL alone.

Non-Workday providers, such as iCIMS, should not be shoehorned into Workday config. They get their own adapter and feed the same normalized output model.

### 4. Description cleanup has a safe fallback

The old version sometimes returned `None` when the employer did not use the exact expected heading. This version tries known headings, trims known boilerplate, but otherwise falls back to the full cleaned schema.org JobPosting description.

### 5. Ranking is replaceable

`KeywordRanker` is intentionally simple, but the default profile is tuned toward Chris-style roles: quality engineering, test automation, Linux/Python, SRE/DevOps, Kubernetes/OpenShift, enterprise storage, network OS/networking, customer-facing solutions work, and technical leadership. Later, it can be replaced or complemented by embeddings/LLM scoring without touching provider scraping layers.

## Suggested next step

Add one tiny `sites.yaml` or `sites.json` file so you can store named configs like `cisco`, `nvidia`, `draper`, `fidelity`, `netflix`, `redhat`, `suffolk_icims`, etc., then call:

```bash
grepper-jobs --site-config cisco --pages 5
```

That would make this feel like an actual product instead of a script collection.
