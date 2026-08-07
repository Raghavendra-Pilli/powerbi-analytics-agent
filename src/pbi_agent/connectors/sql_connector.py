"""SQL Server / Azure SQL connector — connects and extracts schema metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pbi_agent.config import ConnectorConfig
from pbi_agent.logging import get_logger

log = get_logger("sql_connector")


@dataclass
class SQLColumnMeta:
    """Metadata for a SQL Server column."""
    name: str
    data_type: str
    max_length: int = -1
    is_nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    default_value: str = ""


@dataclass
class SQLTableMeta:
    """Metadata for a SQL Server table."""
    schema_name: str
    table_name: str
    table_type: str = "BASE TABLE"  # or VIEW
    row_count: int = 0
    columns: list[SQLColumnMeta] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"

    @property
    def column_count(self) -> int:
        return len(self.columns)


@dataclass
class SQLForeignKey:
    """Foreign key relationship between tables."""
    name: str
    from_schema: str
    from_table: str
    from_column: str
    to_schema: str
    to_table: str
    to_column: str


@dataclass
class SQLConnectionResult:
    """Result of connecting to SQL Server."""
    success: bool
    source_type: str = "sql_server"
    name: str = ""
    server: str = ""
    database: str = ""
    tables: list[SQLTableMeta] = field(default_factory=list)
    foreign_keys: list[SQLForeignKey] = field(default_factory=list)
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
            "server": self.server,
            "database": self.database,
            "table_count": self.table_count,
            "error": self.error,
            "message": self.message,
            "tables": [
                {
                    "full_name": t.full_name,
                    "table_type": t.table_type,
                    "row_count": t.row_count,
                    "column_count": t.column_count,
                    "columns": [
                        {
                            "name": c.name,
                            "data_type": c.data_type,
                            "is_nullable": c.is_nullable,
                            "is_primary_key": c.is_primary_key,
                        }
                        for c in t.columns
                    ],
                }
                for t in self.tables
            ],
            "foreign_keys": [
                {
                    "name": fk.name,
                    "from": f"{fk.from_schema}.{fk.from_table}.{fk.from_column}",
                    "to": f"{fk.to_schema}.{fk.to_table}.{fk.to_column}",
                }
                for fk in self.foreign_keys
            ],
        }


# SQL Server type → Power BI type mapping
SQL_TYPE_MAP = {
    "int": "int64",
    "bigint": "int64",
    "smallint": "int64",
    "tinyint": "int64",
    "bit": "boolean",
    "decimal": "decimal",
    "numeric": "decimal",
    "money": "decimal",
    "smallmoney": "decimal",
    "float": "double",
    "real": "double",
    "char": "string",
    "varchar": "string",
    "nchar": "string",
    "nvarchar": "string",
    "text": "string",
    "ntext": "string",
    "date": "dateTime",
    "datetime": "dateTime",
    "datetime2": "dateTime",
    "smalldatetime": "dateTime",
    "time": "dateTime",
    "datetimeoffset": "dateTime",
    "uniqueidentifier": "string",
    "xml": "string",
    "binary": "binary",
    "varbinary": "binary",
    "image": "binary",
}


class SQLConnector:
    """Connects to SQL Server / Azure SQL and extracts schema metadata."""

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self._connection = None
        self._engine = None

    def connect(self) -> SQLConnectionResult:
        """Connect to SQL Server and discover the schema."""
        try:
            import pyodbc
        except ImportError:
            return SQLConnectionResult(
                success=False,
                error="pyodbc not installed. Run: pip install pyodbc",
            )

        conn_str = (
            f"DRIVER={{{self.config.sql_driver}}};"
            f"SERVER={self.config.sql_host},{self.config.sql_port};"
            f"DATABASE={self.config.sql_database};"
            f"UID={self.config.sql_user};"
            f"PWD={self.config.sql_password};"
            f"TrustServerCertificate=yes;"
            f"Connection Timeout={self.config.sql_connection_timeout};"
        )

        try:
            log.info(f"Connecting to {self.config.sql_host}:{self.config.sql_port}/{self.config.sql_database}")
            self._connection = pyodbc.connect(conn_str, timeout=self.config.sql_connection_timeout)
            cursor = self._connection.cursor()

            result = SQLConnectionResult(
                success=True,
                name=self.config.sql_database,
                server=self.config.sql_host,
                database=self.config.sql_database,
            )

            # Discover tables and views
            result.tables = self._discover_tables(cursor)

            # Discover foreign keys
            result.foreign_keys = self._discover_foreign_keys(cursor)

            result.message = (
                f"Connected to {self.config.sql_database}: "
                f"{result.table_count} tables/views, "
                f"{len(result.foreign_keys)} foreign keys"
            )
            log.info(result.message)
            return result

        except pyodbc.Error as e:
            error_msg = str(e)
            log.error(f"SQL connection failed: {error_msg}")
            return SQLConnectionResult(
                success=False,
                error=f"Connection failed: {error_msg}",
            )

    def _discover_tables(self, cursor) -> list[SQLTableMeta]:
        """Discover all user tables and views with their columns."""
        tables = []

        # Get tables and views
        cursor.execute("""
            SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')
            ORDER BY TABLE_SCHEMA, TABLE_NAME
        """)
        table_rows = cursor.fetchall()

        for schema, table_name, table_type in table_rows:
            table = SQLTableMeta(
                schema_name=schema,
                table_name=table_name,
                table_type=table_type,
            )

            # Get row count (skip for views)
            if table_type == "BASE TABLE":
                try:
                    cursor.execute(f"""
                        SELECT SUM(p.rows)
                        FROM sys.partitions p
                        JOIN sys.tables t ON p.object_id = t.object_id
                        JOIN sys.schemas s ON t.schema_id = s.schema_id
                        WHERE s.name = ? AND t.name = ? AND p.index_id IN (0, 1)
                    """, schema, table_name)
                    row = cursor.fetchone()
                    table.row_count = int(row[0]) if row and row[0] else 0
                except Exception:
                    pass

            # Get columns
            cursor.execute("""
                SELECT
                    c.COLUMN_NAME,
                    c.DATA_TYPE,
                    c.CHARACTER_MAXIMUM_LENGTH,
                    c.IS_NULLABLE,
                    c.COLUMN_DEFAULT
                FROM INFORMATION_SCHEMA.COLUMNS c
                WHERE c.TABLE_SCHEMA = ? AND c.TABLE_NAME = ?
                ORDER BY c.ORDINAL_POSITION
            """, schema, table_name)

            for col_name, data_type, max_len, is_nullable, default_val in cursor.fetchall():
                table.columns.append(SQLColumnMeta(
                    name=col_name,
                    data_type=SQL_TYPE_MAP.get(data_type.lower(), data_type),
                    max_length=max_len or -1,
                    is_nullable=(is_nullable == "YES"),
                    default_value=str(default_val) if default_val else "",
                ))

            # Mark primary key columns
            try:
                cursor.execute("""
                    SELECT ccu.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu
                        ON tc.CONSTRAINT_NAME = ccu.CONSTRAINT_NAME
                    WHERE tc.TABLE_SCHEMA = ? AND tc.TABLE_NAME = ?
                        AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                """, schema, table_name)
                pk_cols = {row[0] for row in cursor.fetchall()}
                for col in table.columns:
                    if col.name in pk_cols:
                        col.is_primary_key = True
            except Exception:
                pass

            tables.append(table)

        return tables

    def _discover_foreign_keys(self, cursor) -> list[SQLForeignKey]:
        """Discover all foreign key relationships."""
        foreign_keys = []
        try:
            cursor.execute("""
                SELECT
                    fk.name AS fk_name,
                    s1.name AS from_schema,
                    t1.name AS from_table,
                    c1.name AS from_column,
                    s2.name AS to_schema,
                    t2.name AS to_table,
                    c2.name AS to_column
                FROM sys.foreign_key_columns fkc
                JOIN sys.foreign_keys fk ON fkc.constraint_object_id = fk.object_id
                JOIN sys.tables t1 ON fkc.parent_object_id = t1.object_id
                JOIN sys.schemas s1 ON t1.schema_id = s1.schema_id
                JOIN sys.columns c1 ON fkc.parent_object_id = c1.object_id
                    AND fkc.parent_column_id = c1.column_id
                JOIN sys.tables t2 ON fkc.referenced_object_id = t2.object_id
                JOIN sys.schemas s2 ON t2.schema_id = s2.schema_id
                JOIN sys.columns c2 ON fkc.referenced_object_id = c2.object_id
                    AND fkc.referenced_column_id = c2.column_id
                ORDER BY fk.name
            """)
            for fk_name, fs, ft, fc, ts, tt, tc in cursor.fetchall():
                foreign_keys.append(SQLForeignKey(
                    name=fk_name,
                    from_schema=fs, from_table=ft, from_column=fc,
                    to_schema=ts, to_table=tt, to_column=tc,
                ))
        except Exception as e:
            log.warning(f"Could not discover foreign keys: {e}")

        return foreign_keys

    def execute_query(self, query: str) -> list[dict[str, Any]]:
        """Execute a read-only query and return results as list of dicts."""
        if not self._connection:
            raise RuntimeError("Not connected. Call connect() first.")

        # Basic safety check — block writes
        dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "EXEC", "EXECUTE"]
        query_upper = query.strip().upper()
        if any(query_upper.startswith(d) for d in dangerous):
            raise ValueError(f"Write operations are not allowed. Query starts with a blocked keyword.")

        cursor = self._connection.cursor()
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def close(self):
        """Close the SQL connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
            log.info("SQL connection closed")
