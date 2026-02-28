"""SNOMED CT MCP Server.

Provides MCP tools for searching and exploring SNOMED CT concepts
via the NCBO BioPortal REST API.
"""

import asyncio
import json
import os
import urllib.parse
from typing import Annotated

import httpx
from fastmcp import FastMCP

BIOPORTAL_BASE = "https://data.bioontology.org"
BIOPORTAL_ONTOLOGY_PREFIX = "http://purl.bioontology.org/ontology/"
SNOMED_ONTOLOGY = "SNOMEDCT"
SNOMED_IRI_PREFIX = "http://purl.bioontology.org/ontology/SNOMEDCT/"

mcp = FastMCP(
    "SNOMED CT",
    instructions=(
        "Query SNOMED CT clinical terminology via BioPortal. "
        "Use `search` to find concepts by text, `get_concept` for full details, "
        "and `get_hierarchy` to navigate parent/child relationships."
    ),
)

client = httpx.AsyncClient(timeout=30.0)


def _auth_headers() -> dict[str, str]:
    key = os.environ.get("BIOPORTAL_API_KEY", "")
    if not key:
        raise RuntimeError(
            "Set BIOPORTAL_API_KEY environment variable. "
            "Get one at https://bioportal.bioontology.org/account"
        )
    return {"Authorization": f"apikey token={key}"}


def _encode_class_uri(concept_id: str) -> str:
    """URL-encode a SNOMED CT class URI for use in BioPortal API paths."""
    return urllib.parse.quote(f"{SNOMED_IRI_PREFIX}{concept_id}", safe="")


def _extract_snomed_id(uri: str) -> str:
    """Extract numeric SNOMED ID from a full URI."""
    if uri.startswith(SNOMED_IRI_PREFIX):
        return uri[len(SNOMED_IRI_PREFIX) :]
    return uri.rsplit("/", 1)[-1] if "/" in uri else uri


# ---------------------------------------------------------------------------
# Label resolution
# ---------------------------------------------------------------------------


def _collect_relationship_targets(data: dict) -> list[str]:
    """Collect unique SNOMED CT IDs from clinical relationship properties."""
    ids: set[str] = set()
    for key, values in data.get("properties", {}).items():
        if not key.startswith(SNOMED_IRI_PREFIX):
            continue
        short = key[len(SNOMED_IRI_PREFIX) :]
        if short == short.upper():
            continue
        for v in values if isinstance(values, list) else [values]:
            if isinstance(v, str):
                ids.add(_extract_snomed_id(v))
    return list(ids)


def _collect_semantic_type_uris(data: dict) -> list[str]:
    """Collect semantic type URIs from concept data."""
    uris: list[str] = []
    for t in data.get("semanticType", []) or []:
        if isinstance(t, str) and t.startswith(BIOPORTAL_ONTOLOGY_PREFIX):
            uris.append(t)
    return uris


