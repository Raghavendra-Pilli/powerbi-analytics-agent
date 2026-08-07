"""Central orchestrator — routes user requests to the right module."""

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
                case "INSPECT":
                    response = self._handle_inspect(user_message)
                case "REVIEW":
                    response = self._handle_review(user_message)
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
                "You can now inspect the model or review reports."
            )
        return f"Connection failed: {result.get('error', 'Unknown error')}"

    def _handle_inspect(self, message: str) -> str:
        self.session.state = WorkflowState.INSPECTING
        if not self.session.pbip_path:
            return (
                "No PBIP project loaded. Please provide the path to your .pbip project folder, "
                "or connect to a data source first."
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
            "2. Inspect Power BI semantic models (TMDL/PBIP)\n"
            "3. Review report health and quality\n"
            "4. Export PBIX files using pbi-tools\n\n"
            "Be concise and practical. If the user seems lost, suggest the next step."
        )
        return self.llm.analyze(system, message)

    def set_pbip_path(self, path: str) -> str:
        """Set the PBIP project path for inspection/review/export."""
        self.session.pbip_path = path
        log.info(f"PBIP path set: {path}")
        return f"PBIP project loaded: {path}"
