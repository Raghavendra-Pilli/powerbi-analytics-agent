"""Central orchestrator — routes user requests to the right module."""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pbi_agent.config import AgentConfig
from pbi_agent.llm.client import LLMClient
from pbi_agent.logging import get_logger

log = get_logger("orchestrator")


class WorkflowState(Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    INSPECTING = "inspecting"
    REVIEWING = "reviewing"
    EXPORTING = "exporting"
    SCAFFOLDING = "scaffolding"
    REMEDIATING = "remediating"


@dataclass
class SessionContext:
    """Tracks state across a user session."""
    state: WorkflowState = WorkflowState.IDLE
    connected_source: dict[str, Any] | None = None
    model_summary: dict[str, Any] | None = None
    review_results: dict[str, Any] | None = None
    messages: list[dict] = field(default_factory=list)
    pbip_path: str | None = None


class Orchestrator:
    """Routes user intent to the appropriate handler module."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.llm = LLMClient(config.llm)
        self.session = SessionContext()

        # Lazy-loaded modules (initialized on first use)
        self._connection_manager = None
        self._model_inspector = None
        self._report_reviewer = None
        self._export_engine = None
        self._pbip_scaffolder = None
        self._model_fixer = None

    @property
    def connection_manager(self):
        if self._connection_manager is None:
            from pbi_agent.connectors import ConnectionManager
            self._connection_manager = ConnectionManager(self.config.connectors)
        return self._connection_manager

    @property
    def model_inspector(self):
        if self._model_inspector is None:
            from pbi_agent.inspector import ModelInspector
            self._model_inspector = ModelInspector(self.config.inspector, self.llm)
        return self._model_inspector

    @property
    def report_reviewer(self):
        if self._report_reviewer is None:
            from pbi_agent.reviewer import ReportReviewer
            self._report_reviewer = ReportReviewer(self.config.reviewer, self.llm)
        return self._report_reviewer

    @property
    def export_engine(self):
        if self._export_engine is None:
            from pbi_agent.export import ExportEngine
            self._export_engine = ExportEngine(self.config.export, self.config.pbi_tools)
        return self._export_engine

    @property
    def pbip_scaffolder(self):
        if self._pbip_scaffolder is None:
            from pbi_agent.export.pbip_scaffolder import PbipScaffolder
            self._pbip_scaffolder = PbipScaffolder()
        return self._pbip_scaffolder

    @property
    def model_fixer(self):
        if self._model_fixer is None:
            from pbi_agent.remediate.model_fixer import ModelFixer
            self._model_fixer = ModelFixer(self.llm)
        return self._model_fixer

    def process(self, user_message: str) -> str:
        """Process a user message and return a response."""
        log.info(f"Processing: {user_message[:80]}...")

        # Track conversation
        self.session.messages.append({"role": "user", "content": user_message})

        # Route intent
        intent = self.llm.route(user_message)

        try:
            match intent:
                case "CONNECT":
                    response = self._handle_connect(user_message)
                case "SUMMARIZE":
                    response = self._handle_summarize(user_message)
                case "INSPECT":
                    response = self._handle_inspect(user_message)
                case "REVIEW":
                    response = self._handle_review(user_message)
                case "SCAFFOLD":
                    response = self._handle_scaffold(user_message)
                case "REMEDIATE":
                    response = self._handle_remediate(user_message)
                case "EXPORT":
                    response = self._handle_export(user_message)
                case "HELP" | _:
                    response = self._handle_help(user_message)
        except Exception as e:
            log.error(f"Error handling {intent}: {e}")
            response = f"Error during {intent.lower()}: {str(e)}"

        self.session.messages.append({"role": "assistant", "content": response})
        return response

    def _handle_connect(self, message: str) -> str:
        self.session.state = WorkflowState.CONNECTING
        result = self.connection_manager.connect(message)
        if result.get("success"):
            self.session.connected_source = result
            self.session.state = WorkflowState.IDLE
            return (
                f"Connected to {result['source_type']}: {result['name']}\n"
                f"Found {result.get('table_count', '?')} tables.\n"
                "You can now inspect the model, review reports, ask me to summarize the data, "
                "or ask me to create a PBIP project from it."
            )
        return f"Connection failed: {result.get('error', 'Unknown error')}"

    def _handle_summarize(self, message: str) -> str:
        """Summarize whatever data source is currently connected, or the loaded PBIP model."""
        metadata = self.connection_manager.get_metadata_for_llm()
        has_file_data = bool(metadata.get("sources"))

        if not has_file_data and not self.session.pbip_path:
            return (
                "Nothing is connected yet, so I don't have any data to summarize. "
                "Connect to a CSV/Excel file or load a PBIP project first."
            )

        if has_file_data:
            system = (
                "You are a data analyst. You will be given metadata extracted from a connected "
                "CSV/Excel file (table names, columns, data types, sample values, null/unique "
                "counts). Write a plain-language summary covering: what the data appears to be "
                "about (what), what columns/fields describe (who/what entities), the likely "
                "purpose or business use of this data (why), row/column counts, and anything "
                "notable (missing values, obvious key columns, date ranges). "
                "Only describe what is actually present in the metadata — do not invent facts."
            )
            user_msg = f"Connected data metadata:\n{json.dumps(metadata, indent=2, default=str)}"
            return self.llm.analyze(system, user_msg)

        # Fall back to summarizing the loaded PBIP semantic model
        summary = self.model_inspector.inspect(self.session.pbip_path, use_llm=False)
        system = (
            "You are a data analyst. Summarize this Power BI semantic model in plain language: "
            "what the model appears to represent, the key tables and what each contains, and "
            "the overall purpose. Only describe what is in the provided structure."
        )
        user_msg = f"Semantic model structure:\n{json.dumps(summary.get('summary', {}), indent=2, default=str)}"
        return self.llm.analyze(system, user_msg)

    def _handle_inspect(self, message: str) -> str:
        self.session.state = WorkflowState.INSPECTING
        if not self.session.pbip_path:
            return (
                "No PBIP project loaded. Please provide the path to your .pbip project folder "
                "in the sidebar first."
            )
        summary = self.model_inspector.inspect(self.session.pbip_path)
        self.session.model_summary = summary
        self.session.state = WorkflowState.IDLE
        return summary.get("report", "Inspection complete. No issues found.")

    def _handle_review(self, message: str) -> str:
        self.session.state = WorkflowState.REVIEWING
        if not self.session.pbip_path:
            return "No PBIP project loaded. Please provide the path first."
        results = self.report_reviewer.review(self.session.pbip_path)
        self.session.review_results = results
        self.session.state = WorkflowState.IDLE
        return results.get("report", "Review complete.")

    def _handle_scaffold(self, message: str) -> str:
        """Generate a new starter PBIP project from the currently connected CSV/Excel file."""
        self.session.state = WorkflowState.SCAFFOLDING
        file_result = self.connection_manager.last_file_result

        if not file_result or not file_result.success:
            self.session.state = WorkflowState.IDLE
            return (
                "No connected CSV/Excel file to build a PBIP project from. "
                "Connect to a file first, e.g. \"Connect to C:\\path\\to\\data.xlsx\", "
                "then ask me to create the PBIP project."
            )

        result = self.pbip_scaffolder.scaffold(file_result, output_dir=".")
        self.session.state = WorkflowState.IDLE

        if not result.success:
            return f"Could not create the PBIP project: {result.error}"

        lines = [result.message]
        for w in result.warnings:
            lines.append(f"Note: {w}")
        return "\n".join(lines)

    def _handle_remediate(self, message: str) -> str:
        """Fix model gaps (DAX, date table) and report a before/after health score.

        Always writes to a safe copy in the web UI — never modifies your original
        project files. Use the CLI's --in-place flag if you explicitly want that.
        """
        self.session.state = WorkflowState.REMEDIATING
        if not self.session.pbip_path:
            self.session.state = WorkflowState.IDLE
            return "No PBIP project loaded. Please provide the path in the sidebar first."

        result = self.model_fixer.remediate(self.session.pbip_path, output_dir=None, in_place=False)
        self.session.state = WorkflowState.IDLE

        if not result.success:
            return f"Could not fix the model: {result.error}"

        lines = [
            f"Before: {result.before_score}",
            f"After:  {result.after_score}",
            "",
            "Changes made:",
        ]
        for c in result.changes:
            lines.append(f"  - [{c.category}] {c.description}")
        lines.append("")
        lines.append(f"Fixed project written to: {result.output_path}")
        lines.append(
            "Dashboard page specification (not auto-injected into report.json — "
            "see the tool's notes on why) is included below:"
        )
        lines.append("")
        lines.append(result.dashboard_spec)
        return "\n".join(lines)

    def _handle_export(self, message: str) -> str:
        self.session.state = WorkflowState.EXPORTING
        if not self.session.pbip_path:
            return "No PBIP project loaded. Please provide the path first."
        result = self.export_engine.export(self.session.pbip_path)
        self.session.state = WorkflowState.IDLE
        return result.get("message", "Export complete.")

    def _handle_help(self, message: str) -> str:
        system = (
            "You are a helpful Power BI analytics assistant. You help users:\n"
            "1. Connect to data sources (CSV, Excel, SQL Server)\n"
            "2. Summarize connected data in plain language\n"
            "3. Inspect Power BI semantic models (TMDL/PBIP)\n"
            "4. Review report health and quality\n"
            "5. Create a new starter PBIP project from a connected CSV/Excel file\n"
            "6. Export PBIX files using pbi-tools\n\n"
            "Be concise and practical. If the user seems lost, suggest the next step."
        )
        return self.llm.analyze(system, message)

    def set_pbip_path(self, path: str) -> str:
        """Set the PBIP project path for inspection/review/export."""
        path = path.strip().strip('"').strip("'")
        self.session.pbip_path = path
        log.info(f"PBIP path set: {path}")
        return f"PBIP project loaded: {path}"
