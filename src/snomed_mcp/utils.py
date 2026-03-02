"""Utilities for SNOMED CT MCP Server.

Constants, URI helpers, and response formatters for the BioPortal REST API.
All functions here are pure (no I/O) so they can be tested without mocking.
"""

import json
import os
from typing import Any

# API Configuration
BIOPORTAL_BASE = "https://data.bioontology.org"
BIOPORTAL_ONTOLOGY_PREFIX = "http://purl.bioontology.org/ontology/"
SNOMED_ONTOLOGY = "SNOMEDCT"
SNOMED_IRI_PREFIX = "http://purl.bioontology.org/ontology/SNOMEDCT/"
BIOPORTAL_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def get_auth_headers() -> dict[str, str]:
    """Build BioPortal authorization headers from environment.

    Raises:
        RuntimeError: If BIOPORTAL_API_KEY is not set.
    """
    key = os.environ.get("BIOPORTAL_API_KEY", "")
    if not key:
        raise RuntimeError(
            "Set BIOPORTAL_API_KEY environment variable. "
            "Get one at https://bioportal.bioontology.org/account"
        )
    return {"Authorization": f"apikey token={key}"}


# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------


def encode_class_uri(concept_id: str) -> str:
    """URL-encode a SNOMED CT class URI for BioPortal API paths."""
    import urllib.parse

    return urllib.parse.quote(f"{SNOMED_IRI_PREFIX}{concept_id}", safe="")


def extract_snomed_id(uri: str) -> str:
    """Extract numeric SNOMED ID from a full URI."""
    if uri.startswith(SNOMED_IRI_PREFIX):
        return uri[len(SNOMED_IRI_PREFIX):]
    return uri.rsplit("/", 1)[-1] if "/" in uri else uri


def concept_id(item: dict[str, Any]) -> str:
    """Extract SNOMED CT concept ID from a BioPortal API response item."""
    notation = item.get("notation", "")
    if notation:
        return notation[0] if isinstance(notation, list) else notation
    at_id = item.get("@id", "")
    if at_id.startswith(SNOMED_IRI_PREFIX):
        return at_id[len(SNOMED_IRI_PREFIX):]
    return extract_snomed_id(at_id) if at_id else ""


def parse_bioportal_uri(uri: str) -> tuple[str, str] | None:
    """Parse a BioPortal class URI into (ontology_acronym, class_id)."""
    if not uri.startswith(BIOPORTAL_ONTOLOGY_PREFIX):
        return None
    rest = uri[len(BIOPORTAL_ONTOLOGY_PREFIX):]
    parts = rest.split("/", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Collectors (extract IDs from raw concept data for batch resolution)
# ---------------------------------------------------------------------------


def collect_relationship_targets(data: dict[str, Any]) -> list[str]:
    """Collect unique SNOMED CT IDs from clinical relationship properties.

    Only picks properties whose short name is mixed-case (e.g. findingSite),
    skipping metadata keys that are ALL-CAPS (e.g. ACTIVE, MODULE_ID).
    """
    ids: set[str] = set()
    for key, values in data.get("properties", {}).items():
        if not key.startswith(SNOMED_IRI_PREFIX):
            continue
        short = key[len(SNOMED_IRI_PREFIX):]
        if short == short.upper():
            continue
        for v in values if isinstance(values, list) else [values]:
            if isinstance(v, str):
                ids.add(extract_snomed_id(v))
    return list(ids)


def collect_semantic_type_uris(data: dict[str, Any]) -> list[str]:
    """Collect semantic type URIs from concept data."""
    return [
        t
        for t in data.get("semanticType", []) or []
        if isinstance(t, str) and t.startswith(BIOPORTAL_ONTOLOGY_PREFIX)
    ]


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def format_search_results(data: dict[str, Any]) -> str:
    """Format BioPortal search response into concise JSON."""
    results = []
    for item in data.get("collection", []):
        entry: dict[str, Any] = {
            "id": concept_id(item),
            "label": item.get("prefLabel", ""),
        }
        defn = item.get("definition", [])
        if defn:
            entry["definition"] = defn[0] if isinstance(defn, list) else defn
        results.append(entry)

    return _to_json({
        "results": results,
        "total": data.get("totalCount", len(results)),
        "page": data.get("page", 1),
        "page_count": data.get("pageCount", 1),
    })


def format_concept(
    data: dict[str, Any],
    include_detail: bool = True,
    labels: dict[str, str] | None = None,
    semantic_type_labels: dict[str, str] | None = None,
) -> str:
    """Format a single BioPortal concept response.

    Args:
        data: Raw concept JSON from BioPortal.
        include_detail: If True, include synonyms, parents, relationships.
        labels: Resolved id->label map for relationship targets.
        semantic_type_labels: Resolved code->label map for semantic types.
    """
    result: dict[str, Any] = {
        "id": concept_id(data),
        "label": data.get("prefLabel", ""),
    }

    defn = data.get("definition", [])
    if defn:
        result["definition"] = defn if isinstance(defn, list) else [defn]

    if not include_detail:
        return _to_json(result)

    result["obsolete"] = data.get("obsolete", False)

    synonyms = data.get("synonym", [])
    if synonyms:
        result["synonyms"] = synonyms

    cui = data.get("cui", [])
    if cui:
        result["cui"] = cui

    sem_types = data.get("semanticType", [])
    if sem_types:
        st_labels = semantic_type_labels or {}
        resolved = []
        for t in sem_types:
            code = t.rsplit("/", 1)[-1] if isinstance(t, str) and "/" in t else str(t)
            lbl = st_labels.get(code)
            resolved.append(f"[{lbl}]({code})" if lbl else code)
        result["semantic_types"] = resolved

    parents = data.get("parents", [])
    if parents:
        result["parents"] = [
            {"id": concept_id(p), "label": p.get("prefLabel", "")}
            for p in parents
            if isinstance(p, dict)
        ]

    label_map = labels or {}
    props = data.get("properties", {})
    relationships: dict[str, list[str]] = {}
    for key, values in props.items():
        if not key.startswith(SNOMED_IRI_PREFIX):
            continue
        short = key[len(SNOMED_IRI_PREFIX):]
        if short == short.upper():
            continue
        resolved_vals = []
        for v in values if isinstance(values, list) else [values]:
            cid = extract_snomed_id(v) if isinstance(v, str) else str(v)
            lbl = label_map.get(cid)
            resolved_vals.append(f"[{lbl}]({cid})" if lbl else cid)
        relationships[short] = resolved_vals

    if relationships:
        result["relationships"] = relationships

    return _to_json(result)


def format_hierarchy(items: list[dict[str, Any]]) -> str:
    """Format hierarchy response (parents, children, etc.) into JSON."""
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {
            "id": concept_id(item),
            "label": item.get("prefLabel", ""),
        }
        defn = item.get("definition", [])
        if defn:
            entry["definition"] = defn[0] if isinstance(defn, list) else defn
        results.append(entry)
    return _to_json(results)


def format_error(message: str) -> str:
    """Format an error message as JSON."""
    return _to_json({"error": message})


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _to_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)
