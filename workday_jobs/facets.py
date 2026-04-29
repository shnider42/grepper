from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


LOCATION_FACET_HINTS = (
    "location",
    "locations",
    "locationhierarchy",
    "joblocation",
)

COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "us": ("us", "u.s.", "u.s", "usa", "u.s.a.", "united states", "united states of america", "america", "(us)"),
    "usa": ("us", "u.s.", "u.s", "usa", "u.s.a.", "united states", "united states of america", "america", "(us)"),
    "united states": ("us", "u.s.", "u.s", "usa", "u.s.a.", "united states", "united states of america", "america", "(us)"),
    "uk": ("uk", "u.k.", "united kingdom", "great britain", "england", "(uk)"),
    "canada": ("canada", "ca", "(ca)"),
}

US_STATE_ALIASES: dict[str, tuple[str, ...]] = {
    "ma": ("ma", "massachusetts"),
    "massachusetts": ("ma", "massachusetts"),
    "ca": ("ca", "california"),
    "california": ("ca", "california"),
    "nc": ("nc", "north carolina"),
    "north carolina": ("nc", "north carolina"),
    "tx": ("tx", "texas"),
    "texas": ("tx", "texas"),
    "ny": ("ny", "new york"),
    "new york": ("ny", "new york"),
    "nj": ("nj", "new jersey"),
    "new jersey": ("nj", "new jersey"),
    "va": ("va", "virginia"),
    "virginia": ("va", "virginia"),
    "fl": ("fl", "florida"),
    "florida": ("fl", "florida"),
    "co": ("co", "colorado"),
    "colorado": ("co", "colorado"),
    "wa": ("wa", "washington"),
    "washington": ("wa", "washington"),
}

COUNTRY_ONLY_LABELS = {
    "us",
    "usa",
    "u s",
    "u s a",
    "united states",
    "united states of america",
    "uk",
    "u k",
    "united kingdom",
    "canada",
}

COUNTRY_QUERY_TERMS = {
    alias
    for aliases in COUNTRY_ALIASES.values()
    for alias in aliases
} | set(COUNTRY_ALIASES.keys())


@dataclass(frozen=True)
class FacetOption:
    """One selectable value from a Workday facet dropdown.

    Workday tenants do not all expose the same location facet name. NVIDIA may expose a
    country-ish value under `locationHierarchy1`; another tenant may expose city values
    under `locations`. This object keeps the API key and selected value together.
    """

    facet_key: str
    value: str
    label: str
    count: int | None = None
    score: float = 0.0
    path: tuple[str, ...] = ()

    def as_facet_dict(self) -> dict[str, list[str]]:
        return {self.facet_key: [self.value]}


def normalize_for_match(text: str | None) -> str:
    if not text:
        return ""
    text = text.casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_country_query(query: str) -> bool:
    normalized = normalize_for_match(query)
    normalized_country_terms = {normalize_for_match(term) for term in COUNTRY_QUERY_TERMS}
    return normalized in normalized_country_terms


def is_country_only_label(label: str) -> bool:
    return normalize_for_match(label) in COUNTRY_ONLY_LABELS


def aliases_for_query(query: str) -> set[str]:
    normalized = normalize_for_match(query)
    aliases = {normalized} if normalized else set()
    raw = query.casefold().strip()

    for table in (COUNTRY_ALIASES, US_STATE_ALIASES):
        for key, values in table.items():
            normalized_values = {normalize_for_match(value) for value in values}
            if normalized == normalize_for_match(key) or normalized in normalized_values or raw in values:
                aliases.update(normalized_values)
                aliases.add(normalize_for_match(key))

    aliases.update(part for part in re.split(r"[,/|]", normalized) if part)
    return {alias for alias in aliases if alias}


def looks_like_location_facet(facet_key: str | None, facet_label: str | None) -> bool:
    haystack = normalize_for_match(f"{facet_key or ''} {facet_label or ''}")
    return any(hint in haystack for hint in LOCATION_FACET_HINTS)


