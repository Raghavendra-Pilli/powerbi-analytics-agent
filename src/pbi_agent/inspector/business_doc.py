"""Business Documentation Generator — turns a parsed PBIP project into a
plain-language markdown report for non-technical business users.

Gathers the full raw structure from TMDLParser/ReportParser (tables, columns,
measures, relationships, roles, report pages/visuals/filters) and hands it to
Claude with strict instructions to describe only what is actually present in
the project — no invented facts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pbi_agent.inspector.tmdl_parser import (
    TMDLParser, ReportParser, SemanticModel, ReportDefinition, Table, Measure, Relationship,
)
from pbi_agent.llm.client import LLMClient
from pbi_agent.logging import get_logger

log = get_logger("business_doc")

DOC_MAX_TOKENS = 8000


class BusinessDocGenerator:
    """Generates a business-friendly documentation report from a PBIP project."""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.tmdl_parser = TMDLParser()
        self.report_parser = ReportParser()

    def generate(self, pbip_path: str | Path) -> str:
        """Parse the project and produce the full markdown documentation.

        Returns:
            Markdown text following the 12-section business documentation format.
        """
        pbip_path = Path(pbip_path)
        log.info(f"Generating business documentation for: {pbip_path}")

        model = self.tmdl_parser.parse_project(pbip_path)
        report = self.report_parser.parse_report(pbip_path)

        if model.table_count == 0:
            return f"No semantic model found at {pbip_path}. Cannot generate documentation."

        raw_data = self._build_raw_context(pbip_path, model, report)

        system_prompt = self._system_prompt()
        user_message = self._user_message(raw_data)

        markdown = self.llm.analyze(system_prompt, user_message, max_tokens=DOC_MAX_TOKENS)
        log.info("Business documentation generated")
        return markdown

    # ── Raw context assembly ────────────────────────────────────────────

    def _build_raw_context(
        self, pbip_path: Path, model: SemanticModel, report: ReportDefinition | None
    ) -> dict[str, Any]:
        """Serialize everything the parser knows into one JSON-able structure."""
        return {
            "project_path": str(pbip_path),
            "culture": model.model_info.culture,
            "tables": [self._table_dict(t, model) for t in model.tables],
            "relationships": [self._relationship_dict(r) for r in model.relationships],
            "roles": [
                {
                    "name": role.name,
                    "model_permission": role.model_permission,
                    "description": role.description,
                    "table_permissions": [
                        {"table": tp.table, "filter_expression": tp.filter_expression}
                        for tp in role.table_permissions
                    ],
                }
                for role in model.roles
            ],
            "report": report.to_summary_dict() if report else None,
            "report_pages_detail": self._report_pages_detail(report) if report else [],
        }

    def _table_dict(self, table: Table, model: SemanticModel) -> dict[str, Any]:
        incoming = sum(1 for r in model.relationships if r.to_table == table.name)
        outgoing = sum(1 for r in model.relationships if r.from_table == table.name)
        return {
            "name": table.name,
            "data_category": table.data_category,
            "likely_role_hint": self._table_role_hint(table.name, incoming, outgoing),
            "columns": [
                {
                    "name": c.name,
                    "data_type": c.data_type,
                    "description": c.description,
                    "is_key": c.is_key,
                    "is_hidden": c.is_hidden,
                    "source_column": c.source_column,
                    "summarize_by": c.summarize_by,
                    "is_calculated": "=" in c.name,
                }
                for c in table.columns
            ],
            "measures": [
                {
                    "name": m.name,
                    "expression": m.expression,
                    "format_string": m.format_string,
                    "display_folder": m.display_folder,
                    "description": m.description,
                    "referenced_measures": m.referenced_measures,
                }
                for m in table.measures
            ],
            "hierarchies": [
                {"name": h.name, "levels": [lvl.name for lvl in h.levels]}
                for h in table.hierarchies
            ],
            "partitions": [
                {"name": p.name, "mode": p.mode, "source_type": p.source_type}
                for p in table.partitions
            ],
        }

    def _table_role_hint(self, name: str, incoming: int, outgoing: int) -> str:
        """Heuristic only — final classification is left to the LLM using full context."""
        lower = name.lower()
        if lower.startswith("dim") or lower.startswith("localdatetable") or lower.startswith("datetabletemplate"):
            return "likely dimension/date table (naming convention)"
        if incoming == 0 and outgoing >= 1:
            return "likely fact table (has outgoing relationships, no incoming)"
        if incoming >= 1 and outgoing == 0:
            return "likely dimension table (referenced by other tables)"
        return "unclear from structure alone"

    def _relationship_dict(self, r: Relationship) -> dict[str, Any]:
        return {
            "from_table": r.from_table,
            "from_column": r.from_column,
            "to_table": r.to_table,
            "to_column": r.to_column,
            "cross_filtering": r.cross_filtering,
            "is_active": r.is_active,
        }

    def _report_pages_detail(self, report: ReportDefinition) -> list[dict[str, Any]]:
        pages = []
        for page in report.pages:
            visuals = []
            for v in page.visuals:
                visuals.append({
                    "name": v.name,
                    "visual_type": v.visual_type,
                    "projections": v.projections,
                    "position": {"x": v.x, "y": v.y, "width": v.width, "height": v.height},
                })
            pages.append({
                "name": page.display_name or page.name,
                "internal_name": page.name,
                "visuals": visuals,
                "filters": page.filters,
            })
        return pages

    # ── Prompting ────────────────────────────────────────────────────────

    def _system_prompt(self) -> str:
        return (
            "You are a business analyst who writes clear, non-technical documentation "
            "for Power BI reports. You will be given the full extracted structure of a "
            "Power BI project (tables, columns, measures with DAX, relationships, roles, "
            "report pages, and visuals) as JSON.\n\n"
            "STRICT RULES:\n"
            "- Only describe what is present in the provided JSON. Never invent tables, "
            "columns, measures, pages, or relationships that are not in the data.\n"
            "- If something cannot be determined from the data (e.g. refresh schedule, "
            "data source connection details, bookmarks, drill-through), say so explicitly "
            "rather than guessing.\n"
            "- Preserve exact names of tables, columns, measures, and pages as given.\n"
            "- Use simple, business-friendly language. Briefly explain any technical term "
            "you can't avoid.\n"
            "- Do not omit any table, measure, or page from the data provided.\n"
            "- Use DAX code only when needed to explain or validate a measure — do not dump "
            "raw expressions without explanation.\n"
            "- Follow the exact markdown output structure requested by the user, including "
            "all 12 sections and their tables."
        )

    def _user_message(self, raw_data: dict[str, Any]) -> str:
        return f"""Create a simple, structured documentation summary of this Power BI project that a non-technical business user can easily understand.

