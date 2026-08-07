"""Tests for the CSV/Excel file connector."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pbi_agent.connectors.csv_connector import FileConnector


SAMPLE_CSV_DIR = Path(__file__).parent / "sample_data" / "csv"
SALES_CSV = SAMPLE_CSV_DIR / "sales.csv"


class TestFileConnector:

    def setup_method(self):
        self.connector = FileConnector(max_file_size_mb=500)

    def test_connect_single_csv(self):
        result = self.connector.connect(SALES_CSV)
        assert result.success
        assert result.table_count == 1
        t = result.tables[0]
        assert t.name == "sales"
        assert t.row_count == 20
        assert t.column_count == 7
        assert t.file_type == "csv"

    def test_connect_directory(self):
        result = self.connector.connect(SAMPLE_CSV_DIR)
        assert result.success
        assert result.table_count == 3
        names = [t.name for t in result.tables]
        assert "sales" in names
        assert "products" in names
        assert "customers" in names

    def test_column_metadata(self):
        result = self.connector.connect(SALES_CSV)
        t = result.tables[0]
        col_map = {c.name: c for c in t.columns}

        assert col_map["OrderID"].dtype == "int64"
        assert col_map["OrderDate"].dtype == "dateTime"
        assert col_map["UnitPrice"].dtype == "double"
        assert col_map["OrderID"].unique_count == 20
        assert col_map["OrderID"].null_count == 0

    def test_nonexistent_path(self):
        result = self.connector.connect("/nonexistent/path.csv")
        assert not result.success
        assert "does not exist" in result.error

    def test_unsupported_extension(self):
        result = self.connector.connect("test.json")
        assert not result.success

    def test_to_dict(self):
        result = self.connector.connect(SALES_CSV)
        d = result.to_dict()
        assert d["success"] is True
        assert d["table_count"] == 1
        assert len(d["tables"]) == 1
        assert len(d["tables"][0]["columns"]) == 7

    def test_load_dataframe(self):
        df = self.connector.load_dataframe(SALES_CSV)
        assert len(df) == 20
        assert "OrderID" in df.columns


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
