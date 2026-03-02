"""Unit tests for snomed_mcp.utils — pure functions, no API calls."""

import json

import pytest

from snomed_mcp.utils import (
    BIOPORTAL_ONTOLOGY_PREFIX,
    SNOMED_IRI_PREFIX,
    collect_relationship_targets,
    collect_semantic_type_uris,
    concept_id,
    encode_class_uri,
    extract_snomed_id,
    format_concept,
    format_error,
    format_hierarchy,
    format_search_results,
    get_auth_headers,
    parse_bioportal_uri,
)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestGetAuthHeaders:
    def test_with_key(self, monkeypatch):
        monkeypatch.setenv("BIOPORTAL_API_KEY", "abc123")
        assert get_auth_headers() == {"Authorization": "apikey token=abc123"}

    def test_missing_key(self, monkeypatch):
        monkeypatch.delenv("BIOPORTAL_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="BIOPORTAL_API_KEY"):
            get_auth_headers()


# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------


class TestExtractSnomedId:
    def test_full_uri(self):
        assert extract_snomed_id(f"{SNOMED_IRI_PREFIX}195967001") == "195967001"

    def test_bare_id(self):
        assert extract_snomed_id("195967001") == "195967001"

    def test_other_uri(self):
        assert extract_snomed_id("http://example.org/123") == "123"


class TestConceptId:
    def test_from_notation(self):
        assert concept_id({"notation": ["195967001"]}) == "195967001"

    def test_from_notation_string(self):
        assert concept_id({"notation": "195967001"}) == "195967001"

    def test_from_at_id(self):
        assert concept_id({"@id": f"{SNOMED_IRI_PREFIX}195967001"}) == "195967001"

    def test_empty(self):
        assert concept_id({}) == ""


class TestEncodeClassUri:
    def test_encodes_uri(self):
        encoded = encode_class_uri("195967001")
        assert "195967001" in encoded
        assert "%2F" in encoded or "/" not in encoded


class TestParseBioportalUri:
    def test_valid_uri(self):
        uri = f"{BIOPORTAL_ONTOLOGY_PREFIX}SNOMEDCT/12345"
        result = parse_bioportal_uri(uri)
        assert result == ("SNOMEDCT", "12345")

    def test_non_bioportal_uri(self):
        assert parse_bioportal_uri("http://example.org/foo") is None

    def test_malformed_uri(self):
        assert parse_bioportal_uri(f"{BIOPORTAL_ONTOLOGY_PREFIX}NOSLASH") is None


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


class TestCollectors:
    def test_collect_relationship_targets(self):
        data = {
            "properties": {
                f"{SNOMED_IRI_PREFIX}findingSite": [f"{SNOMED_IRI_PREFIX}80891009"],
                f"{SNOMED_IRI_PREFIX}ACTIVE": ["1"],  # uppercase — skipped
                "http://other/prop": ["ignored"],
            }
        }
        ids = collect_relationship_targets(data)
        assert "80891009" in ids
        assert len(ids) == 1

    def test_collect_semantic_type_uris(self):
        data = {
            "semanticType": [
                f"{BIOPORTAL_ONTOLOGY_PREFIX}STY/T047",
                "not-a-bioportal-uri",
            ]
        }
        uris = collect_semantic_type_uris(data)
        assert len(uris) == 1
        assert uris[0].endswith("T047")


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


SAMPLE_SEARCH_RESPONSE = {
    "collection": [
        {
            "notation": ["84114007"],
            "prefLabel": "Heart failure",
            "definition": ["A disorder of cardiac function"],
            "@id": f"{SNOMED_IRI_PREFIX}84114007",
        },
        {
            "notation": ["195967001"],
            "prefLabel": "Asthma",
            "definition": [],
            "@id": f"{SNOMED_IRI_PREFIX}195967001",
        },
    ],
    "totalCount": 100,
    "page": 1,
    "pageCount": 50,
}

SAMPLE_CONCEPT_DATA = {
    "notation": ["84114007"],
    "prefLabel": "Heart failure",
    "definition": ["A disorder of cardiac function"],
    "@id": f"{SNOMED_IRI_PREFIX}84114007",
    "obsolete": False,
    "synonym": ["Cardiac failure", "HF"],
    "cui": ["C0018801"],
    "semanticType": [f"{BIOPORTAL_ONTOLOGY_PREFIX}STY/T047"],
    "parents": [
        {"notation": ["105981003"], "prefLabel": "Disorder of cardiac function", "@id": "x"}
    ],
    "properties": {
        f"{SNOMED_IRI_PREFIX}findingSite": [f"{SNOMED_IRI_PREFIX}80891009"],
        f"{SNOMED_IRI_PREFIX}ACTIVE": ["1"],
    },
}


class TestFormatSearchResults:
    def test_basic_results(self):
        result = json.loads(format_search_results(SAMPLE_SEARCH_RESPONSE))
        assert result["total"] == 100
        assert result["page"] == 1
        assert len(result["results"]) == 2
        assert result["results"][0]["id"] == "84114007"
        assert result["results"][0]["label"] == "Heart failure"
        assert result["results"][0]["definition"] == "A disorder of cardiac function"

    def test_no_definition_omitted(self):
        result = json.loads(format_search_results(SAMPLE_SEARCH_RESPONSE))
        assert "definition" not in result["results"][1]

    def test_empty_collection(self):
        result = json.loads(format_search_results({"collection": [], "totalCount": 0}))
        assert result["results"] == []


class TestFormatConcept:
    def test_brief_mode(self):
        result = json.loads(format_concept(SAMPLE_CONCEPT_DATA, include_detail=False))
        assert result["id"] == "84114007"
        assert result["label"] == "Heart failure"
        assert "definition" in result
        assert "synonyms" not in result
        assert "relationships" not in result

    def test_full_detail(self):
        labels = {"80891009": "Heart structure"}
        sem_labels = {"T047": "Disease or Syndrome"}
        result = json.loads(format_concept(
            SAMPLE_CONCEPT_DATA, include_detail=True, labels=labels,
            semantic_type_labels=sem_labels,
        ))
        assert result["synonyms"] == ["Cardiac failure", "HF"]
        assert result["cui"] == ["C0018801"]
        assert result["parents"][0]["id"] == "105981003"
        assert "[Heart structure]" in result["relationships"]["findingSite"][0]
        assert "[Disease or Syndrome]" in result["semantic_types"][0]

    def test_relationships_skip_uppercase_props(self):
        result = json.loads(format_concept(SAMPLE_CONCEPT_DATA, include_detail=True))
        assert "ACTIVE" not in result.get("relationships", {})


class TestFormatHierarchy:
    def test_basic_hierarchy(self):
        items = [
            {"notation": ["111"], "prefLabel": "Child A", "definition": ["def A"]},
            {"notation": ["222"], "prefLabel": "Child B", "definition": []},
        ]
        result = json.loads(format_hierarchy(items))
        assert len(result) == 2
        assert result[0]["id"] == "111"
        assert result[0]["definition"] == "def A"
        assert "definition" not in result[1]

    def test_empty_list(self):
        assert json.loads(format_hierarchy([])) == []

    def test_skips_non_dict(self):
        result = json.loads(format_hierarchy(["not-a-dict", {"notation": ["1"], "prefLabel": "X"}]))
        assert len(result) == 1


class TestFormatError:
    def test_simple_error(self):
        result = json.loads(format_error("Something went wrong"))
        assert result == {"error": "Something went wrong"}
