"""Report Review Engine — validates report definitions, visuals, and health."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pbi_agent.config import ReviewerConfig
from pbi_agent.inspector.tmdl_parser import (
    TMDLParser, ReportParser, SemanticModel, ReportDefinition, ReportPage, Visual,
)
from pbi_agent.llm.client import LLMClient
from pbi_agent.logging import get_logger

log = get_logger("report_reviewer")


@dataclass
class ReviewFinding:
    severity: str  # "error", "warning", "info"
    category: str
    message: str
    page: str = ""
    visual: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {"severity": self.severity, "category": self.category, "message": self.message}
        if self.page:
            d["page"] = self.page
        if self.visual:
            d["visual"] = self.visual
        return d


@dataclass
class ReviewResult:
    success: bool = True
    report_summary: dict[str, Any] = field(default_factory=dict)
    model_summary: dict[str, Any] = field(default_factory=dict)
    findings: list[ReviewFinding] = field(default_factory=list)
    llm_analysis: str = ""
    report: str = ""

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "report_summary": self.report_summary,
            "findings": [f.to_dict() for f in self.findings],
            "counts": {
                "errors": self.error_count,
                "warnings": self.warning_count,
                "info": sum(1 for f in self.findings if f.severity == "info"),
            },
            "llm_analysis": self.llm_analysis,
            "report": self.report,
        }


class ReportReviewer:
    """Reviews Power BI report definitions for quality and completeness.

    Checks:
    - Page count and structure
    - Visual types and coverage
    - Measure/column references (cross-validated against semantic model)
    - Filter presence
    - Layout and sizing
    - Best practices
    """

    def __init__(self, config: ReviewerConfig, llm: LLMClient | None = None):
        self.config = config
        self.llm = llm
        self.tmdl_parser = TMDLParser()
        self.report_parser = ReportParser()

    def review(self, pbip_path: str, use_llm: bool = True) -> dict[str, Any]:
        """Full review of a PBIP project's report.

        Args:
            pbip_path: Path to the .pbip project folder.
            use_llm: Whether to run LLM-based analysis.

        Returns:
            Dict with report summary, findings, and analysis.
        """
        log.info(f"Reviewing report at: {pbip_path}")

        # Parse report
        report_def = self.report_parser.parse_report(pbip_path)
        if not report_def:
            return {
                "success": False,
                "report": f"No report definition found in {pbip_path}.",
            }

        # Parse semantic model (for cross-validation)
        model = self.tmdl_parser.parse_project(pbip_path)

        result = ReviewResult(
            report_summary=report_def.to_summary_dict(),
            model_summary=model.to_summary_dict() if model.table_count > 0 else {},
        )

        # Run checks
        self._check_pages(report_def, result)
        self._check_visuals(report_def, result)
        self._check_references(report_def, model, result)
        self._check_filters(report_def, result)
        self._check_layout(report_def, result)
        self._check_best_practices(report_def, model, result)

        # LLM analysis
        if use_llm and self.llm:
            try:
                result.llm_analysis = self._llm_analyze(report_def, model, result)
            except Exception as e:
                log.warning(f"LLM analysis failed: {e}")
                result.llm_analysis = f"LLM analysis unavailable: {e}"

        result.report = self._build_report(report_def, result)

        log.info(
            f"Review complete: {result.error_count} errors, {result.warning_count} warnings"
        )
        return result.to_dict()

    # ── Checks ───────────────────────────────────────────────────────────

    def _check_pages(self, report: ReportDefinition, result: ReviewResult):
        """Validate page count and structure."""
        if report.page_count == 0:
            result.findings.append(ReviewFinding(
                severity="error", category="pages",
                message="Report has no pages.",
            ))
            return

        if report.page_count < self.config.min_pages:
            result.findings.append(ReviewFinding(
                severity="warning", category="pages",
                message=f"Report has {report.page_count} page(s), minimum recommended is {self.config.min_pages}.",
            ))

        # Check for empty pages
        for page in report.pages:
            if not page.visuals:
                result.findings.append(ReviewFinding(
                    severity="warning", category="pages",
                    message="Page has no visuals.",
                    page=page.display_name or page.name,
                ))

        # Check for duplicate page names
        names = [p.display_name or p.name for p in report.pages]
        seen = set()
        for name in names:
            if name in seen:
                result.findings.append(ReviewFinding(
                    severity="warning", category="pages",
                    message=f"Duplicate page name: '{name}'",
                ))
            seen.add(name)

    def _check_visuals(self, report: ReportDefinition, result: ReviewResult):
        """Validate visual types and configurations."""
        if not self.config.validate_visuals:
            return

        for page in report.pages:
            visual_types = [v.visual_type for v in page.visuals]
            page_name = page.display_name or page.name

            # Check for too many visuals on one page
            if len(page.visuals) > 15:
                result.findings.append(ReviewFinding(
                    severity="warning", category="visuals",
                    message=f"Page has {len(page.visuals)} visuals. Consider splitting for readability.",
                    page=page_name,
                ))

            # Check for visuals without a type
            for v in page.visuals:
                if not v.visual_type:
                    result.findings.append(ReviewFinding(
                        severity="warning", category="visuals",
                        message=f"Visual '{v.name}' has no visual type defined.",
                        page=page_name, visual=v.name,
                    ))

                # Check for visuals with no data projections
                if not v.projections or all(len(refs) == 0 for refs in v.projections.values()):
                    result.findings.append(ReviewFinding(
                        severity="warning", category="visuals",
                        message=f"Visual '{v.name}' has no data fields assigned.",
                        page=page_name, visual=v.name,
                    ))

    def _check_references(self, report: ReportDefinition, model: SemanticModel, result: ReviewResult):
        """Cross-validate report references against the semantic model."""
        if model.table_count == 0:
            result.findings.append(ReviewFinding(
                severity="info", category="references",
                message="No semantic model available for cross-validation.",
            ))
            return

        # Build lookup of valid references
        valid_refs = set()
        for table in model.tables:
            for col in table.columns:
                valid_refs.add(f"{table.name}.{col.name}")
            for measure in table.measures:
                valid_refs.add(f"{table.name}.{measure.name}")

        # Check all visual projections
        for page in report.pages:
            page_name = page.display_name or page.name
            for visual in page.visuals:
                for role, refs in visual.projections.items():
                    for ref in refs:
                        if ref and ref not in valid_refs:
                            result.findings.append(ReviewFinding(
                                severity="warning", category="references",
                                message=f"Visual references '{ref}' which is not in the semantic model.",
                                page=page_name, visual=visual.name,
                            ))

        # Check for unused measures (defined but never referenced in report)
        referenced = set()
        for page in report.pages:
            for visual in page.visuals:
                for refs in visual.projections.values():
                    referenced.update(refs)

        for table in model.tables:
            for measure in table.measures:
                full_ref = f"{table.name}.{measure.name}"
                if full_ref not in referenced:
                    result.findings.append(ReviewFinding(
                        severity="info", category="references",
                        message=f"Measure '{measure.name}' is defined but not used in any visual.",
                    ))

    def _check_filters(self, report: ReportDefinition, result: ReviewResult):
        """Check filter configuration."""
        if not self.config.check_filters:
            return

        pages_without_filters = []
        for page in report.pages:
            if not page.filters:
                pages_without_filters.append(page.display_name or page.name)

        if pages_without_filters and len(pages_without_filters) == report.page_count:
            result.findings.append(ReviewFinding(
                severity="info", category="filters",
                message="No pages have filters configured. Consider adding slicers or report-level filters.",
            ))
        elif pages_without_filters:
            for pname in pages_without_filters:
                result.findings.append(ReviewFinding(
                    severity="info", category="filters",
                    message="Page has no filters. Consider adding context filters.",
                    page=pname,
                ))

    def _check_layout(self, report: ReportDefinition, result: ReviewResult):
        """Check visual layout and sizing."""
        for page in report.pages:
            page_name = page.display_name or page.name
            page_width = page.width or 1280
            page_height = page.height or 720

            for v in page.visuals:
                # Check for visuals outside page bounds
                if v.x + v.width > page_width + 10 or v.y + v.height > page_height + 10:
                    result.findings.append(ReviewFinding(
                        severity="warning", category="layout",
                        message=f"Visual '{v.name}' extends beyond page bounds.",
                        page=page_name, visual=v.name,
                    ))

                # Check for very small visuals
                if v.width > 0 and v.height > 0:
                    if v.width < 50 or v.height < 50:
                        result.findings.append(ReviewFinding(
                            severity="info", category="layout",
                            message=f"Visual '{v.name}' is very small ({v.width}x{v.height}px).",
                            page=page_name, visual=v.name,
                        ))

    def _check_best_practices(self, report: ReportDefinition, model: SemanticModel, result: ReviewResult):
        """Check report design best practices."""
        # Check for KPI cards on overview page
        if report.pages:
            first_page = report.pages[0]
            card_count = sum(1 for v in first_page.visuals if v.visual_type in ("card", "multiRowCard", "kpi"))
            if card_count == 0 and first_page.visuals:
                result.findings.append(ReviewFinding(
                    severity="info", category="best_practices",
                    message="First page has no KPI cards. Consider adding summary cards for key metrics.",
                    page=first_page.display_name or first_page.name,
                ))

        # Check visual type variety
        all_types = set()
        for page in report.pages:
            for v in page.visuals:
                if v.visual_type:
                    all_types.add(v.visual_type)

        if len(all_types) == 1 and report.total_visuals > 3:
            result.findings.append(ReviewFinding(
                severity="info", category="best_practices",
                message=f"All visuals use the same type ('{next(iter(all_types))}'). "
                        f"Consider using different visual types for variety.",
            ))

    # ── LLM Analysis ─────────────────────────────────────────────────────

    def _llm_analyze(self, report: ReportDefinition, model: SemanticModel, result: ReviewResult) -> str:
        """Use Claude for deeper report analysis."""
        system_prompt = """You are an expert Power BI report reviewer. Analyze the report structure