Cover all 12 sections in this exact order and format:

# Power BI Report – Business Documentation

## 1. Project Overview
[Simple explanation: report name, purpose, business objective, key business areas covered]

## 2. Data Tables
| Table Name | Type | Business Purpose | Key Information |
|---|---|---|---|

Then for each table:
### [Table Name]
**Purpose:**
**Important Columns:**
**Relationships:**
**Business Explanation:**

## 3. Data Model
| From Table | Column | To Table | Column | Relationship |
|---|---|---|---|---|

**Simple Explanation:** [how the tables connect, which is the main/fact table vs dimension tables]

## 4. DAX Measures
| Measure | Category | Business Definition | Used For |
|---|---|---|---|

Then for each measure:
### [Measure Name]
**What it means:**
**What it calculates:**
**Dependencies:**
**Business Value:**

## 5. Report Pages
| Page Name | Purpose | Main KPIs | Main Visuals |
|---|---|---|---|

Then for each page:
### [Page Name]
**Purpose:**
**Business Questions Answered:**
**Key KPIs:**
**Main Visuals:**
**Filters:**
**Business Interpretation:**

## 6. Report Visuals
[Structured visual-by-visual summary of the important visuals]

## 7. Filters & Slicers
[Structured summary of page-level, visual-level, report-level filters and slicers]

## 8. Security / RLS
[Explain any roles found — if none, state that no RLS roles were defined]

## 9. Data Sources
[Identify data sources from partition/source info available; state clearly what cannot be determined, e.g. live refresh schedule]

## 10. Key Business Metrics
[Simple list of the major KPIs/measures, their business definition, why they matter, where used]

## 11. Report Navigation
[Explain page organization from what's available; state explicitly if bookmarks/drill-through/buttons cannot be determined from the data]

## 12. Executive Summary
[Concise summary for a business stakeholder: what the report does, who uses it, top business questions it answers, most important tables/measures/pages, key structural insights]

Here is the full extracted project data (JSON):

{json.dumps(raw_data, indent=2, default=str)}
"""
