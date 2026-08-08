"""Model Fixer — applies automated fixes to a PBIP semantic model:

- Marks the date table properly (isKey, dataCategory: Time, Year>Quarter>Month
  hierarchy) so time-intelligence DAX functions work.
- Fills in empty measures with best-guess DAX (via Claude), clearly labeled
  as generated and needing review, plus missing format strings/display
  folders.
- Writes the result to a NEW copy of the project by default (never touches
  your original files unless in_place=True is explicitly requested).
- Computes a before/after Report Health Score so you can see the impact.

Deliberately does NOT attempt to rewrite report.json / report pages in
place — this tool's report parser could only read 0 pages from real-world
PBIP report files during testing, meaning Power BI Desktop's actual report
schema has more version-specific detail than we can safely round-trip.
Instead, new dashboard pages are handed back as a structured page/visual
specification for you (or Power BI Desktop) to build from directly.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pbi_agent.inspector.model_inspector import ModelInspector
from pbi_agent.inspector.tmdl_parser import TMDLParser, SemanticModel, Table, Measure, Hierarchy, HierarchyLevel
from pbi_agent.llm.client import LLMClient
from pbi_agent.remediate.health_score import calculate_health_score, HealthScore
from pbi_agent.remediate.tmdl_writer import write_table_tmdl
from pbi_agent.logging import get_logger

log = get_logger("model_fixer")

GENERATED_TAG = "[GENERATED — VERIFY]"


@dataclass
class FixChange:
    category: str
    description: str


@dataclass
class RemediationResult:
    success: bool
    output_path: str = ""
    before_score: HealthScore | None = None
    after_score: HealthScore | None = None
    changes: list[FixChange] = field(default_factory=list)
    dashboard_spec: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output_path": self.output_path,
            "before_score": str(self.before_score) if self.before_score else None,
            "after_score": str(self.after_score) if self.after_score else None,
            "changes": [f"[{c.category}] {c.description}" for c in self.changes],
            "error": self.error,
        }


class ModelFixer:
    """Applies automated, transparent fixes to a PBIP semantic model."""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.parser = TMDLParser()
        self.inspector = ModelInspector(config=_DummyInspectorConfig(), llm=None)

    def remediate(
        self, pbip_path: str | Path, output_dir: str | Path | None = None, in_place: bool = False
    ) -> RemediationResult:
        pbip_path = Path(pbip_path)

        # BEFORE score
        before_inspection = self.inspector.inspect(str(pbip_path), use_llm=False)
        if not before_inspection.get("success", True) and before_inspection.get("summary") is None:
            return RemediationResult(success=False, error=before_inspection.get("report", "Could not read model."))
        before_score = calculate_health_score(before_inspection.get("counts", {}))

        # Determine target path
        if in_place:
            target_path = pbip_path
        else:
            out_dir = Path(output_dir) if output_dir else pbip_path.parent
            target_path = out_dir / f"{pbip_path.name}_fixed"
            if target_path.exists():
                shutil.rmtree(target_path)
            shutil.copytree(pbip_path, target_path)

        model = self.parser.parse_project(target_path)
        if model.table_count == 0:
            return RemediationResult(success=False, error=f"No tables found in {target_path}")

        changes: list[FixChange] = []

        self._fix_date_table(model, changes)
        self._fix_measures(model, changes)
        self._write_changed_tables(target_path, model)

        dashboard_spec = self._build_dashboard_spec(model)

        # AFTER score
        after_inspection = self.inspector.inspect(str(target_path), use_llm=False)
        after_score = calculate_health_score(after_inspection.get("counts", {}))

        return RemediationResult(
            success=True,
            output_path=str(target_path),
            before_score=before_score,
            after_score=after_score,
            changes=changes,
            dashboard_spec=dashboard_spec,
        )

    # ── Date table fixes ─────────────────────────────────────────────────

    def _fix_date_table(self, model: SemanticModel, changes: list[FixChange]):
        date_tables = [t for t in model.tables if t.data_category == "Time"]
        if date_tables:
            return  # already marked

        candidates = [t for t in model.tables if "date" in t.name.lower() and not t.name.lower().startswith("local")]
        if not candidates:
            candidates = [t for t in model.tables if "date" in t.name.lower()]
        if not candidates:
            return

        # Prefer the table with the most columns (likely the "real" DimDate, not an auto-generated helper)
        target = max(candidates, key=lambda t: t.column_count)
        target.data_category = "Time"
        changes.append(FixChange("date_table", f"Marked '{target.name}' as the official date table (dataCategory: Time)."))

        date_col = next((c for c in target.columns if c.data_type == "dateTime" or c.name.lower() == "date"), None)
        if date_col and not date_col.is_key:
            date_col.is_key = True
            changes.append(FixChange("date_table", f"Marked '{target.name}[{date_col.name}]' as the key column (isKey: true)."))

        if not target.hierarchies:
            col_names = {c.name.lower(): c.name for c in target.columns}
            level_order = ["year", "quarter", "month", "date"]
            levels = [HierarchyLevel(name=col_names[k], column=col_names[k]) for k in level_order if k in col_names]
            if len(levels) >= 2:
                target.hierarchies.append(Hierarchy(name="Date Hierarchy", levels=levels))
                changes.append(FixChange(
                    "date_table",
                    f"Added a '{' > '.join(l.name for l in levels)}' hierarchy to '{target.name}'."
                ))

    # ── Measure fixes ────────────────────────────────────────────────────

    def _fix_measures(self, model: SemanticModel, changes: list[FixChange]):
        empty_measures: list[tuple[Table, Measure]] = []
        for table in model.tables:
            for m in table.measures:
                if not m.expression.strip():
                    empty_measures.append((table, m))

        if not empty_measures:
            return

        available_columns = {
            t.name: [c.name for c in t.columns] for t in model.tables
        }
        available_measures = [m.name for t in model.tables for m in t.measures if m.expression.strip()]

        generated = self._generate_measure_dax(
            [(t.name, m.name) for t, m in empty_measures], available_columns, available_measures
        )

        for table, measure in empty_measures:
            key = f"{table.name}.{measure.name}"
            fix = generated.get(key) or generated.get(measure.name)
            if not fix:
                continue
            measure.expression = fix.get("dax", "").strip()
            if not measure.format_string and fix.get("format_string"):
                measure.format_string = fix["format_string"]
            if not measure.display_folder and fix.get("display_folder"):
                measure.display_folder = fix["display_folder"]
            note = fix.get("explanation", "")
            tag_line = f"{GENERATED_TAG} {note}".strip()
            measure.description = (measure.description + " " + tag_line).strip() if measure.description else tag_line
            changes.append(FixChange(
                "measures", f"Generated DAX for '{table.name}.{measure.name}': {measure.expression}"
            ))

        # Also fill missing format strings / display folders on measures that already had DAX
        for table in model.tables:
            for m in table.measures:
                if m.expression.strip() and not m.format_string:
                    m.format_string = self._guess_format_string(m.name)
                    changes.append(FixChange("measures", f"Added format string to '{table.name}.{m.name}'."))
                if m.expression.strip() and not m.display_folder:
                    m.display_folder = self._guess_display_folder(m.name)
                    changes.append(FixChange("measures", f"Added display folder to '{table.name}.{m.name}'."))

    def _generate_measure_dax(
        self,
        empty_measures: list[tuple[str, str]],
        available_columns: dict[str, list[str]],
        available_measures: list[str],
    ) -> dict[str, dict]:
        system = (
            "You are a DAX expert fixing broken Power BI measures that currently have no "
            "expression (just a name). For each measure, write a reasonable standard DAX "
            "formula based on its name and the available columns/measures in the model. "
            "Use DIVIDE() for any ratio/percentage to avoid divide-by-zero errors. "
            "Respond with ONLY a JSON object mapping \"Table.MeasureName\" to an object with "
            "keys: dax (the DAX expression, no leading '='), format_string (e.g. \"0.0%\" or "
            "\"#,0\" or \"$#,0.00\"), display_folder (a short category like \"Sales\", "
            "\"Customer\", \"Time Intelligence\"), and explanation (one sentence on the "
            "assumption you made, since the business definition wasn't documented). "
            "No markdown, no prose outside the JSON."
        )
        user = (
            f"Empty measures to fix (Table.MeasureName): {json.dumps([f'{t}.{m}' for t, m in empty_measures])}\n\n"
            f"Available columns per table: {json.dumps(available_columns, indent=2)}\n\n"
            f"Available existing measures: {json.dumps(available_measures)}"
        )
        try:
            raw = self.llm.analyze(system, user, max_tokens=4000)
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            return json.loads(raw)
        except Exception as e:
            log.error(f"DAX generation failed: {e}")
            return {}

    def _guess_format_string(self, name: str) -> str:
        lower = name.lower()
        if "%" in name or "rate" in lower or "percent" in lower:
            return "0.0%"
        if any(k in lower for k in ["revenue", "sales", "price", "value", "cost"]):
            return "$#,0.00"
        return "#,0"

    def _guess_display_folder(self, name: str) -> str:
        lower = name.lower()
        if any(k in lower for k in ["yoy", "ytd", "qtd", "mtd", "prior", "growth"]):
            return "Time Intelligence"
        if any(k in lower for k in ["customer", "retention", "churn", "tenure"]):
            return "Customer"
        if any(k in lower for k in ["revenue", "sales", "order", "price"]):
            return "Sales"
        if any(k in lower for k in ["rank", "top", "fav"]):
            return "Ranking"
        return "General"

    # ── Write back ───────────────────────────────────────────────────────

    def _write_changed_tables(self, target_path: Path, model: SemanticModel):
        from pbi_agent.inspector.tmdl_parser import TMDLParser as _P
        sm_dir = None
        for item in target_path.iterdir():
            if item.is_dir() and item.name.endswith(".SemanticModel"):
                sm_dir = item
                break
        if not sm_dir:
            return
        tables_dir = sm_dir / "definition" / "tables"

        for table in model.tables:
            content = write_table_tmdl(table)
            # Match the file this table was originally read from (flat file or folder+definition.tmdl)
            flat_file = tables_dir / f"{table.name}.tmdl"
            folder_file = tables_dir / table.name / "definition.tmdl"
            if folder_file.exists():
                folder_file.write_text(content, encoding="utf-8")
            else:
                flat_file.write_text(content, encoding="utf-8")

    # ── Dashboard specification (not injected into report.json) ────────────

    def _build_dashboard_spec(self, model: SemanticModel) -> str:
        all_measures = [(t.name, m.name) for t in model.tables for m in t.measures if m.expression.strip()]
        date_tables = [t.name for t in model.tables if t.data_category == "Time"]
        date_table = date_tables[0] if date_tables else None

        lines = [
            "# Executive Dashboard Specification",
            "",
            "Build these two pages in Power BI Desktop using the fixed model. "
            "(Not auto-injected into report.json — see the notes in the tool's output for why.)",
            "",
            "## Page 1: Executive Overview",
            "",
            "KPI cards across the top using:",
        ]
        for table_name, measure_name in all_measures[:6]:
            lines.append(f"- {table_name}.{measure_name}")

        if date_table:
            lines.append("")
            lines.append(f"Trend line chart: X-axis = {date_table}.Date (or Month), "
                          f"Y-axis = your primary revenue/count measure.")

        lines.extend([
            "",
            "## Page 2: Customer & Sales Detail",
            "",
            "Table visual listing customer/product dimension columns alongside the relevant measures above.",
            "Add slicers for Date and any category/segment columns available in your dimension tables.",
        ])
        return "\n".join(lines)


class _DummyInspectorConfig:
    """Minimal stand-in so ModelFixer can reuse ModelInspector without the full AgentConfig."""
    flag_undocumented = True
    check_unused_columns = True
    max_tables_detail = 50
