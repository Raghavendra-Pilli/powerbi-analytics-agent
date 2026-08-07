"""Configuration loader for the Power BI Analytics Agent."""

from pathlib import Path
from dataclasses import dataclass, field
import yaml
from dotenv import load_dotenv
import os


@dataclass
class LLMConfig:
    router_model: str = "claude-haiku-4-5-20251001"
    analysis_model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.0
    api_key: str = ""


@dataclass
class PbiToolsConfig:
    path: str = "pbi-tools"
    export_dir: str = "./exports"
    timeout: int = 120


@dataclass
class ConnectorConfig:
    csv_enabled: bool = True
    csv_max_file_size_mb: int = 500
    csv_extensions: list[str] = field(default_factory=lambda: [".csv", ".tsv", ".xlsx", ".xls"])
    sql_enabled: bool = True
    sql_host: str = "localhost"
    sql_port: int = 1433
    sql_database: str = ""
    sql_user: str = ""
    sql_password: str = ""
    sql_driver: str = "ODBC Driver 18 for SQL Server"
    sql_connection_timeout: int = 30
    sql_query_timeout: int = 120


@dataclass
class InspectorConfig:
    max_tables_detail: int = 50
    flag_undocumented: bool = True
    check_unused_columns: bool = True


@dataclass
class ReviewerConfig:
    min_pages: int = 1
    check_filters: bool = True
    validate_visuals: bool = True


@dataclass
class ExportConfig:
    default_format: str = "pbip"
    include_docs: bool = True
    tableau_handoff: bool = False


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "structured"
    file: str = "logs/agent.log"
    console: bool = True


@dataclass
class AgentConfig:
    """Top-level configuration container."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    pbi_tools: PbiToolsConfig = field(default_factory=PbiToolsConfig)
    connectors: ConnectorConfig = field(default_factory=ConnectorConfig)
    inspector: InspectorConfig = field(default_factory=InspectorConfig)
    reviewer: ReviewerConfig = field(default_factory=ReviewerConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(
    config_path: str | Path = "config/settings.yaml",
    env_path: str | Path = ".env",
) -> AgentConfig:
    """Load configuration from YAML + environment variables."""
    load_dotenv(env_path)

    config = AgentConfig()

    # Load YAML if it exists
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r") as f:
            raw = yaml.safe_load(f) or {}

        # LLM
        llm = raw.get("llm", {})
        config.llm.router_model = llm.get("router_model", config.llm.router_model)
        config.llm.analysis_model = llm.get("analysis_model", config.llm.analysis_model)
        config.llm.max_tokens = llm.get("max_tokens", config.llm.max_tokens)
        config.llm.temperature = llm.get("temperature", config.llm.temperature)

        # pbi-tools
        pbi = raw.get("pbi_tools", {})
        config.pbi_tools.path = pbi.get("path", config.pbi_tools.path)
        config.pbi_tools.export_dir = pbi.get("export_dir", config.pbi_tools.export_dir)
        config.pbi_tools.timeout = pbi.get("timeout", config.pbi_tools.timeout)

        # Connectors
        conn = raw.get("connectors", {})
        csv_conf = conn.get("csv", {})
        config.connectors.csv_enabled = csv_conf.get("enabled", config.connectors.csv_enabled)
        config.connectors.csv_max_file_size_mb = csv_conf.get(
            "max_file_size_mb", config.connectors.csv_max_file_size_mb
        )
        sql_conf = conn.get("sql_server", {})
        config.connectors.sql_enabled = sql_conf.get("enabled", config.connectors.sql_enabled)

        # Inspector
        insp = raw.get("inspector", {})
        config.inspector.max_tables_detail = insp.get(
            "max_tables_detail", config.inspector.max_tables_detail
        )
        config.inspector.flag_undocumented = insp.get(
            "flag_undocumented", config.inspector.flag_undocumented
        )

        # Reviewer
        rev = raw.get("reviewer", {})
        config.reviewer.min_pages = rev.get("min_pages", config.reviewer.min_pages)
        config.reviewer.check_filters = rev.get("check_filters", config.reviewer.check_filters)

        # Export
        exp = raw.get("export", {})
        config.export.default_format = exp.get("default_format", config.export.default_format)
        config.export.include_docs = exp.get("include_docs", config.export.include_docs)
        config.export.tableau_handoff = exp.get("tableau_handoff", config.export.tableau_handoff)

        # Logging
        log = raw.get("logging", {})
        config.logging.level = log.get("level", config.logging.level)
        config.logging.file = log.get("file", config.logging.file)
        config.logging.console = log.get("console", config.logging.console)

    # Override with environment variables
    config.llm.api_key = os.getenv("ANTHROPIC_API_KEY", "")
    config.connectors.sql_host = os.getenv("SQL_SERVER_HOST", config.connectors.sql_host)
    config.connectors.sql_port = int(os.getenv("SQL_SERVER_PORT", str(config.connectors.sql_port)))
    config.connectors.sql_database = os.getenv("SQL_SERVER_DATABASE", "")
    config.connectors.sql_user = os.getenv("SQL_SERVER_USER", "")
    config.connectors.sql_password = os.getenv("SQL_SERVER_PASSWORD", "")
    config.connectors.sql_driver = os.getenv("SQL_SERVER_DRIVER", config.connectors.sql_driver)
    config.pbi_tools.path = os.getenv("PBI_TOOLS_PATH", config.pbi_tools.path)
    config.logging.level = os.getenv("LOG_LEVEL", config.logging.level)

    return config
