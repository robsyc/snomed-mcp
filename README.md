# SNOMED CT MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server for querying [SNOMED CT](https://www.snomed.org/) clinical terminology through the [NCBO BioPortal](https://bioportal.bioontology.org/) REST API.

## Available Tools

| Tool | Arguments | Description |
|------|-------------|
| `search` | `query` `limit` `domain` | Search SNOMED CT concepts by text query. Optional `domain` filter limits results to a SNOMED branch (e.g., `procedure`). |
| `get_concept` | `concept_id` `include_detail` | Get full concept details: label, definition, synonyms, parents, and clinical relationships. |
| `get_hierarchy` | `concept_id` `relation` `limit` | Navigate the SNOMED CT hierarchy (parents, children, ancestors, descendants). |

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A BioPortal API key (free at [bioportal.bioontology.org/account](https://bioportal.bioontology.org/account))

### Install as a tool

```bash
git clone https://github.com/robsyc/snomed-mcp && cd snomed-mcp
uv tool install .
```

Then add to your `.cursor/mcp.json` or Claude Desktop config:
```json
{
  "mcpServers": {
    "snomed-mcp": {
      "command": "snomed-mcp",
      "env": {
        "BIOPORTAL_API_KEY": "your-api-key"
      }
    }
  }
}
```

### Run with uv

```bash
git clone https://github.com/robsyc/snomed-mcp && cd snomed-mcp
uv sync
```

Add to your `.cursor/mcp.json` or Claude Desktop config:
```json
{
  "mcpServers": {
    "SNOMED CT": {
      "command": "uv",
      "args": ["tool", "run", "snomed-mcp"],
      "env": {
        "BIOPORTAL_API_KEY": "your-api-key"
      }
    }
  }
}
```

## Usage Examples

> "Search for SNOMED CT concepts related to heart failure"

> "Search for appendectomy in the `procedure` domain only"

> "Get the full details for SNOMED concept 195967001"

> "Show me the children of concept 73211009 (diabetes mellitus)"

## BioPortal API

This server wraps the [BioPortal REST API](https://data.bioontology.org/documentation). Key details:

- **Auth**: API key passed via `Authorization: apikey token=...` header
- **SNOMED CT ontology**: accessed as `SNOMEDCT` in BioPortal
- **Concept URIs**: `http://purl.bioontology.org/ontology/SNOMEDCT/{concept_id}`
- **Rate limits**: not publicly documented; the server uses a single `httpx` client with 30s timeout

## Development

```bash
uv sync --group dev

# Lint
uv run ruff check src/ tests/

# Tests
uv run pytest tests/ -v

# MCP Inspector (web UI for testing tools)
BIOPORTAL_API_KEY=your-key uv run fastmcp dev inspector src/snomed_mcp/server.py:mcp
```

## Acknowledgments

- [NCBO BioPortal](https://bioportal.bioontology.org/) for the REST API
- [SNOMED International](https://www.snomed.org/) for SNOMED CT
- [FastMCP](https://gofastmcp.com/) for the MCP framework
