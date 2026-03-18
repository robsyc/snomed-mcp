"""SNOMED CT MCP Server.

Provides MCP tools for searching and exploring SNOMED CT concepts
via the NCBO BioPortal REST API.
"""

import asyncio
import json
import urllib.parse
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP

from snomed_mcp.utils import (
    BIOPORTAL_BASE,
    BIOPORTAL_TIMEOUT,
    SNOMED_HIERARCHIES,
    SNOMED_IRI_PREFIX,
    SNOMED_ONTOLOGY,
    collect_relationship_targets,
    collect_semantic_type_uris,
    encode_class_uri,
    format_concept,
    format_error,
    format_hierarchy,
    format_search_results,
    get_auth_headers,
    parse_bioportal_uri,
)

mcp = FastMCP(
    "SNOMED CT",
    instructions=(
        "Query SNOMED CT clinical terminology via BioPortal. "
        "Use `search` to find concepts by text, `get_concept` for full details, "
        "and `get_hierarchy` to navigate parent/child relationships."
    ),
)

_client: httpx.AsyncClient | None = None
SearchDomain = Literal[
    "clinical_finding",
    "procedure",
    "observable_entity",
    "body_structure",
    "organism",
    "substance",
    "pharmaceutical_product",
    "specimen",
    "special_concept",
    "physical_object",
    "physical_force",
    "event",
    "environment",
    "social_context",
    "situation",
    "staging_and_scales",
    "qualifier_value",
    "record_artifact",
    "snomed_model_component",
]


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=BIOPORTAL_TIMEOUT)
    return _client


# ---------------------------------------------------------------------------
# Label resolution (async — needs the httpx client)
# ---------------------------------------------------------------------------


async def _resolve_labels(concept_ids: list[str]) -> dict[str, str]:
    """Fetch prefLabels for a batch of SNOMED CT concept IDs concurrently."""
    if not concept_ids:
        return {}

    async def _fetch_one(cid: str) -> tuple[str, str]:
        try:
            resp = await _get_client().get(
                f"{BIOPORTAL_BASE}/ontologies/{SNOMED_ONTOLOGY}/classes/"
                f"{encode_class_uri(cid)}",
                params={"display_context": "false", "display_links": "false"},
                headers=get_auth_headers(),
            )
            resp.raise_for_status()
            return cid, resp.json().get("prefLabel", cid)
        except httpx.HTTPError:
            return cid, cid

    results = await asyncio.gather(*(_fetch_one(cid) for cid in concept_ids))
    return dict(results)


async def _resolve_semantic_type_labels(uris: list[str]) -> dict[str, str]:
    """Fetch prefLabels for semantic type URIs (any ontology) concurrently."""
    if not uris:
        return {}

    async def _fetch_one(uri: str) -> tuple[str, str]:
        parsed = parse_bioportal_uri(uri)
        if not parsed:
            code = uri.rsplit("/", 1)[-1] if "/" in uri else uri
            return code, code
        ontology, class_id = parsed
        try:
            encoded = urllib.parse.quote(uri, safe="")
            resp = await _get_client().get(
                f"{BIOPORTAL_BASE}/ontologies/{ontology}/classes/{encoded}",
                params={"display_context": "false", "display_links": "false"},
                headers=get_auth_headers(),
            )
            resp.raise_for_status()
            return class_id, resp.json().get("prefLabel", class_id)
        except httpx.HTTPError:
            return class_id, class_id

    results = await asyncio.gather(*(_fetch_one(u) for u in uris))
    return dict(results)


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search(
    query: Annotated[str, "Search text (e.g. 'heart failure', 'diabetes mellitus')"],
    page_size: Annotated[int, "Max results to return (1-50)"] = 10,
    page: Annotated[int, "Page number"] = 1,
    include_obsolete: Annotated[bool, "Include obsolete concepts"] = False,
    domain: Annotated[
        SearchDomain | None,
        (
            "Optional SNOMED branch filter. "
            "Use one of: clinical_finding, procedure, observable_entity, body_structure, "
            "organism, substance, pharmaceutical_product, specimen, special_concept, "
            "physical_object, physical_force, event, environment, social_context, "
            "situation, staging_and_scales, qualifier_value, record_artifact, "
            "snomed_model_component."
        ),
    ] = None,
) -> str:
    """Search SNOMED CT concepts. Returns matching concept IDs, labels, and definitions."""
    try:
        params: dict[str, str | int] = {
            "q": query,
            "pagesize": min(page_size, 50),
            "page": page,
            "also_search_obsolete": str(include_obsolete).lower(),
            "display_context": "false",
            "display_links": "false",
        }
        if domain:
            branch = SNOMED_HIERARCHIES.get(str(domain).lower().strip())
            if not branch:
                valid = ", ".join(sorted(SNOMED_HIERARCHIES))
                return format_error(f"Invalid domain '{domain}'. Use one of: {valid}")
            params["ontology"] = SNOMED_ONTOLOGY
            params["subtree_root_id"] = f"{SNOMED_IRI_PREFIX}{branch[0]}"
        else:
            params["ontologies"] = SNOMED_ONTOLOGY

        resp = await _get_client().get(
            f"{BIOPORTAL_BASE}/search",
            params=params,
            headers=get_auth_headers(),
        )
        resp.raise_for_status()
        return format_search_results(resp.json())
    except httpx.HTTPError as e:
        return format_error(f"Error searching SNOMED CT: {e}")


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
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
        resp = await _get_client().get(
            f"{BIOPORTAL_BASE}/ontologies/{SNOMED_ONTOLOGY}/classes/"
            f"{encode_class_uri(concept_id)}",
            params={
                "display": "all",
                "display_context": "false",
                "display_links": "false",
            },
            headers=get_auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        labels: dict[str, str] = {}
        semantic_type_labels: dict[str, str] = {}
        if include_detail:
            target_ids = collect_relationship_targets(data)
            sem_uris = collect_semantic_type_uris(data)
            labels, semantic_type_labels = await asyncio.gather(
                _resolve_labels(target_ids),
                _resolve_semantic_type_labels(sem_uris),
            )

        return format_concept(
            data,
            include_detail=include_detail,
            labels=labels,
            semantic_type_labels=semantic_type_labels,
        )
    except httpx.HTTPError as e:
        return format_error(f"Error fetching concept {concept_id}: {e}")


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
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
        return format_error(f"Invalid relation '{relation}'. Use one of: {', '.join(valid)}")

    try:
        resp = await _get_client().get(
            f"{BIOPORTAL_BASE}/ontologies/{SNOMED_ONTOLOGY}/classes/"
            f"{encode_class_uri(concept_id)}/{relation}",
            params={
                "pagesize": page_size,
                "display_context": "false",
                "display_links": "false",
            },
            headers=get_auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list):
            return format_hierarchy(data)
        if "collection" in data:
            return format_hierarchy(data["collection"])
        return json.dumps(data, indent=2)
    except httpx.HTTPError as e:
        return format_error(f"Error fetching {relation} for {concept_id}: {e}")


def main():
    """Entry point for the MCP server."""
    mcp.run()
