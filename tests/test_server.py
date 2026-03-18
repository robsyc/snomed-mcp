"""Unit tests for snomed_mcp.server tool parameter behavior."""

import json

from snomed_mcp import server
from snomed_mcp.utils import SNOMED_IRI_PREFIX, SNOMED_ONTOLOGY


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def get(self, url, params, headers):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return _FakeResponse({"collection": [], "totalCount": 0, "page": 1, "pageCount": 1})


class TestSearchParams:
    async def test_legacy_search_uses_ontologies_param(self, monkeypatch):
        client = _FakeClient()
        monkeypatch.setattr(server, "_get_client", lambda: client)
        monkeypatch.setattr(server, "get_auth_headers", lambda: {})

        result = json.loads(await server.search("asthma"))

        assert "error" not in result
        params = client.calls[0]["params"]
        assert params["ontologies"] == SNOMED_ONTOLOGY
        assert "ontology" not in params
        assert "subtree_root_id" not in params

    async def test_domain_search_uses_subtree_filters(self, monkeypatch):
        client = _FakeClient()
        monkeypatch.setattr(server, "_get_client", lambda: client)
        monkeypatch.setattr(server, "get_auth_headers", lambda: {})

        result = json.loads(await server.search("appendectomy", domain="Procedure"))

        assert "error" not in result
        params = client.calls[0]["params"]
        assert params["ontology"] == SNOMED_ONTOLOGY
        assert params["subtree_root_id"] == f"{SNOMED_IRI_PREFIX}71388002"
        assert "ontologies" not in params

    async def test_invalid_domain_returns_error(self, monkeypatch):
        monkeypatch.setattr(server, "get_auth_headers", lambda: {})

        result = json.loads(await server.search("x", domain="invalid_domain"))  # type: ignore[arg-type]

        assert "error" in result
        assert "Invalid domain" in result["error"]
