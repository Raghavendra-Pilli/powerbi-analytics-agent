"""Model Inspector — analyzes TMDL semantic models with rule-based checks + LLM analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pbi_agent.config import InspectorConfig
from pbi_agent.inspector.tmdl_parser import TMDLParser, SemanticModel, Table
from pbi_agent.llm.client import LLMClient
from pbi_agent.logging import get_logger

log = get_logger("model_inspector")


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Finding:
    """A single inspection finding."""
    severity: Severity
    category: str
    message: str
    table: str = ""
    object_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "severity": self.severity.value,
            "category": self.category,
            "message": self.message,
        }
        if self.table:
            d["table"] = self.table
        if self.object_name:
            d["object"] = self.object_name
        return d


@dataclass
class InspectionResult:
    """Complete inspection result."""
    success: bool = True
    model_summary: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    llm_analysis: str = ""
    report: str = ""

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.INFO)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "summary": self.model_summary,
            "findings": [f.to_dict() for f in self.findings],
            "counts": {
                "errors": self.error_count,
                "warnings": self.warning_count,
                "info": self.info_count,
            },
            "llm_analysis": self.llm_analysis,
            "report": self.report,
        }


class ModelInspector:
    """Inspects Power BI semantic model structure from TMDL files.

    Two-phase inspection:
    1. Rule-based checks (no LLM needed) — fast, deterministic
    2. LLM analysis (optional) — deeper semantic review
    """

    def __init__(self, config: InspectorConfig, llm: LLMClient | None = None):
        self.config = config
        self.llm = llm
        self.parser = TMDLParser()

    def inspect(self, pbip_path: str, use_llm: bool = True) -> dict[str, Any]:
        """Full inspection of a PBIP project.

        Args:
            pbip_path: Path to the .pbip project folder.
            use_llm: Whether to run LLM-based analysis (requires API key).

        Returns:
            Dict with model summary, findings, and analysis report.
        """
        log.info(f"Inspecting model at: {pbip_path}")

        # Parse TMDL
        model = self.parser.parse_project(pbip_path)
        if model.table_count == 0:
            return {
                "success": False,
                "report": f"No tables found in {pbip_path}. Is this a valid PBIP project?",
            }

        result = InspectionResult(
            model_summary=model.to_summary_dict(),
        )

        # Phase 1: Rule-based checks
        self._check_documentation(model, result)
        self._check_relationships(model, result)
        self._check_date_table(model, result)
        self._check_measures(model, result)
        self._check_columns(model, result)
        self._check_roles(model, result)
        self._check_naming(model, result)

        # Phase 2: LLM analysis (optional)
        if use_llm and self.llm:
            try:
                result.llm_analysis = self._llm_analyze(model, result)
            except Exception as e:
                log.warning(f"LLM analysis failed: {e}")
                result.llm_analysis = f"LLM analysis unavailable: {e}"

        # Build human-readable report
        result.report = self._build_report(model, result)

        log.info(
            f"Inspection complete: {result.error_count} errors, "
            f"{result.warning_count} warnings, {result.info_count} info"
        )
        return result.to_dict()

    # ── Rule-based checks ────────────────────────────────────────────────

    def _check_documentation(self, model: SemanticModel, result: InspectionResult):
        """Check for undocumented columns and measures."""
        if not self.config.flag_undocumented:
            return

        for table in model.tables:
            undoc_cols = table.undocumented_columns
            if undoc_cols:
                result.findings.append(Finding(
                    severity=Severity.WARNING,
                    category="documentation",
                    message=f"{len(undoc_cols)} undocumented column(s): {', '.join(c.name for c in undoc_cols[:5])}",
                    table=table.name,
                ))

            undoc_measures = table.undocumented_measures
            if undoc_measures:
                result.findings.append(Finding(
                    severity=Severity.WARNING,
                    category="documentation",
                    message=f"{len(undoc_measures)} undocumented measure(s): {', '.join(m.name for m in undoc_measures)}",
                    table=table.name,
                ))

    def _check_relationships(self, model: SemanticModel, result: InspectionResult):
        """Validate relationships."""
        if model.relationship_count == 0 and model.table_count > 1:
            result.findings.append(Finding(
                severity=Severity.ERROR,
                category="relationships",
                message="No relationships defined between tables. Model may not work correctly.",
            ))
            return

        # Check for tables with no relationships (islands)
        tables_in_rels = set()
        for r in model.relationships:
            tables_in_rels.add(r.from_table)
            tables_in_rels.add(r.to_table)

        for table in model.tables:
            if table.name not in tables_in_rels and model.table_count > 1:
                result.findings.append(Finding(
                    severity=Severity.WARNING,
                    category="relationships",
                    message=f"Table has no relationships (isolated island)",
                    table=table.name,
                ))

        # Check for missing relationship targets
        table_names = {t.name for t in model.tables}
        for r in model.relationships:
            if r.from_table not in table_names:
                result.findings.append(Finding(
                    severity=Severity.ERROR,
                    category="relationships",
                    message=f"Relationship references missing table: {r.from_table}",
                    object_name=r.name,
                ))
            if r.to_table not in table_names:
                result.findings.append(Finding(
                    severity=Severity.ERROR,
                    category="relationships",
                    message=f"Relationship references missing table: {r.to_table}",
                    object_name=r.name,
                ))

            # Check column existence
            from_table = model.get_table(r.from_table)
            if from_table:
                col_names = {c.name for c in from_table.columns}
                if r.from_column not in col_names:
                    result.findings.append(Finding(
                        severity=Severity.ERROR,
                        category="relationships",
                        message=f"Relationship column {r.from_column} not found in {r.from_table}",
                        object_name=r.name,
                    ))

            to_table = model.get_table(r.to_table)
            if to_table:
                col_names = {c.name for c in to_table.columns}
                if r.to_column not in col_names:
                    result.findings.append(Finding(
                        severity=Severity.ERROR,
                        category="relationships",
                        message=f"Relationship column {r.to_column} not found in {r.to_table}",
                        object_name=r.name,
                    ))

    def _check_date_table(self, model: SemanticModel, result: InspectionResult):
        """Check for a proper date table."""
        date_tables = [t for t in model.tables if t.data_category == "Time"]

        if not date_tables:
            # Check if any table looks like a date table
            possible = [t for t in model.tables if any(
                kw in t.name.lower() for kw in ["date", "calendar", "time"]
            )]
            if possible:
                result.findings.append(Finding(
                    severity=Severity.WARNING,
                    category="date_table",
                    message=f"Table '{possible[0].name}' looks like a date table but "
                            f"dataCategory is not set to 'Time'. Mark it to enable time intelligence.",
                    table=possible[0].name,
                ))
            else:
                result.findings.append(Finding(
                    severity=Severity.WARNING,
                    category="date_table",
                    message="No date table found. Time intelligence functions (YTD, QTD, etc.) "
                            "require a table with dataCategory: Time.",
                ))
            return

        for dt in date_tables:
            # Check for a key column
            has_key = any(c.is_key for c in dt.columns)
            if not has_key:
                result.findings.append(Finding(
                    severity=Severity.WARNING,
                    category="date_table",
                    message="Date table has no key column marked (isKey: true).",
                    table=dt.name,
                ))

            # Check for hierarchy
            if not dt.hierarchies:
                result.findings.append(Finding(
                    severity=Severity.INFO,
                    category="date_table",
                    message="Date table has no hierarchy. Consider adding Year > Quarter > Month.",
                    table=dt.name,
                ))

    def _check_measures(self, model: SemanticModel, result: InspectionResult):
        """Validate measures."""
        all_measure_names = set()
        for table in model.tables:
            for m in table.measures:
                # Check for duplicates
                if m.name in all_measure_names:
                    result.findings.append(Finding(
                        severity=Severity.ERROR,
                        category="measures",
                        message=f"Duplicate measure name: {m.name}",
                        table=table.name,
                        object_name=m.name,
                    ))
                all_measure_names.add(m.name)

                # Check for empty expressions
                if not m.expression.strip():
                    result.findings.append(Finding(
                        severity=Severity.ERROR,
                        category="measures",
                        message="Measure has no expression",
                        table=table.name,
                        object_name=m.name,
                    ))

                # Check for missing format strings
                if not m.format_string:
                    result.findings.append(Finding(
                        severity=Severity.INFO,
                        category="measures",
                        message="Measure has no format string",
                        table=table.name,
                        object_name=m.name,
                    ))

                # Check for measures not in display folders
                if not m.display_folder:
                    result.findings.append(Finding(
                        severity=Severity.INFO,
                        category="measures",
                        message="Measure is not organized in a display folder",
                        table=table.name,
                        object_name=m.name,
                    ))

    def _check_columns(self, model: SemanticModel, result: InspectionResult):
        """Check column quality."""
        for table in model.tables:
            # Check for columns with summarizeBy: sum that might be IDs
            for col in table.columns:
                if col.summarize_by == "sum" and any(
                    kw in col.name.lower() for kw in ["id", "key", "code", "number"]
                ):
                    result.findings.append(Finding(
                        severity=Severity.WARNING,
                        category="columns",
                        message=f"Column '{col.name}' looks like an ID but has summarizeBy: sum. "
                                f"Consider setting to 'none'.",
                        table=table.name,
                        object_name=col.name,
                    ))

    def _check_roles(self, model: SemanticModel, result: InspectionResult):
        """Validate RLS roles."""
        for role in model.roles:
            if not role.table_permissions:
                result.findings.append(Finding(
                    severity=Severity.WARNING,
                    category="security",
                    message=f"Role '{role.name}' has no table permissions defined.",
                ))

            for perm in role.table_permissions:
                # Check if filtered table exists
                if not model.get_table(perm.table):
                    result.findings.append(Finding(
                        severity=Severity.ERROR,
                        category="security",
                        message=f"Role '{role.name}' filters on non-existent table: {perm.table}",
                    ))

                if not perm.filter_expression.strip():
                    result.findings.append(Finding(
                        severity=Severity.WARNING,
                        category="security",
                        message=f"Role '{role.name}' has empty filter on table {perm.table}",
                    ))

    def _check_naming(self, model: SemanticModel, result: InspectionResult):
        """Check naming conventions."""
        for table in model.tables:
            # Flag tables with spaces or special characters (info only)
            if " " in table.name and not table.name.startswith("'"):
                result.findings.append(Finding(
                    severity=Severity.INFO,
                    category="naming",
                    message="Table name contains spaces. Consider using PascalCase.",
                    table=table.name,
                ))

    # ── LLM Analysis ─────────────────────────────────────────────────────

    def _llm_analyze(self, model: SemanticModel, result: InspectionResult) -> str:
        """Use Claude to perform deeper semantic analysis."""
        summary = model.to_summary_dict()
        findings_so_far = [f.to_dict() for f in result.findings]

        system_prompt = """You are an expert Power BI semantic model reviewer. You analyze TMDL models
