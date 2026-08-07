"""Tests for the TMDL and Report parsers."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pbi_agent.inspector.tmdl_parser import TMDLParser, ReportParser


SAMPLE_PBIP = Path(__file__).parent / "sample_data" / "SalesAnalytics.pbip"


class TestTMDLParser:
    """Test TMDL semantic model parsing."""

    def setup_method(self):
        self.parser = TMDLParser()
        self.model = self.parser.parse_project(SAMPLE_PBIP)

    def test_model_parsed(self):
        assert self.model is not None
        assert self.model.model_info.culture == "en-US"

    def test_table_count(self):
        assert self.model.table_count == 4
        table_names = [t.name for t in self.model.tables]
        assert "Sales" in table_names
        assert "Products" in table_names
        assert "Customers" in table_names
        assert "DateTable" in table_names

    def test_sales_table_columns(self):
        sales = self.model.get_table("Sales")
        assert sales is not None
        assert sales.column_count == 7
        col_names = [c.name for c in sales.columns]
        assert "OrderID" in col_names
        assert "Quantity" in col_names
        assert "UnitPrice" in col_names

    def test_sales_table_measures(self):
        sales = self.model.get_table("Sales")
        assert sales is not None
        assert sales.measure_count == 4
        measure_names = [m.name for m in sales.measures]
        assert "Total Revenue" in measure_names
        assert "Order Count" in measure_names
        assert "Average Order Value" in measure_names
        assert "YoY Growth %" in measure_names

    def test_measure_expressions(self):
        sales = self.model.get_table("Sales")
        revenue = next(m for m in sales.measures if m.name == "Total Revenue")
        assert "SUMX" in revenue.expression
        assert revenue.format_string == "$#,0.00"
        assert revenue.display_folder == "Revenue"
        assert revenue.has_description

    def test_measure_without_description(self):
        sales = self.model.get_table("Sales")
        order_count = next(m for m in sales.measures if m.name == "Order Count")
        assert not order_count.has_description

    def test_column_data_types(self):
        sales = self.model.get_table("Sales")
        order_id = next(c for c in sales.columns if c.name == "OrderID")
        assert order_id.data_type == "int64"
        unit_price = next(c for c in sales.columns if c.name == "UnitPrice")
        assert unit_price.data_type == "decimal"

    def test_date_table_hierarchy(self):
        dt = self.model.get_table("DateTable")
        assert dt is not None
        assert len(dt.hierarchies) == 1
        h = dt.hierarchies[0]
        assert h.name == "Date Hierarchy"
        assert len(h.levels) == 3
        assert h.levels[0].name == "Year"
        assert h.levels[1].name == "Quarter"
        assert h.levels[2].name == "Month"

    def test_date_table_data_category(self):
        dt = self.model.get_table("DateTable")
        assert dt.data_category == "Time"

    def test_hidden_column(self):
        dt = self.model.get_table("DateTable")
        month_num = next(c for c in dt.columns if c.name == "MonthNumber")
        assert month_num.is_hidden

    def test_key_column(self):
        dt = self.model.get_table("DateTable")
        date_col = next(c for c in dt.columns if c.name == "Date")
        assert date_col.is_key

    def test_sort_by_column(self):
        dt = self.model.get_table("DateTable")
        month = next(c for c in dt.columns if c.name == "Month")
        assert month.sort_by_column == "MonthNumber"

    def test_relationships(self):
        assert self.model.relationship_count == 3
        rel_pairs = [
            (r.from_table, r.from_column, r.to_table, r.to_column)
            for r in self.model.relationships
        ]
        assert ("Sales", "ProductID", "Products", "ProductID") in rel_pairs
        assert ("Sales", "CustomerID", "Customers", "CustomerID") in rel_pairs
        assert ("Sales", "OrderDate", "DateTable", "Date") in rel_pairs

    def test_roles(self):
        assert self.model.role_count == 1
        role = self.model.roles[0]
        assert role.name == "RegionRole"
        assert role.model_permission == "read"
        assert len(role.table_permissions) == 1
        assert role.table_permissions[0].table == "Customers"
        assert "USERNAME()" in role.table_permissions[0].filter_expression

    def test_summary_dict(self):
        summary = self.model.to_summary_dict()
        assert summary["table_count"] == 4
        assert summary["total_measures"] == 4
        assert summary["relationship_count"] == 3
        assert summary["role_count"] == 1
        assert len(summary["tables"]) == 4

    def test_undocumented_columns(self):
        products = self.model.get_table("Products")
        # Only ProductID has a description
        undoc = products.undocumented_columns
        assert len(undoc) == 5  # 6 columns - 1 documented = 5

    def test_partitions(self):
        sales = self.model.get_table("Sales")
        assert len(sales.partitions) >= 1
        p = sales.partitions[0]
        assert p.source_type == "m"
        assert p.mode == "import"


class TestReportParser:
    """Test report definition parsing."""

    def setup_method(self):
        self.parser = ReportParser()
        self.report = self.parser.parse_report(SAMPLE_PBIP)

    def test_report_parsed(self):
        assert self.report is not None
        assert self.report.name == "Sales Analytics"

    def test_page_count(self):
        assert self.report.page_count == 2

    def test_overview_page(self):
        overview = self.report.pages[0]
        assert overview.display_name == "Overview"
        assert len(overview.visuals) == 4
        visual_types = [v.visual_type for v in overview.visuals]
        assert "card" in visual_types
        assert "lineChart" in visual_types
        assert "barChart" in visual_types

    def test_detail_page(self):
        detail = self.report.pages[1]
        assert detail.display_name == "Detail"
        assert len(detail.visuals) == 1
        assert detail.visuals[0].visual_type == "tableEx"

    def test_visual_projections(self):
        overview = self.report.pages[0]
        revenue_card = next(v for v in overview.visuals if v.name == "card_total_revenue")
        assert "Values" in revenue_card.projections
        assert "Sales.Total Revenue" in revenue_card.projections["Values"]

    def test_filters(self):
        overview = self.report.pages[0]
        assert len(overview.filters) == 1

    def test_summary_dict(self):
        summary = self.report.to_summary_dict()
        assert summary["page_count"] == 2
        assert summary["total_visuals"] == 5


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