and provide actionable feedback on:
1. Overall report quality score (1-10)
2. User experience assessment (navigation, visual hierarchy, storytelling)
3. Data coverage (are the right metrics shown?)
4. Missing visuals or pages that would improve the report
5. Specific improvements for each page

Be concise — under 400 words. Reference actual page/visual names."""

        user_message = f"""Review this Power BI report:

REPORT STRUCTURE:
{json.dumps(report.to_summary_dict(), indent=2)}

SEMANTIC MODEL (available data):
{json.dumps(model.to_summary_dict(), indent=2)}

ISSUES ALREADY FOUND:
{json.dumps([f.to_dict() for f in result.findings], indent=2)}"""

        return self.llm.analyze(system_prompt, user_message)

    # ── Report Builder ───────────────────────────────────────────────────

    def _build_report(self, report_def: ReportDefinition, result: ReviewResult) -> str:
        """Build a human-readable review report."""
        lines = []
        lines.append("=" * 60)
        lines.append("REPORT REVIEW")
        lines.append("=" * 60)

        lines.append(f"\nReport: {report_def.name}")
        if report_def.description:
            lines.append(f"Description: {report_def.description}")
        lines.append(f"Pages: {report_def.page_count}")
        lines.append(f"Total visuals: {report_def.total_visuals}")

        for page in report_def.pages:
            pname = page.display_name or page.name
            lines.append(f"\n  Page: {pname}")
            lines.append(f"    Visuals: {len(page.visuals)}")
            lines.append(f"    Filters: {len(page.filters)}")
            for v in page.visuals:
                lines.append(f"      - {v.name} ({v.visual_type})")

        lines.append(f"\n--- Findings ---")
        lines.append(f"Errors: {result.error_count}")
        lines.append(f"Warnings: {result.warning_count}")

        if result.findings:
            categories = {}
            for f in result.findings:
                categories.setdefault(f.category, []).append(f)
            for cat, findings in sorted(categories.items()):
                lines.append(f"\n[{cat.upper()}]")
                for f in findings:
                    icon = {"error": "X", "warning": "!", "info": "i"}[f.severity]
                    loc = ""
                    if f.page:
                        loc = f" ({f.page}"
                        if f.visual:
                            loc += f" > {f.visual}"
                        loc += ")"
                    lines.append(f"  [{icon}]{loc} {f.message}")

        if result.llm_analysis:
            lines.append(f"\n--- AI Analysis ---")
            lines.append(result.llm_analysis)

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def review_offline(self, pbip_path: str) -> dict[str, Any]:
        """Run review without LLM (rule-based only)."""
        return self.review(pbip_path, use_llm=False)
