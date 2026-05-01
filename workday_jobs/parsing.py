from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


REQ_ID_RE = re.compile(r"_([A-Za-z]*\d+)(?:\?.*)?$")
JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>\s*(.*?)\s*</script>',
    flags=re.S | re.I,
)

DEFAULT_STOP_CUES = [
    r"\bAdditional Job Description\b",
    r"\bThe US base salary range\b",
    r"\bThe U\.S\. base salary range\b",
    r"\bEqual Opportunity Employer\b",
    r"\bE-Verify\b",
    r"\bConnect With\b",
    r"\bExplore life at\b",
    r"\bReasonable accommodation\b",
]

DEFAULT_START_CUES = [
    r"\bJob Description Summary:\s*",
    r"\bWhat you will be doing:\s*",
    r"\bWhat you'll be doing:\s*",
    r"\bWhat you’ll be doing:\s*",
    r"\bResponsibilities:?\s*",
    r"\bDuties/Responsibilities:?\s*",
]


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "section", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "li":
            self.parts.append("\n- ")
        elif tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def parse_req_id_from_path(path: str) -> str:
    match = REQ_ID_RE.search(path or "")
    return match.group(1) if match else ""


def compact_location(posting: dict[str, Any]) -> str:
    loc = posting.get("locationsText")
    if loc:
        return str(loc)

    for sub in posting.get("subtitles", []) or []:
        if not isinstance(sub, dict):
            continue
        label = str(sub.get("label") or "").lower()
        if label.startswith("location"):
            value = sub.get("value")
            if value:
                return str(value)

    locs = posting.get("locations") or []
    names = [str(l.get("descriptor")) for l in locs if isinstance(l, dict) and l.get("descriptor")]
    return ", ".join(names)


def compact_posted_on(posting: dict[str, Any]) -> str:
    for sub in posting.get("subtitles", []) or []:
        if not isinstance(sub, dict):
            continue
        label = str(sub.get("label") or "").lower()
        if "posted" in label:
            return str(sub.get("value") or "")
    return str(posting.get("postedOn") or "")


def build_public_job_url(
    base_url: str,
    site: str,
    external_path: str,
    *,
    locale: str = "en-US",
    public_path_prefix: str | None = None,
) -> str:
    prefix = public_path_prefix or f"/{locale}/{site}"
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"

    if not external_path:
        return f"{base_url}{prefix}"
    if external_path.startswith("http://") or external_path.startswith("https://"):
        return external_path

    path = external_path if external_path.startswith("/") else f"/{external_path}"
    return urljoin(base_url, prefix.rstrip("/") + path)


def extract_json_ld(html_text: str) -> dict[str, Any]:
    match = JSON_LD_RE.search(html_text or "")
    if not match:
        return {}

    raw = html.unescape(match.group(1).strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Workday usually emits a single JobPosting object, but keep this tolerant.
        return {}

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
        return data[0] if data and isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}


def html_to_text(html_text: str | None) -> str:
    if not html_text:
        return ""
    parser = _TextExtractor()
    parser.feed(html.unescape(html_text))
    return normalize_text(parser.text())


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = text.replace("â¢", "-").replace("•", "-")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def clean_description(
    description_html: str | None,
    *,
    start_cues: list[str] | None = None,
    stop_cues: list[str] | None = None,
) -> str:
    """Clean a Workday JobPosting description.

    Important behavior: if no preferred heading is found, return the full cleaned description.
    This avoids the Cisco-style failure mode where every job description became None.
    """
    text = html_to_text(description_html)
    if not text:
        return ""

    starts = start_cues or DEFAULT_START_CUES
    stops = stop_cues or DEFAULT_STOP_CUES

    selected = text
    for cue in starts:
        match = re.search(cue, selected, flags=re.I)
        if match:
            selected = selected[match.end():]
            break

    stop_re = re.compile("|".join(stops), re.I)
    stop = stop_re.search(selected)
    if stop:
        selected = selected[: stop.start()]

    replacements = [
        (r"\bJob Description:\s*", ""),
        (r"\bDuties/Responsibilities\b:?", "Duties & Responsibilities:"),
        (r"\bSkills/Abilities\b:?", "Skills & Abilities:"),
        (r"\bEducation\b:?", "Education:"),
        (r"\bExperience\b:?", "Experience:"),
        (r"\bWhat we need to see:\b:?", "What we need to see:"),
        (r"\bWays to stand out from the crowd:\b:?", "Ways to stand out from the crowd:"),
    ]
    for pattern, replacement in replacements:
        selected = re.sub(pattern, replacement, selected, flags=re.I)

    return normalize_text(selected)
