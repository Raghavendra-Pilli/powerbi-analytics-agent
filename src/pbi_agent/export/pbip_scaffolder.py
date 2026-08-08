"""PBIP Scaffolder — generates a starter .pbip project (TMDL model + basic
report) from a connected CSV/Excel file.

This is a best-effort scaffold, not a guarantee of a byte-perfect Power BI
Desktop file. It produces a project this tool's own parser/inspector/
reviewer/document commands can read immediately, and gives Power BI Desktop
a working starting point (tables, columns, an import partition, and a basic
report page) that may need a "Transform Data" refresh or minor fixes when
first opened in Desktop, since Desktop's full on-disk schema has more
version-specific detail than a hand-built scaffold can guarantee.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from pbi_agent.connectors.csv_connector import FileConnectionResult, TableMeta
from pbi_agent.logging import get_logger

log = get_logger("pbip_scaffolder")

# TMDL data types line up with the connector's already-normalized dtypes.
NUMERIC_TYPES = {"int64", "double"}


@dataclass
class ScaffoldResult:
    success: bool
    output_path: str = ""
    message: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output_path": self.output_path,
            "message": self.message,
            "error": self.error,
            "warnings": self.warnings,
        }


class PbipScaffolder:
    """Builds a starter PBIP project from connected file metadata."""

    def scaffold(
        self,
        file_result: FileConnectionResult,
        output_dir: str | Path,
        project_name: str | None = None,
    ) -> ScaffoldResult:
        if not file_result.success or not file_result.tables:
            return ScaffoldResult(success=False, error="No connected tables to scaffold from.")

        name = self._sanitize_name(project_name or Path(file_result.name).stem or "NewProject")
        output_dir = Path(output_dir)
        project_dir = output_dir / name
        sm_dir = project_dir / f"{name}.SemanticModel"
        report_dir = project_dir / f"{name}.Report"

        warnings: list[str] = []

        try:
            (sm_dir / "definition" / "tables").mkdir(parents=True, exist_ok=True)
            (report_dir / "definition").mkdir(parents=True, exist_ok=True)

            # .pbip manifest
            manifest = {
                "version": "1.0",
                "artifacts": [
                    {"report": {"path": f"{name}.Report"}},
                    {"dataset": {"path": f"{name}.SemanticModel"}},
                ],
                "settings": {"enableAutoRecovery": True},
            }
            (project_dir / f"{name}.pbip").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            # model.tmdl
            model_tmdl = 'model Model\n\tculture: en-US\n\n'
            (sm_dir / "definition" / "model.tmdl").write_text(model_tmdl, encoding="utf-8")

            # One .tmdl file per table (flat format)
            table_names = []
            for table in file_result.tables:
                safe_table_name = self._sanitize_name(table.name)
                table_names.append(safe_table_name)
                tmdl_text, table_warnings = self._build_table_tmdl(table, safe_table_name)
                warnings.extend(table_warnings)
                (sm_dir / "definition" / "tables" / f"{safe_table_name}.tmdl").write_text(
                    tmdl_text, encoding="utf-8"
                )

            # Minimal report.json: one page per table with a table visual of all columns
            report_json = self._build_report_json(name, file_result.tables, table_names)
            (report_dir / "definition" / "report.json").write_text(
                json.dumps(report_json, indent=2), encoding="utf-8"
            )

            log.info(f"Scaffolded PBIP project at: {project_dir}")

            warnings.append(
                "This is a generated starting point, not a guaranteed byte-perfect Power BI "
                "Desktop file. When you open it in Desktop, use 'Transform Data' to verify the "
                "data source connection, and check column data types."
            )

            return ScaffoldResult(
                success=True,
                output_path=str(project_dir),
                message=f"Created starter PBIP project at: {project_dir}",
                warnings=warnings,
            )
        except Exception as e:
            log.error(f"Scaffold failed: {e}")
            return ScaffoldResult(success=False, error=str(e))

    # ── TMDL generation ──────────────────────────────────────────────────

    def _build_table_tmdl(self, table: TableMeta, safe_name: str) -> tuple[str, list[str]]:
        warnings: list[str] = []
        lines = [f"table {safe_name}", ""]

        for col in table.columns:
            summarize_by = "sum" if col.dtype in NUMERIC_TYPES else "none"
            lines.append(f"\tcolumn '{col.name}'")
            lines.append(f"\t\tdataType: {col.dtype}")
            lines.append(f"\t\tsummarizeBy: {summarize_by}")
            lines.append(f"\t\tsourceColumn: {col.name}")
            lines.append("")

        m_expr, m_warnings = self._build_m_expression(table)
        warnings.extend(m_warnings)

        lines.append(f"\tpartition {safe_name} = m")
        lines.append("\t\tmode: import")
        lines.append("\t\tsource =")
        for m_line in m_expr.splitlines():
            lines.append(f"\t\t\t{m_line}")
        lines.append("")

        return "\n".join(lines), warnings

    def _build_m_expression(self, table: TableMeta) -> tuple[str, list[str]]:
        warnings: list[str] = []
        path = table.source_path.replace('"', '""')
        ext = table.file_type.lower()

        if ext == "csv":
            return (
                'let\n'
                f'    Source = Csv.Document(File.Contents("{path}"), '
                '[Delimiter=",", Columns=' + str(len(table.columns)) + ', Encoding=65001, QuoteStyle=QuoteStyle.None]),\n'
                '    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true])\n'
                'in\n'
                '    #"Promoted Headers"'
            ), warnings

        if ext in ("xlsx", "xls"):
            sheet_name = "Sheet1"
            try:
                sheet_name = pd.ExcelFile(table.source_path).sheet_names[0]
            except Exception as e:
                warnings.append(
                    f"Could not detect the sheet name for '{table.name}' automatically "
                    f"({e}); the generated Power Query uses a placeholder sheet name — "
                    "verify it in Power BI Desktop's Transform Data / Power Query editor."
                )
            sheet_escaped = sheet_name.replace('"', '""')
            return (
                'let\n'
                f'    Source = Excel.Workbook(File.Contents("{path}"), null, true),\n'
                f'    Data = Source{{[Item="{sheet_escaped}",Kind="Sheet"]}}[Data],\n'
                '    #"Promoted Headers" = Table.PromoteHeaders(Data, [PromoteAllScalars=true])\n'
                'in\n'
                '    #"Promoted Headers"'
            ), warnings

        warnings.append(f"Unrecognized file type '{ext}' for table '{table.name}' — generated a placeholder M query.")
        return f'let\n    Source = "{path}"\nin\n    Source', warnings

    # ── Report generation ────────────────────────────────────────────────

    def _build_report_json(
        self, project_name: str, tables: list[TableMeta], table_names: list[str]
    ) -> dict[str, Any]:
        sections = []
        for i, (table, safe_name) in enumerate(zip(tables, table_names)):
            projections = [{"queryRef": f"{safe_name}.{c.name}"} for c in table.columns]
            sections.append({
                "name": f"ReportSection{i}",
                "displayName": safe_name,
                "ordinal": i,
                "width": 1280,
                "height": 720,
                "visualContainers": [
                    {
                        "x": 0, "y": 0, "width": 1280, "height": 600,
                        "config": {
                            "name": f"table_{safe_name}",
                            "type": "tableEx",
                            "singleVisual": {
                                "visualType": "tableEx",
                                "projections": {"Values": projections},
                            },
                        },
                    }
                ],
                "filters": [],
            })

        return {
            "id": "report-scaffold",
            "reportId": "report-scaffold",
            "name": project_name,
            "description": f"Auto-generated starter report for {project_name}",
            "layoutOptimization": 0,
            "resourcePackages": [],
            "sections": sections,
            "config": {"version": "5.50"},
        }

    def _sanitize_name(self, name: str) -> str:
        """Make a name safe for use as a table/project identifier."""
        cleaned = re.sub(r"[^\w\s\-]", "", name).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned or "Table"