for best practices, performance issues, and design quality.

Review the model and provide:
1. Overall model health score (1-10)
2. Key strengths of the model
3. Top recommendations for improvement (prioritized)
4. Any DAX measure patterns that could be optimized
5. Relationship design assessment

Be specific and actionable. Reference actual table/column/measure names.
Keep the response concise — under 500 words."""

        user_message = f"""Analyze this Power BI semantic model:

MODEL STRUCTURE:
{json.dumps(summary, indent=2)}

RULE-BASED FINDINGS ALREADY IDENTIFIED:
{json.dumps(findings_so_far, indent=2)}

Provide your analysis focusing on areas the rule-based checks may have missed."""

        return self.llm.analyze(system_prompt, user_message)

    # ── Report Builder ───────────────────────────────────────────────────

    def _build_report(self, model: SemanticModel, result: InspectionResult) -> str:
        """Build a human-readable inspection report."""
        lines = []
        lines.append("=" * 60)
        lines.append("SEMANTIC MODEL INSPECTION REPORT")
        lines.append("=" * 60)

        # Summary
        lines.append(f"\nModel: {model.source_path}")
        lines.append(f"Culture: {model.model_info.culture}")
        lines.append(f"Tables: {model.table_count}")
        lines.append(f"Total columns: {model.total_columns}")
        lines.append(f"Total measures: {model.total_measures}")
        lines.append(f"Relationships: {model.relationship_count}")
        lines.append(f"Roles: {model.role_count}")

        # Findings summary
        lines.append(f"\n--- Findings ---")
        lines.append(f"Errors: {result.error_count}")
        lines.append(f"Warnings: {result.warning_count}")
        lines.append(f"Info: {result.info_count}")

        # Group findings by category
        if result.findings:
            categories = {}
            for f in result.findings:
                categories.setdefault(f.category, []).append(f)

            for cat, findings in sorted(categories.items()):
                lines.append(f"\n[{cat.upper()}]")
                for f in findings:
                    icon = {"error": "X", "warning": "!", "info": "i"}[f.severity.value]
                    location = f" ({f.table}" + (f".{f.object_name}" if f.object_name else "") + ")" if f.table else ""
                    lines.append(f"  [{icon}]{location} {f.message}")

        # LLM analysis
        if result.llm_analysis:
            lines.append(f"\n--- AI Analysis ---")
            lines.append(result.llm_analysis)

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def inspect_offline(self, pbip_path: str) -> dict[str, Any]:
        """Run inspection without LLM (rule-based only)."""
        return self.inspect(pbip_path, use_llm=False)
