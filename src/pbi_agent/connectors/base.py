"""Connection Manager — routes to the appropriate data source connector."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pbi_agent.config import ConnectorConfig
from pbi_agent.connectors.csv_connector import FileConnector
from pbi_agent.connectors.sql_connector import SQLConnector
from pbi_agent.logging import get_logger

log = get_logger("connection_manager")


class ConnectionManager:
    """Manages connections to supported data sources."""

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self._file_connector: FileConnector | None = None
        self._sql_connector: SQLConnector | None = None
        self._last_file_result = None
        self._last_sql_result = None

    @property
    def file_connector(self) -> FileConnector:
        if self._file_connector is None:
            self._file_connector = FileConnector(
                max_file_size_mb=self.config.csv_max_file_size_mb
            )
        return self._file_connector

    @property
    def sql_connector(self) -> SQLConnector:
        if self._sql_connector is None:
            self._sql_connector = SQLConnector(self.config)
        return self._sql_connector

    def connect(self, user_message: str) -> dict[str, Any]:
        """Parse user intent and connect to the appropriate source."""
        msg = user_message.lower()

        # Check for file path in the message
        path = self._extract_path(user_message)

        if path and Path(path).exists():
            return self.connect_file(path)
        elif any(ext in msg for ext in [".csv", ".tsv", ".xlsx", ".xls", "excel", "spreadsheet"]):
            if path:
                return self.connect_file(path)
            return {"success": False, "error": "Please provide the file path."}
        elif any(kw in msg for kw in ["sql", "server", "database", "azure"]):
            return self.connect_sql()
        else:
            return {
                "success": False,
                "error": "Could not determine data source type. "
                         "Please mention a file path (CSV/Excel) or SQL Server.",
            }

    def connect_file(self, path: str) -> dict[str, Any]:
        """Connect to a file or directory of files."""
        log.info(f"Connecting to file: {path}")
        result = self.file_connector.connect(path)
        self._last_file_result = result

        if not result.success:
            return {"success": False, "error": result.error}

        output = result.to_dict()
        # Format a human-readable summary
        table_summaries = []
        for t in result.tables:
            table_summaries.append(
                f"  - {t.name}: {t.row_count:,} rows, {t.column_count} columns ({t.file_type})"
            )
        output["summary"] = (
            f"Connected to {result.table_count} file(s):\n" +
            "\n".join(table_summaries)
        )
        return output

    def connect_sql(self) -> dict[str, Any]:
        """Connect to SQL Server using configured credentials."""
        if not self.config.sql_database:
            return {
                "success": False,
                "error": "SQL Server not configured. Set SQL_SERVER_* variables in .env file.",
            }

        log.info(f"Connecting to SQL Server: {self.config.sql_host}/{self.config.sql_database}")
        result = self.sql_connector.connect()
        self._last_sql_result = result

        if not result.success:
            return {"success": False, "error": result.error}

        output = result.to_dict()
        table_summaries = []
        for t in result.tables:
            table_summaries.append(
                f"  - {t.full_name}: {t.row_count:,} rows, {t.column_count} columns ({t.table_type})"
            )
        output["summary"] = (
            f"Connected to {result.database} on {result.server}:\n"
            f"{result.table_count} tables/views, {len(result.foreign_keys)} foreign keys\n" +
            "\n".join(table_summaries[:20])  # Limit to first 20
        )
        if result.table_count > 20:
            output["summary"] += f"\n  ... and {result.table_count - 20} more"

        return output

    def _extract_path(self, message: str) -> str | None:
        """Try to extract a file/directory path from the user message."""
        # Match common path patterns
        patterns = [
            r'[A-Z]:\\[\w\\.\-\s]+',           # Windows: C:\path\to\file.csv
            r'/[\w/.\-]+',                       # Unix: /path/to/file.csv
            r'\.[\\/][\w\\/.+\-]+',              # Relative: ./data/file.csv
            r'[\w\-]+\.(?:csv|tsv|xlsx|xls)',    # Just filename: data.csv
        ]
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return match.group(0).strip()
        return None

    @property
    def last_file_result(self):
        """The most recent raw FileConnectionResult (with full column metadata), or None."""
        return self._last_file_result

    def get_metadata_for_llm(self) -> dict[str, Any]:
        """Get combined metadata from all connections for LLM analysis."""
        metadata = {"sources": []}
        if self._last_file_result and self._last_file_result.success:
            metadata["sources"].append(self._last_file_result.to_dict())
        if self._last_sql_result and self._last_sql_result.success:
            metadata["sources"].append(self._last_sql_result.to_dict())
        return metadata
