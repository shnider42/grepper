'https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers/details/Solutions-Engineer_2012720?jobFamilyGroup=2101eee3ea96016aef42a674fc016429&jobFamilyGroup=2101eee3ea9601cf53eba574fc016229&jobFamilyGroup=2101eee3ea96017b1ceba674fc016829'

import re, json, requests, html, time, argparse
from urllib.parse import urljoin
from typing import List, Tuple, Any, Dict

BASE = "https://cisco.wd5.myworkdayjobs.com"
SITE = "Cisco_Careers"

# Search (list) endpoint the SPA calls:
LIST_URL = f"{BASE}/wday/cxs/cisco/{SITE}/jobs"

# Per-job JSON endpoint:
DETAIL_JSON_URL = f"{BASE}/wday/cxs/cisco/{SITE}/job"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal-research)",
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE,
    "Referer": f"{BASE}/en-US/{SITE}",
}

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

def post_jobs(limit=20, offset=0, payload_style=0, applied_facets=None):
    """
    payload_style:
      0 -> include appliedFacets (default empty dict if None)
      1 -> omit appliedFacets entirely (fallback if 400s)
    """
    payload = {
        "limit": limit,
        "offset": offset,
        "searchText": ""
    }
    if payload_style == 0:
        payload["appliedFacets"] = applied_facets or {}

    r = requests.post(LIST_URL, headers=HEADERS, json=payload, timeout=30)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        # quick retry without appliedFacets if tenant is picky
        if r.status_code == 400 and payload_style == 0:
            return post_jobs(limit=limit, offset=offset, payload_style=1, applied_facets=applied_facets)
        raise
    return r.json()

