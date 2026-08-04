from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EUROSTAT_HELPER = ROOT / "eurostat_api.py"
if not EUROSTAT_HELPER.exists():
    EUROSTAT_HELPER = ROOT.parent / "scripts" / "eurostat_api.py"
SKILL = ROOT / "SKILL.md"
if not SKILL.exists():
    SKILL = ROOT.parent / "SKILL.md"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LIMITS_PATH = ROOT / "agent_limits.json"
if not LIMITS_PATH.exists():
    LIMITS_PATH = ROOT.parent / "agent_limits.json"
LIMITS = json.loads(LIMITS_PATH.read_text(encoding="utf-8"))
MAX_TOOL_CHARS = int(LIMITS["max_tool_output_characters"])
MAX_RESULT_ROWS = int(LIMITS["max_result_rows"])
MAX_TOOL_ROUNDS = int(LIMITS["max_model_rounds"])
MAX_TOOL_CALLS = int(LIMITS["max_tool_calls"])
MAX_EUROSTAT_RESPONSE_BYTES = int(LIMITS["max_eurostat_response_bytes"])
MAX_ESTIMATED_CELLS = int(LIMITS["max_estimated_cells"])
MAX_TIME_PERIODS = int(LIMITS["max_time_periods"])
MAX_RECENT_MESSAGES = int(LIMITS["max_recent_messages"])
MAX_SUMMARY_CHARACTERS = int(LIMITS["max_summary_characters"])
MIN_CATALOG_RESULTS = 12
TOOL_CALL_LIMITS = {
    str(name): int(limit) for name, limit in LIMITS["tool_call_limits"].items()
}
EVENT_PREFIX = "__EUROSTAT_EVENT__"
MAX_EVENT_PREVIEW_CHARS = 700
CATALOG_CACHE = Path(os.getenv("EUROSTAT_CATALOG_CACHE", ROOT / "eurostat_toc.tsv"))
CHART_REFERENCE = ROOT / "chart-selection.md"
if not CHART_REFERENCE.exists():
    CHART_REFERENCE = ROOT.parent / "references" / "chart-selection.md"

CHART_TYPES = {
    "line",
    "area",
    "bar",
    "dot",
    "scatter",
    "heatmap",
    "histogram",
    "boxplot",
}
CHART_PURPOSES = {
    "trend",
    "comparison",
    "relationship",
    "distribution",
    "composition",
    "change",
}

TOOL_REASON_PROPERTY = {
    "type": "string",
    "maxLength": 160,
    "description": (
        "One brief user-facing sentence explaining what this call will retrieve or verify. "
        "Do not include hidden reasoning."
    ),
}

CHART_TOOL_PROPERTIES = {
    "purpose": {
        "type": "string",
        "enum": sorted(CHART_PURPOSES),
        "description": "The analytical relationship the chart should communicate.",
    },
    "type": {"type": "string", "enum": ["auto", *sorted(CHART_TYPES)]},
    "x": {"type": "string", "description": "Horizontal/category/bin field."},
    "y": {"type": "string", "description": "Vertical numeric field."},
    "color": {"type": "string", "description": "Numeric intensity field for a heatmap."},
    "size": {"type": "string", "description": "Optional numeric point-size field."},
    "series": {"type": "string", "description": "Optional categorical grouping field."},
    "label": {"type": "string", "description": "Optional reader-facing point label field."},
    "orientation": {"type": "string", "enum": ["horizontal", "vertical"]},
    "stack": {"type": "string", "enum": ["none", "stacked", "normalize"]},
    "sort": {"type": "string", "enum": ["natural", "ascending", "descending"]},
    "top_n": {"type": "integer", "minimum": 1, "maximum": 50},
    "trendline": {"type": "string", "enum": ["none", "linear"]},
    "labels": {"type": "string", "enum": ["hover", "always"]},
    "scale": {"type": "string", "enum": ["linear", "log"]},
    "zero_baseline": {
        "type": "string",
        "enum": ["auto", "zero", "free"],
    },
    "x_label": {"type": "string", "maxLength": 80},
    "y_label": {"type": "string", "maxLength": 80},
    "title": {"type": "string", "maxLength": 160},
}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_eurostat",
            "description": "Search Eurostat table-of-contents metadata for candidate datasets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": (
                            "Requested candidate count. The host returns at least 12 bounded "
                            "candidates so family tables with the requested category in a "
                            "dimension are not hidden by literal-title matches."
                        ),
                    },
                    "reason": TOOL_REASON_PROPERTY,
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_dimensions",
            "description": (
                "Inspect dimensions and sample categories from Eurostat structural metadata "
                "without requesting observations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {"type": "string"},
                    "matches": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 8,
                        "description": (
                            "Requested category labels or codes to match across the complete "
                            "dimension catalog, including regions, units, and products."
                        ),
                    },
                    "reason": TOOL_REASON_PROPERTY,
                },
                "required": ["dataset"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_eurostat",
            "description": "Fetch a bounded Eurostat data slice as flattened JSON rows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {"type": "string"},
                    "params": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "Dimension filter in key=value form, for example geo=DE or sex=T.",
                        },
                    },
                    "last_time_period": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_TIME_PERIODS,
                    },
                    "time": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_TIME_PERIODS,
                    },
                    "reason": TOOL_REASON_PROPERTY,
                },
                "required": ["dataset"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_result",
            "description": (
                "Publish fetched or reusable rows as the answer's table and optional chart. "
                "Pass one result ID to select or re-chart it. Pass two result IDs plus join_on "
                "and axis labels to create a paired scatter result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "result_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 2,
                        "description": (
                            "Opaque fetch result IDs in publication order, or ['context'] for "
                            "the reusable previous result."
                        ),
                    },
                    "join_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "Shared keys for pairing two results, normally geo and time.",
                    },
                    "x_label": {"type": "string", "maxLength": 80},
                    "y_label": {"type": "string", "maxLength": 80},
                    "title": {"type": "string", "maxLength": 160},
                    "label": {"type": "string", "maxLength": 80},
                    "chart": {
                        "type": "object",
                        "properties": CHART_TOOL_PROPERTIES,
                        "required": ["purpose"],
                        "additionalProperties": False,
                    },
                    "reason": TOOL_REASON_PROPERTY,
                },
                "required": ["result_ids"],
                "additionalProperties": False,
            },
        },
    },
]
