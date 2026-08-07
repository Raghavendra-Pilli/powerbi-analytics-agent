"""CSV/Excel file connector — loads flat files into inspectable metadata."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from pbi_agent.logging import get_logger

log = get_logger("csv_connector")


@dataclass
class ColumnMeta:
    """Metadata for a single column."""
    name: str
    dtype: str
    nullable: bool = True
    unique_count: int = 0
    null_count: int = 0
    sample_values: list[str] = field(default_factory=list)
    min_value: str = ""
    max_value: str = ""


@dataclass
class TableMeta:
    """Metadata for a loaded table/file."""
    name: str
    source_path: str
    row_count: int = 0
    columns: list[ColumnMeta] = field(default_factory=list)
    file_size_bytes: int = 0
    file_type: str = ""

    @property
    def column_count(self) -> int:
        return len(self.columns)


@dataclass
class FileConnectionResult:
    """Result of connecting to file(s)."""
    success: bool
    source_type: str = "file"
    name: str = ""
    tables: list[TableMeta] = field(default_factory=list)
    error: str = ""
    message: str = ""

    @property
    def table_count(self) -> int:
        return len(self.tables)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "source_type": self.source_type,
            "name": self.name,
            "table_count": self.table_count,
            "error": self.error,
            "message": self.message,
            "tables": [
                {
                    "name": t.name,
                    "row_count": t.row_count,
                    "column_count": t.column_count,
                    "file_type": t.file_type,
                    "file_size_mb": round(t.file_size_bytes / (1024 * 1024), 2),
                    "columns": [
                        {
                            "name": c.name,
                            "dtype": c.dtype,
                            "unique_count": c.unique_count,
                            "null_count": c.null_count,
                            "sample_values": c.sample_values[:3],
                        }
                        for c in t.columns
                    ],
                }
                for t in self.tables
            ],
        }


# Mapping pandas dtypes to Power BI-friendly type names
DTYPE_MAP = {
    "int64": "int64",
    "int32": "int64",
    "float64": "double",
    "float32": "double",
    "object": "string",
    "bool": "boolean",
    "datetime64[ns]": "dateTime",
    "datetime64": "dateTime",
    "category": "string",
}


class FileConnector:
    """Connects to CSV, TSV, and Excel files, extracts metadata."""

    SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls"}

    def __init__(self, max_file_size_mb: int = 500):
        self.max_file_size_mb = max_file_size_mb

    def connect(self, path: str | Path) -> FileConnectionResult:
        """Connect to a file or directory of files.

        Args:
            path: Path to a single file or a directory containing supported files.

        Returns:
            FileConnectionResult with metadata for all loaded tables.
        """
        path = Path(path)

        if not path.exists():
            return FileConnectionResult(
                success=False,
                error=f"Path does not exist: {path}",
            )

        files: list[Path] = []
        if path.is_file():
            if path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                files = [path]
            else:
                return FileConnectionResult(
                    success=False,
                    error=f"Unsupported file type: {path.suffix}. "
                          f"Supported: {', '.join(self.SUPPORTED_EXTENSIONS)}",
                )
        elif path.is_dir():
            files = [
                f for f in path.iterdir()
                if f.is_file() and f.suffix.lower() in self.SUPPORTED_EXTENSIONS
            ]
            if not files:
                return FileConnectionResult(
                    success=False,
                    error=f"No supported files found in: {path}",
                )
        files.sort(key=lambda f: f.name)

        result = FileConnectionResult(
            success=True,
            name=path.name,
        )

        for file_path in files:
            try:
                table = self._load_file(file_path)
                result.tables.append(table)
                log.info(f"Loaded {file_path.name}: {table.row_count} rows, {table.column_count} cols")
            except Exception as e:
                log.error(f"Failed to load {file_path.name}: {e}")
                result.tables.append(TableMeta(
                    name=file_path.stem,
                    source_path=str(file_path),
                ))

        result.message = f"Loaded {result.table_count} file(s) from {path.name}"
        return result

    def _load_file(self, path: Path) -> TableMeta:
        """Load a single file and extract its metadata."""
        file_size = path.stat().st_size
        if file_size > self.max_file_size_mb * 1024 * 1024:
            raise ValueError(
                f"File too large: {file_size / (1024*1024):.1f}MB "
                f"(max {self.max_file_size_mb}MB)"
            )

        ext = path.suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(path, low_memory=False)
        elif ext == ".tsv":
            df = pd.read_csv(path, sep="\t", low_memory=False)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(path, engine="openpyxl" if ext == ".xlsx" else None)
        else:
            raise ValueError(f"Unsupported extension: {ext}")

        columns = []
        for col_name in df.columns:
            series = df[col_name]
            dtype_str = str(series.dtype)
            pbi_type = DTYPE_MAP.get(dtype_str, "string")

            # Try to detect dates stored as strings
            if dtype_str == "object" and series.dropna().shape[0] > 0:
                sample = series.dropna().head(5)
                try:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        pd.to_datetime(sample, format="mixed")
                    pbi_type = "dateTime"
                except (ValueError, TypeError):
                    pass

            # Get sample values
            non_null = series.dropna()
            samples = [str(v) for v in non_null.head(5).tolist()]

            # Min/max for numeric/date columns
            min_val = ""
            max_val = ""
            if pd.api.types.is_numeric_dtype(series):
                min_val = str(series.min()) if not series.isna().all() else ""
                max_val = str(series.max()) if not series.isna().all() else ""
            elif pd.api.types.is_datetime64_any_dtype(series):
                min_val = str(series.min()) if not series.isna().all() else ""
                max_val = str(series.max()) if not series.isna().all() else ""

            columns.append(ColumnMeta(
                name=str(col_name),
                dtype=pbi_type,
                nullable=bool(series.isna().any()),
                unique_count=int(series.nunique()),
                null_count=int(series.isna().sum()),
                sample_values=samples,
                min_value=min_val,
                max_value=max_val,
            ))

        return TableMeta(
            name=path.stem,
            source_path=str(path),
            row_count=len(df),
            columns=columns,
            file_size_bytes=file_size,
            file_type=ext.lstrip("."),
        )

    def load_dataframe(self, path: str | Path) -> pd.DataFrame:
        """Load a file and return the pandas DataFrame (for downstream use)."""
        path = Path(path)
        ext = path.suffix.lower()
        if ext == ".csv":
            return pd.read_csv(path, low_memory=False)
        elif ext == ".tsv":
            return pd.read_csv(path, sep="\t", low_memory=False)
        elif ext in (".xlsx", ".xls"):
            return pd.read_excel(path, engine="openpyxl" if ext == ".xlsx" else None)
        raise ValueError(f"Unsupported: {ext}")
