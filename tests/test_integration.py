"""Integration tests — calls the real BioPortal API.

Requires BIOPORTAL_API_KEY (set in .env or CI secrets).
Skipped automatically when credentials are unavailable.
"""

import json
import os

import pytest

from snomed_mcp.server import get_concept, get_hierarchy, search

pytestmark = pytest.mark.skipif(
    not os.environ.get("BIOPORTAL_API_KEY"),
    reason="BIOPORTAL_API_KEY not set",
)


def _skip_on_api_error(result: dict | list) -> None:
    """Skip test when the API returns an error (e.g. rate limit)."""
    if isinstance(result, dict) and "error" in result:
        pytest.skip(f"API error: {result['error']}")


class TestSearch:
    async def test_finds_asthma(self):
        raw = await search("asthma")
        result = json.loads(raw)
        _skip_on_api_error(result)
        assert result["total"] > 0
        ids = [r["id"] for r in result["results"]]
        assert "195967001" in ids
        asthma = next(r for r in result["results"] if r["id"] == "195967001")
        assert "asthma" in asthma["label"].lower()

    async def test_search_result_structure(self):
        raw = await search("diabetes mellitus", limit=3)
        result = json.loads(raw)
        _skip_on_api_error(result)
        assert result["total"] > 0
        assert len(result["results"]) <= 3
        assert "page" in result
        assert "page_count" in result
        first = result["results"][0]
        assert "id" in first
        assert "label" in first
        assert any("diabetes" in r["label"].lower() for r in result["results"])


class TestGetConcept:
    async def test_asthma_full_detail(self):
        raw = await get_concept("195967001")
        result = json.loads(raw)
        _skip_on_api_error(result)
        assert result["id"] == "195967001"
        assert "asthma" in result["label"].lower()
        assert "synonyms" in result
        assert isinstance(result["synonyms"], list)
        assert len(result["synonyms"]) > 0
        assert "parents" in result
        assert len(result["parents"]) > 0
        parent = result["parents"][0]
        assert "id" in parent
        assert "label" in parent
        assert "relationships" in result
        assert any(k for k in result["relationships"])

    async def test_heart_failure_relationships(self):
        raw = await get_concept("84114007")
        result = json.loads(raw)
        _skip_on_api_error(result)
        assert result["id"] == "84114007"
        assert "heart failure" in result["label"].lower()
        rels = result.get("relationships", {})
        assert "has_finding_site" in rels or "interprets" in rels

    async def test_asthma_brief(self):
        raw = await get_concept("195967001", include_detail=False)
        result = json.loads(raw)
        _skip_on_api_error(result)
        assert result["id"] == "195967001"
        assert "label" in result
        assert "synonyms" not in result
        assert "relationships" not in result
        assert "parents" not in result


class TestGetHierarchy:
    async def test_children_of_diabetes(self):
        raw = await get_hierarchy("73211009", relation="children")
        result = json.loads(raw)
        if isinstance(result, dict):
            _skip_on_api_error(result)
        assert isinstance(result, list)
        assert len(result) > 0
        first = result[0]
        assert "id" in first
        assert "label" in first
        assert first["id"].isdigit()

    async def test_parents_of_asthma(self):
        raw = await get_hierarchy("195967001", relation="parents")
        result = json.loads(raw)
        if isinstance(result, dict):
            _skip_on_api_error(result)
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_invalid_relation_returns_error(self):
        raw = await get_hierarchy("195967001", relation="siblings")
        result = json.loads(raw)
        assert "error" in result
        assert "siblings" in result["error"]