def _parse_bioportal_uri(uri: str) -> tuple[str, str] | None:
    """Parse a BioPortal class URI into (ontology_acronym, class_id). Returns None if not a BioPortal ontology URI."""
    if not uri.startswith(BIOPORTAL_ONTOLOGY_PREFIX):
        return None
    rest = uri[len(BIOPORTAL_ONTOLOGY_PREFIX) :]
    parts = rest.split("/", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


async def _resolve_labels(concept_ids: list[str]) -> dict[str, str]:
    """Fetch prefLabels for a batch of SNOMED CT concept IDs concurrently."""
    if not concept_ids:
        return {}

    async def _fetch_one(cid: str) -> tuple[str, str]:
        try:
            resp = await client.get(
                f"{BIOPORTAL_BASE}/ontologies/{SNOMED_ONTOLOGY}/classes/"
                f"{_encode_class_uri(cid)}",
                params={"display_context": "false", "display_links": "false"},
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            return cid, resp.json().get("prefLabel", cid)
        except httpx.HTTPError:
            return cid, cid

    results = await asyncio.gather(*(_fetch_one(cid) for cid in concept_ids))
    return dict(results)


async def _resolve_semantic_type_labels(uris: list[str]) -> dict[str, str]:
    """Fetch prefLabels for semantic type URIs (any ontology) concurrently. Returns code -> label."""
    if not uris:
        return {}

    async def _fetch_one(uri: str) -> tuple[str, str]:
        parsed = _parse_bioportal_uri(uri)
        if not parsed:
            code = uri.rsplit("/", 1)[-1] if "/" in uri else uri
            return code, code
        ontology, class_id = parsed
        try:
            encoded = urllib.parse.quote(uri, safe="")
            resp = await client.get(
                f"{BIOPORTAL_BASE}/ontologies/{ontology}/classes/{encoded}",
                params={"display_context": "false", "display_links": "false"},
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            return class_id, resp.json().get("prefLabel", class_id)
        except httpx.HTTPError:
            return class_id, class_id

    results = await asyncio.gather(*(_fetch_one(u) for u in uris))
    return dict(results)


# ---------------------------------------------------------------------------
# Response formatters
# ---------------------------------------------------------------------------


def _concept_id(item: dict) -> str:
    """Extract SNOMED CT concept ID from an API response item."""
    notation = item.get("notation", "")
    if notation:
        return notation[0] if isinstance(notation, list) else notation
    at_id = item.get("@id", "")
    if at_id.startswith(SNOMED_IRI_PREFIX):
        return at_id[len(SNOMED_IRI_PREFIX) :]
    return _extract_snomed_id(at_id) if at_id else ""


def _format_search_results(data: dict) -> str:
    results = []
    for item in data.get("collection", []):
        entry: dict = {
            "id": _concept_id(item),
            "label": item.get("prefLabel", ""),
        }
        defn = item.get("definition", [])
        if defn:
            entry["definition"] = defn[0] if isinstance(defn, list) else defn
        results.append(entry)

    return json.dumps(
        {
            "results": results,
            "total": data.get("totalCount", len(results)),
            "page": data.get("page", 1),
            "page_count": data.get("pageCount", 1),
        },
        indent=2,
    )


def _format_concept(
    data: dict,
    include_detail: bool = True,
    labels: dict[str, str] | None = None,
    semantic_type_labels: dict[str, str] | None = None,
) -> str:
    concept: dict = {
        "id": _concept_id(data),
        "label": data.get("prefLabel", ""),
    }

    defn = data.get("definition", [])
    if defn:
        concept["definition"] = defn if isinstance(defn, list) else [defn]

    if not include_detail:
        return json.dumps(concept, indent=2)

    concept["obsolete"] = data.get("obsolete", False)

    synonyms = data.get("synonym", [])
    if synonyms:
        concept["synonyms"] = synonyms

    cui = data.get("cui", [])
    if cui:
        concept["cui"] = cui

    sem_types = data.get("semanticType", [])
    if sem_types:
        st_labels = semantic_type_labels or {}
        resolved = []
        for t in sem_types:
            code = t.rsplit("/", 1)[-1] if isinstance(t, str) and "/" in t else str(t)
            lbl = st_labels.get(code)
            resolved.append(f"[{lbl}]({code})" if lbl else code)
        concept["semantic_types"] = resolved

    parents = data.get("parents", [])
    if parents:
        concept["parents"] = [
            {"id": _concept_id(p), "label": p.get("prefLabel", "")}
            for p in parents
            if isinstance(p, dict)
        ]

    # Extract SNOMED clinical relationship properties (lowercase keys),
    # skip metadata (UPPERCASE keys) and standard vocab properties.
    label_map = labels or {}
    props = data.get("properties", {})
    relationships: dict[str, list[str]] = {}
    for key, values in props.items():
        if not key.startswith(SNOMED_IRI_PREFIX):
            continue
        short = key[len(SNOMED_IRI_PREFIX) :]
        if short == short.upper():
            continue
        resolved = []
        for v in values if isinstance(values, list) else [values]:
            cid = _extract_snomed_id(v) if isinstance(v, str) else str(v)
            lbl = label_map.get(cid)
            resolved.append(f"[{lbl}]({cid})" if lbl else cid)
        relationships[short] = resolved

    if relationships:
        concept["relationships"] = relationships

    return json.dumps(concept, indent=2)


def _format_hierarchy(items: list) -> str:
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry: dict = {
            "id": _concept_id(item),
            "label": item.get("prefLabel", ""),
        }
        defn = item.get("definition", [])
        if defn:
            entry["definition"] = defn[0] if isinstance(defn, list) else defn
        results.append(entry)
    return json.dumps(results, indent=2)


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def search(
    query: Annotated[str, "Search text (e.g. 'heart failure', 'diabetes mellitus')"],
    page_size: Annotated[int, "Max results to return (1-50)"] = 10,
    page: Annotated[int, "Page number"] = 1,
    include_obsolete: Annotated[bool, "Include obsolete concepts"] = False,
) -> str:
    """Search SNOMED CT concepts. Returns matching concept IDs, labels, and definitions."""
    try:
        resp = await client.get(
            f"{BIOPORTAL_BASE}/search",
            params={
                "q": query,
                "ontologies": SNOMED_ONTOLOGY,
                "pagesize": min(page_size, 50),
                "page": page,
                "also_search_obsolete": str(include_obsolete).lower(),
                "display_context": "false",
                "display_links": "false",
            },
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        return _format_search_results(resp.json())
    except httpx.HTTPError as e:
        return f"Error searching SNOMED CT: {e}"


@mcp.tool()
async def get_concept(
    concept_id: Annotated[str, "SNOMED CT concept ID (e.g. '195967001' for Asthma)"],
    include_detail: Annotated[
        bool,
        "Return full detail (synonyms, parents, clinical relationships). "
        "When False, only label and definition are returned.",
    ] = True,
) -> str:
    """Get full details for a SNOMED CT concept: label, definition, synonyms, parents, and clinical relationships."""
    try:
        resp = await client.get(
            f"{BIOPORTAL_BASE}/ontologies/{SNOMED_ONTOLOGY}/classes/{_encode_class_uri(concept_id)}",
            params={
                "display": "all",
                "display_context": "false",
                "display_links": "false",
            },
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        labels: dict[str, str] = {}
        semantic_type_labels: dict[str, str] = {}
        if include_detail:
            target_ids = _collect_relationship_targets(data)
            sem_uris = _collect_semantic_type_uris(data)
            labels, semantic_type_labels = await asyncio.gather(
                _resolve_labels(target_ids),
                _resolve_semantic_type_labels(sem_uris),
            )

        return _format_concept(
            data,
            include_detail=include_detail,
            labels=labels,
            semantic_type_labels=semantic_type_labels,
        )
    except httpx.HTTPError as e:
        return f"Error fetching concept {concept_id}: {e}"


@mcp.tool()
async def get_hierarchy(
    concept_id: Annotated[str, "SNOMED CT concept ID"],
    relation: Annotated[
        str,
        "One of: 'parents', 'children', 'ancestors', 'descendants'",
    ] = "children",
    page_size: Annotated[int, "Max results"] = 25,
) -> str:
    """Get hierarchically related SNOMED CT concepts (parents, children, ancestors, or descendants)."""
    valid = ("parents", "children", "ancestors", "descendants")
    if relation not in valid:
        return f"Invalid relation '{relation}'. Use one of: {', '.join(valid)}"

    try:
        resp = await client.get(
            f"{BIOPORTAL_BASE}/ontologies/{SNOMED_ONTOLOGY}/classes/"
            f"{_encode_class_uri(concept_id)}/{relation}",
            params={
                "pagesize": page_size,
                "display_context": "false",
                "display_links": "false",
            },
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list):
            return _format_hierarchy(data)
        if "collection" in data:
            return _format_hierarchy(data["collection"])
        return json.dumps(data, indent=2)
    except httpx.HTTPError as e:
        return f"Error fetching {relation} for {concept_id}: {e}"


def main():
    """Entry point for the MCP server."""
    mcp.run()