def extract_facet_options(payload: dict[str, Any]) -> list[FacetOption]:
    """Flatten Workday's facet metadata into FacetOption objects.

    The CXS response has varied slightly across tenants over time, so this handles common
    shapes defensively: facetParameter/facetKey, values/items, nested children, id/value.
    """
    facets = payload.get("facets") or payload.get("facetValues") or []
    if isinstance(facets, dict):
        facets = facets.get("facets") or facets.get("values") or []
    if not isinstance(facets, list):
        return []

    options: list[FacetOption] = []
    for facet in facets:
        if not isinstance(facet, dict):
            continue
        facet_key = str(
            facet.get("facetParameter")
            or facet.get("facetKey")
            or facet.get("parameter")
            or facet.get("name")
            or ""
        )
        facet_label = str(facet.get("descriptor") or facet.get("label") or facet.get("displayName") or facet_key)
        values = facet.get("values") or facet.get("items") or facet.get("children") or []
        if isinstance(values, dict):
            values = values.get("values") or values.get("items") or []
        options.extend(_walk_facet_values(facet_key, values, parent_path=(facet_label,)))
    return options


def _walk_facet_values(
    facet_key: str,
    values: Any,
    *,
    parent_path: tuple[str, ...],
) -> Iterable[FacetOption]:
    if not isinstance(values, list):
        return []

    found: list[FacetOption] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        label = str(
            item.get("descriptor")
            or item.get("label")
            or item.get("displayName")
            or item.get("text")
            or ""
        )
        value = str(item.get("id") or item.get("value") or item.get("wid") or item.get("descriptor") or "")
        count_raw = item.get("count") or item.get("total")
        try:
            count = int(count_raw) if count_raw is not None else None
        except (TypeError, ValueError):
            count = None

        path = (*parent_path, label) if label else parent_path
        if facet_key and value and label:
            found.append(FacetOption(facet_key=facet_key, value=value, label=label, count=count, path=path))

        children = item.get("children") or item.get("values") or item.get("items") or []
        found.extend(_walk_facet_values(facet_key, children, parent_path=path))
    return found


def score_facet_option(option: FacetOption, query: str) -> float:
    aliases = aliases_for_query(query)
    if not aliases:
        return 0.0

    label = normalize_for_match(option.label)
    path = normalize_for_match(" ".join(option.path))

    # A broad country query like "US" should not select an arbitrary high-count city
    # like "San Jose, California, US". Only exact country-level labels are accepted.
    if is_country_query(query) and not is_country_only_label(option.label):
        return 0.0

    score = 0.0
    for alias in aliases:
        if label == alias:
            score = max(score, 100.0)
        elif label.startswith(alias + " ") or label.endswith(" " + alias):
            score = max(score, 90.0)
        elif f" {alias} " in f" {label} ":
            score = max(score, 80.0)
        elif alias in label:
            score = max(score, 65.0)
        elif alias and alias in path:
            score = max(score, 45.0)

    if is_country_query(query) and is_country_only_label(option.label):
        score += 20.0

    if option.count is not None:
        score += min(option.count / 1000.0, 3.0)
    return score


def search_facet_options(
    payload: dict[str, Any],
    query: str,
    *,
    location_only: bool = False,
    facet_keys: set[str] | None = None,
    limit: int = 10,
) -> list[FacetOption]:
    candidates = extract_facet_options(payload)
    matched: list[FacetOption] = []
    for option in candidates:
        if facet_keys and option.facet_key not in facet_keys:
            continue
        if location_only and not looks_like_location_facet(option.facet_key, option.path[0] if option.path else ""):
            continue
        score = score_facet_option(option, query)
        if score > 0:
            matched.append(
                FacetOption(
                    facet_key=option.facet_key,
                    value=option.value,
                    label=option.label,
                    count=option.count,
                    score=round(score, 3),
                    path=option.path,
                )
            )
    matched.sort(key=lambda item: (item.score, item.count or 0, item.label), reverse=True)
    return matched[:limit]


def merge_facets(*facet_sets: dict[str, list[str]] | None) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for facets in facet_sets:
        for key, values in (facets or {}).items():
            bucket = merged.setdefault(key, [])
            for value in values:
                if value not in bucket:
                    bucket.append(value)
    return merged