# --- NEW: tiny helper to fetch a numbered page (1-based) ---
def fetch_page(page=1, limit=20, applied_facets=None):
    """
    Page is 1-based: page=1 -> offset=0, page=2 -> offset=limit, etc.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    offset = (page - 1) * limit
    return post_jobs(limit=limit, offset=offset, applied_facets=applied_facets)

# Example usage:
# data = fetch_page(page=1, limit=20, applied_facets={
#     "locations": ["137100679bc6100117f740f986e00000"],
#     "jobFamilyGroup": ["b9bd15164d241000c3f13e0445530002"]
# })
# for j in data.get("jobPostings", []):
#     print(j.get("title"), BASE + j.get("externalPath", ""))


def first_ok_page(limit=20, offset=0):
    try:
        return post_jobs(limit, offset, payload_style=0)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 400:
            # Some tenants reject empty appliedFacets, retry without it
            return post_jobs(limit, offset, payload_style=1)
        raise

def parse_req_id_from_path(path: str) -> str:
    # e.g. "/en-US/Draper_Careers/job/Cambridge-MA/GNC-Systems-Engineer_JR001767"
    m = re.search(r"_([A-Za-z]*\d+)$", path)
    return m.group(1) if m else ""

def compact_location(posting: dict) -> str:
    # Workday often provides a "locationsText" field in subtitles or a list under locations
    # Try a few common spots:
    # - posting["locationsText"]
    # - one of "subtitles" entries with "label" == "locations"
    # - joining the "locations" array of dicts' "descriptor" fields
    loc = posting.get("locationsText")
    if loc: return loc
    for sub in posting.get("subtitles", []):
        if (sub.get("label") or "").lower().startswith("location"):
            # subtitle values are often strings already
            val = sub.get("value")
            if val: return val
    locs = posting.get("locations") or []
    names = [l.get("descriptor") for l in locs if isinstance(l, dict) and l.get("descriptor")]
    return ", ".join(names)

def compact_posted_on(posting: dict) -> str:
    # Often appears in subtitles as "Posted X days ago" or a date
    for sub in posting.get("subtitles", []):
        label = (sub.get("label") or "").lower()
        if "posted" in label:
            return sub.get("value") or ""
    return posting.get("postedOn") or ""

def discover_jobs(limit=600, offset=0):
    #data = first_ok_page(limit=limit, offset=offset)

    results = []

    for page_num in range(1, 30):
        #data = fetch_page(page=page_num, limit=20, applied_facets={
        #     "locationHierarchy1": ["2fcb99c455831013ea52fb338f2932d8"],
        #     "jobFamilyGroup": ["0c40f6bd1d8f10ae43ffaefd46dc7e78"]
        #     })

        data = fetch_page(page=page_num, limit=20, applied_facets={
            "jobFamilyGroup": ["2101eee3ea96016aef42a674fc016429&jobFamilyGroup=2101eee3ea9601cf53eba574fc016229&jobFamilyGroup=2101eee3ea96017b1ceba674fc016829"]
        })

        '''payload = {
              "appliedFacets": {
                "locationHierarchy1": ["2fcb99c455831013ea52fb338f2932d8"],
                "jobFamilyGroup": [
                  "0c40f6bd1d8f10ae43ffaefd46dc7e78",
                  "0c40f6bd1d8f10ae43ffbd1459047e84"
                ]
              },
              "limit": 50,
              "offset": 0,
              "searchText": ""
            }'''

        for job_items in data.get("jobPostings", []):
             #path = p.get("externalPath")
             path = job_items.get("externalPath", "")

             #print(job_items.get("title"), BASE + job_items.get("externalPath", ""))
             #print(job_items.get("title"), BASE + path)

             #job_items.append()

             middle_path = "/en-US/Cisco_Careers"
             url_prefix = BASE + middle_path
             url = str(url_prefix + path)

             results.append({
                 "req_id": parse_req_id_from_path(path),
                 "title": job_items.get("title") or job_items.get("titleSimple") or "",
                 "location": compact_location(job_items),
                 "posted": compact_posted_on(job_items),
                 "url": url,
                 "job_id": job_items.get("id") or job_items.get("jobId") or job_items.get("uid") or "",  # NEW
             })

        #input("\n\nPAUSE\n\n")
        #print("\n\n" + str(page_num) + "\n\n")

    #input("AFTER FOR LOOP PAUSE")

    '''
    items = data.get("jobPostings") or []
    results = []
    for p in items:
        path = p.get("externalPath") or p.get("externalPathAndQuery")
        if not path:
            continue

        middle_path = "/en-US/Draper_Careers"
        url_prefix = BASE + middle_path
        url = str(url_prefix + path)

        # gathered and appeneded but NOT printed right away, returned instead
        results.append({
            "req_id": parse_req_id_from_path(path),
            "title": p.get("title") or p.get("titleSimple") or "",
            "location": compact_location(p),
            "posted": compact_posted_on(p),
            "url": url,
            "job_id": p.get("id") or p.get("jobId") or p.get("uid") or "",  # NEW
        })
    '''

    return results


# Works now
def fetch_other_fields(PUBLIC_URL):
    html = requests.get(PUBLIC_URL, headers=headers, timeout=30)
    html.raise_for_status()
    text = html.text

    # Extract the JSON-LD (<script type="application/ld+json">…)
    m = re.search(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
                  text, flags=re.S | re.I)
    if not m:
        raise SystemExit("JSON-LD block not found")

    job_ld = json.loads(m.group(1))

    # Useful fields from schema.org/JobPosting
    out = {
        "title": job_ld.get("title"),
        "employmentType": job_ld.get("employmentType"),
        "datePosted": job_ld.get("datePosted"),
        "validThrough": job_ld.get("validThrough"),
        "hiringOrganization": (job_ld.get("hiringOrganization") or {}).get("name"),
        "jobLocation": (job_ld.get("jobLocation") or [{}])
        .get("address", {}).get("addressLocality"),
        "description_html": job_ld.get("description"),  # HTML
        "applyUrl": PUBLIC_URL,
    }

    #print(out["description_html"])

    return out

    #return out["description_html"]

    #print(out)
    #print(json.dumps(out, indent=2))


# Cues that mark the start of boilerplate we don't want in the digest
STOP_CUES = [
    r'\bAdditional Job Description\b',
    r'\bConnect With Draper\b',
    r'\bJob Location\b',
    r'\bThe US base salary range\b',
    r'\bOur work is very important\b',
    r'\bDraper is committed to\b',
    r'\bExplore life at Draper\b',
]

STOP_RE = re.compile('|'.join(STOP_CUES), re.I)

#################### START TEXT PARSING

def split_overviews(big_text: str) -> list[str]:
    """
    Splits the big pasted text into chunks. A new chunk starts at 'Overview: Draper'.
    """
    parts = re.split(r'(?=Overview:\s*Draper\b)', big_text, flags=re.I)
    return [p.strip() for p in parts if p.strip()]

def extract_after_summary(chunk: str) -> str | None:
    """
    Returns the substring starting just after 'Job Description Summary:' and ending
    before common boilerplate sections (salary, EEO paragraph, 'Connect With Draper', etc.).
    """
    m = re.search(r'What you will be doing:\s*', chunk, flags=re.I)
    if not m:
        return None
    tail = chunk[m.end():]
    stop = STOP_RE.search(tail)
    if stop:
        tail = tail[:stop.start()]
    return tail.strip()

def normalize_digest(txt: str | None) -> str | None:
    """
    Cleans up HTML entities, funky bullets, and whitespace.
    """
    if txt is None:
        return None
    # HTML entities -> unicode
    txt = html.unescape(txt)

    # Replace mojibake bullets and normalize dashes
    txt = txt.replace('â¢', '-').replace('•', '-')

    # Tighten up spacing and slashes
    txt = re.sub(r'\s*/\s*', '/', txt)
    txt = re.sub(r'\s+', ' ', txt)

    # Optional: collapse redundant labels like "Job Description:", "Duties/Responsibilities", etc.,
    # into simple markers to reduce noise while keeping content:
    #'''txt = re.sub(r'\b(Job Description:)\s*', '', txt, flags=re.I)
    #txt = re.sub(r'\b(Duties/Responsibilities)\b:?',' Duties & Responsibilities:', txt, flags=re.I)
    #txt = re.sub(r'\b(Skills/Abilities)\b:?',' Skills & Abilities:', txt, flags=re.I)
    #txt = re.sub(r'\b(Education)\b:?',' Education:', txt, flags=re.I)
    #txt = re.sub(r'\b(Experience)\b:?',' Experience:', txt, flags=re.I)'''

    txt = re.sub(r'\b(What you will be doing:)\s*', '', txt, flags=re.I)
    txt = re.sub(r'\b(What we need to see:)\b:?', ' What we need to see:', txt, flags=re.I)
    txt = re.sub(r'\b(Ways to stand out from the crowd:)\b:?', ' Ways to stand out from the crowd:', txt, flags=re.I)

    return txt.strip()

# Works for descriptions
def get_constructed_jobs():
    jobs = discover_jobs(limit=20, offset=0)
    print(f"Found {len(jobs)} jobs\n")
    job_urls = []
    job_fields = []
    constructed_jobs = []  # This will be a list of lists. A constructed job is a job that's been assembled with normalized text and relevant fields. This list is a list of those

    #print("JOBS RETURN DUMP: \n" + str(jobs) + "\n\n")

    index = 0

    # Gathers first x jobs
    for job in jobs[:200]:
        #print(str(j['url']))
        #print("\n\n\n")

        #print("index = " + str(index))
        index = index + 1

        constructed_job = []

        # Passes in URL for job to get the description from HTML scraping
        job_field = fetch_other_fields(str(job["url"]))

        job_urls.append(job["url"])
        job_fields.append(job_field)

        #input(job_field["description_html"])

        after_summary = extract_after_summary(job_field["description_html"])
        normalized_after_summary = normalize_digest(after_summary)

        #input("PAUSE")

        constructed_job.append(job["title"])
        constructed_job.append(job["req_id"])
        constructed_job.append(job["location"])
        constructed_job.append(job["posted"])
        constructed_job.append(job["url"])
        constructed_job.append(normalized_after_summary)

        #print(constructed_job)

        constructed_jobs.append(constructed_job)

    return constructed_jobs


def rank_jobs(
    jobs: List[List[Any]],
    weights: Dict[str, float] | None = None,
    ) -> List[Tuple[float, List[Any], Dict[str, Any]]]:

    """
    Rank jobs by relevance to Chris's background.
    jobs: list of lists like:
        [title, req_id, location, posted, url, description]
        (only title and description are used)
    returns: list sorted DESC by score
        [(score, original_job_list, {"matches": {...}, "notes": str})]

    You can tweak weights to nudge results.
    """

    # --- Lightweight profile (edit freely) ---
    CORE_PLUS = {
        # Strong direct experience / focus areas
        "solutions": 4.0, "python": 2.5, "linux": 2.0, "unix": 1.0, "bash": 1.0,
        "kubernetes": 3.0, "openshift": 2.5, "docker": 2.0, "helm": 1.2,
        "devops": 2.0, "sre": 2.0, "ci/cd": 1.6, "jenkins": 1.0, "gitlab": 1.0, "github actions": 1.0,
        "observability": 1.3, "prometheus": 1.2, "grafana": 1.0,
        "terraform": 1.5, "infrastructure as code": 1.5,
        "virtualization": 1.2, "vmware": 1.2, "kvm": 0.8, "esxi": 0.8,
        "networking": 1.2, "tcp/ip": 1.0, "dns": 0.9,
        "testing": 2.0, "test automation": 2.2, "qa": 2.0,
        "systems engineering": 1.6, "system integration": 1.6,
        "cloud": 1.2, "aws": 1.0, "azure": 1.0, "gcp": 0.8,
    }
    NICE = {
        # Adjacent interests you’ve mentioned
        "matlab": 0.8, "simulink": 0.8, "c++": 0.8, "c/c++": 0.8, "c ": 0.4,
        "simulation": 1.0, "modeling": 0.9, "mbse": 0.9, "sysml": 0.9, "digital engineering": 0.8,
        "linux kernel": 1.0, "kernel driver": 0.9,
        "requirements": 0.6, "risk management": 0.4, "fault tolerance": 0.4,
        "cyber": 0.6, "encryption": 0.6,
    }
    LIGHT_NEG = {
        # Slight de-emphasis for highly specialized aerospace-only domains
        "hypersonic": -0.8, "missile": -0.7, "weapon": -0.7, "munitions": -0.6,
        "gnc": -0.6, "guidance": -0.4, "navigation": -0.3, "avionics": -0.4,
        "deterrent": -0.4, "war-fighter": -0.3,
    }
    TITLE_BOOST = 1.5  # weight multiplier if a keyword hits in the title

    # Allow caller to override/extend weights in one dict if desired
    # (positive or negative; keys case-insensitive)
    if weights:
        # Merge: caller overrides duplicate keys
        for k, v in weights.items():
            key = k.lower()
            if key in CORE_PLUS: CORE_PLUS[key] = v
            elif key in NICE: NICE[key] = v
            elif key in LIGHT_NEG: LIGHT_NEG[key] = v
            else:
                # Put new terms into NICE by default
                NICE[key] = v

    def _prep(text: str) -> str:
        # normalize for matching; keep spaces to enable word-ish matching
        return text.casefold()

    def _score_text(text: str, table: Dict[str, float], title: bool=False) -> tuple[float, list[str]]:
        s = 0.0
        hits = []
        for term, w in table.items():
            # word-ish match; tolerate symbols/spaces in terms like "c++", "ci/cd"
            pattern = r'(?<!\w)' + re.escape(term) + r'(?!\w)'
            if re.search(pattern, text):
                val = w * (TITLE_BOOST if title else 1.0)
                s += val
                hits.append(f"{term}({val:+.1f})")
        return s, hits

    ranked: List[Tuple[float, List[Any], Dict[str, Any]]] = []

    for job in jobs:
        if not job:
            continue
        title = str(job[0]) if len(job) > 0 else ""
        desc  = str(job[-1]) if len(job) > 0 else ""

        t = _prep(title)
        d = _prep(desc)
        both = f"{t}\n{d}"

        score = 0.0
        matches: Dict[str, list[str]] = {"core": [], "nice": [], "neg": []}

        # Score title separately for a small boost, then the full blob.
        sc, hit = _score_text(t, CORE_PLUS, title=True);      score += sc; matches["core"] += hit
        sc, hit = _score_text(both, CORE_PLUS, title=False);  score += sc; matches["core"] += hit

        sc, hit = _score_text(t, NICE, title=True);           score += sc; matches["nice"] += hit
        sc, hit = _score_text(both, NICE, title=False);       score += sc; matches["nice"] += hit

        sc, hit = _score_text(both, LIGHT_NEG, title=False);  score += sc; matches["neg"]  += hit

        # Small tie-breakers: longer, richer descriptions tend to be better signals
        # (cap the bonus so it doesn't dominate)
        length_bonus = min(len(desc) / 800.0, 1.0)  # up to +1.0
        score += length_bonus

        notes = f"title='{title[:80]}...' url='{job[4] if len(job) > 4 else ''}'"
        ranked.append((score, job, {"matches": matches, "notes": notes}))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked

def main():
    constructed_jobs = get_constructed_jobs()

    ranked = rank_jobs(constructed_jobs)

    for ranked_job in ranked:
        print("Score: " + str(ranked_job[0]) + "\nTitle: " + str(ranked_job[1][0]))
        print(str(ranked_job[1][1]))
        print(str(ranked_job[1][2]))
        print(str(ranked_job[1][3]))
        print(str(ranked_job[1][4]))
        print(str(ranked_job[1][5]))
        print("------------------\n")

if __name__ == "__main__":
    main()