"""Export Engine — wraps pbi-tools for PBIX export and project packaging."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pbi_agent.config import ExportConfig, PbiToolsConfig
from pbi_agent.inspector.tmdl_parser import TMDLParser, ReportParser
from pbi_agent.logging import get_logger

log = get_logger("export_engine")


@dataclass
class ExportResult:
    success: bool
    export_type: str = ""
    output_path: str = ""
    message: str = ""
    error: str = ""
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "export_type": self.export_type,
            "output_path": self.output_path,
            "message": self.message,
            "error": self.error,
            "artifacts": self.artifacts,
        }


class ExportEngine:
    """Exports PBIP projects using pbi-tools and generates documentation."""

    def __init__(self, export_config: ExportConfig, pbi_tools_config: PbiToolsConfig):
        self.config = export_config
        self.pbi_tools = pbi_tools_config
        self.tmdl_parser = TMDLParser()
        self.report_parser = ReportParser()

    def export(self, pbip_path: str, output_dir: str | None = None) -> dict[str, Any]:
        """Export a PBIP project based on configured format.

        Args:
            pbip_path: Path to the .pbip project folder.
            output_dir: Override output directory (defaults to config).

        Returns:
            Dict with export results.
        """
        fmt = self.config.default_format
        if fmt == "pbix":
            return self.export_pbix(pbip_path, output_dir).to_dict()
        elif fmt == "pbip":
            return self.export_pbip_package(pbip_path, output_dir).to_dict()
        else:
            return ExportResult(
                success=False,
                error=f"Unknown export format: {fmt}. Use 'pbix' or 'pbip'.",
            ).to_dict()

    def export_pbix(self, pbip_path: str, output_dir: str | None = None) -> ExportResult:
        """Compile PBIP project to PBIX using pbi-tools.

        Requires pbi-tools >= 1.0.0-rc.3 with TMDL support.
        """
        pbip_path = Path(pbip_path)
        out_dir = Path(output_dir or self.pbi_tools.export_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Find the .pbip manifest file
        pbip_file = self._find_pbip_file(pbip_path)
        if not pbip_file:
            return ExportResult(
                success=False, export_type="pbix",
                error=f"No .pbip file found in {pbip_path}",
            )

        # Check pbi-tools availability
        if not self._check_pbi_tools():
            return ExportResult(
                success=False, export_type="pbix",
                error=f"pbi-tools not found at '{self.pbi_tools.path}'. "
                      f"Install from https://pbi.tools/ or update PBI_TOOLS_PATH in .env",
            )

        output_pbix = out_dir / f"{pbip_path.name.replace('.pbip', '')}.pbix"

        log.info(f"Compiling {pbip_file} -> {output_pbix}")

        try:
            cmd = [
                self.pbi_tools.path, "compile",
                str(pbip_file),
                "-outPath", str(output_pbix),
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.pbi_tools.timeout,
                cwd=str(pbip_path),
            )

            if proc.returncode == 0:
                result = ExportResult(
                    success=True, export_type="pbix",
                    output_path=str(output_pbix),
                    message=f"PBIX exported to: {output_pbix}",
                    artifacts=[str(output_pbix)],
                )
                log.info(f"PBIX export successful: {output_pbix}")
            else:
                error_msg = proc.stderr.strip() or proc.stdout.strip() or "Unknown error"
                result = ExportResult(
                    success=False, export_type="pbix",
                    error=f"pbi-tools compile failed: {error_msg}",
                )
                log.error(f"PBIX export failed: {error_msg}")

        except subprocess.TimeoutExpired:
            result = ExportResult(
                success=False, export_type="pbix",
                error=f"pbi-tools compile timed out after {self.pbi_tools.timeout}s",
            )
        except FileNotFoundError:
            result = ExportResult(
                success=False, export_type="pbix",
                error=f"pbi-tools executable not found: {self.pbi_tools.path}",
            )

        return result

    def export_pbip_package(self, pbip_path: str, output_dir: str | None = None) -> ExportResult:
        """Package PBIP project with documentation for handoff.

        Creates a self-contained folder with:
        - Copy of the PBIP project
        - Model documentation (JSON summary)
        - Report documentation (JSON summary)
        - README with setup instructions
        """
        pbip_path = Path(pbip_path)
        out_dir = Path(output_dir or self.pbi_tools.export_dir)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        package_name = f"{pbip_path.name.replace('.pbip', '')}_package_{timestamp}"
        package_dir = out_dir / package_name
        package_dir.mkdir(parents=True, exist_ok=True)

        artifacts = []
        log.info(f"Creating package at: {package_dir}")

        # Copy PBIP project
        project_copy = package_dir / "project"
        try:
            shutil.copytree(pbip_path, project_copy)
            artifacts.append(str(project_copy))
        except Exception as e:
            return ExportResult(
                success=False, export_type="pbip_package",
                error=f"Failed to copy project: {e}",
            )

        # Generate model documentation
        if self.config.include_docs:
            model = self.tmdl_parser.parse_project(pbip_path)
            if model.table_count > 0:
                model_doc = package_dir / "model_summary.json"
                with open(model_doc, "w", encoding="utf-8") as f:
                    json.dump(model.to_summary_dict(), f, indent=2)
                artifacts.append(str(model_doc))

            report = self.report_parser.parse_report(pbip_path)
            if report:
                report_doc = package_dir / "report_summary.json"
                with open(report_doc, "w", encoding="utf-8") as f:
                    json.dump(report.to_summary_dict(), f, indent=2)
                artifacts.append(str(report_doc))

            # Generate README
            readme = self._generate_package_readme(pbip_path, model, report)
            readme_path = package_dir / "README.md"
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(readme)
            artifacts.append(str(readme_path))

        return ExportResult(
            success=True, export_type="pbip_package",
            output_path=str(package_dir),
            message=f"Package created at: {package_dir} ({len(artifacts)} artifacts)",
            artifacts=artifacts,
        )

    def extract_to_tmdl(self, pbix_path: str, output_dir: str | None = None) -> ExportResult:
        """Extract a PBIX file to TMDL format using pbi-tools.

        Useful for importing existing PBIX files into the agent workflow.
        """
        pbix_path = Path(pbix_path)
        if not pbix_path.exists():
            return ExportResult(
                success=False, export_type="extract",
                error=f"PBIX file not found: {pbix_path}",
            )

        if not self._check_pbi_tools():
            return ExportResult(
                success=False, export_type="extract",
                error="pbi-tools not available.",
            )

        out_dir = Path(output_dir or self.pbi_tools.export_dir) / pbix_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"Extracting {pbix_path} -> {out_dir}")

        try:
            cmd = [
                self.pbi_tools.path, "extract",
                str(pbix_path),
                "-extractDir", str(out_dir),
                "-modelSerialization", "Tmdl",
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.pbi_tools.timeout,
            )

            if proc.returncode == 0:
                return ExportResult(
                    success=True, export_type="extract",
                    output_path=str(out_dir),
                    message=f"Extracted TMDL to: {out_dir}",
                    artifacts=[str(out_dir)],
                )
            else:
                return ExportResult(
                    success=False, export_type="extract",
                    error=f"pbi-tools extract failed: {proc.stderr.strip() or proc.stdout.strip()}",
                )
        except subprocess.TimeoutExpired:
            return ExportResult(
                success=False, export_type="extract",
                error=f"Extraction timed out after {self.pbi_tools.timeout}s",
            )

    def _check_pbi_tools(self) -> bool:
        """Check if pbi-tools is available."""
        try:
            proc = subprocess.run(
                [self.pbi_tools.path, "info"],
                capture_output=True, text=True, timeout=10,
            )
            return proc.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _find_pbip_file(self, pbip_path: Path) -> Path | None:
        """Find the .pbip manifest file in the project directory."""
        for f in pbip_path.iterdir():
            if f.suffix == ".pbip" and f.is_file():
                return f
        return None

    def _generate_package_readme(self, pbip_path, model, report) -> str:
        """Generate README for the export package."""
        lines = [
            f"# {pbip_path.name.replace('.pbip', '')} — Export Package",
            "",
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Contents",
            "",
            "- `project/` — Full PBIP project (open in Power BI Desktop with Developer Mode)",
            "- `model_summary.json` — Semantic model documentation",
            "- `report_summary.json` — Report structure documentation",
            "",
            "## Model Summary",
            "",
        ]

        if model and model.table_count > 0:
            lines.append(f"- Tables: {model.table_count}")
            lines.append(f"- Columns: {model.total_columns}")
            lines.append(f"- Measures: {model.total_measures}")
            lines.append(f"- Relationships: {model.relationship_count}")
            lines.append(f"- Roles: {model.role_count}")
            lines.append("")
            lines.append("### Tables")
            lines.append("")
            for t in model.tables:
                lines.append(f"- **{t.name}**: {t.column_count} columns, {t.measure_count} measures")

        if report:
            lines.append("")
            lines.append("## Report Summary")
            lines.append("")
            lines.append(f"- Pages: {report.page_count}")
            lines.append(f"- Total visuals: {report.total_visuals}")
            for p in report.pages:
                pname = p.display_name or p.name
                lines.append(f"  - {pname}: {len(p.visuals)} visuals")

        lines.extend([
            "",
            "## Setup",
            "",
            "1. Install Power BI Desktop (latest version)",
            "2. Enable Developer Mode in Options > Preview features",
            "3. Open `project/<name>.pbip`",
            "4. Update data source connections as needed",
        ])

        return "\n".join(lines)
