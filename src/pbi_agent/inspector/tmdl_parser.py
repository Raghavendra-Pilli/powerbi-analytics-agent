"""TMDL Parser — reads PBIP/TMDL files into structured Python objects.

Parses the folder-based TMDL format used by Power BI Developer Mode:
  definition/
    model.tmdl
    relationships.tmdl
    tables/<TableName>/definition.tmdl
    roles/<RoleName>.tmdl
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pbi_agent.logging import get_logger

log = get_logger("tmdl_parser")


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Column:
    name: str
    data_type: str = ""
    format_string: str = ""
    source_column: str = ""
    description: str = ""
    summarize_by: str = "none"
    is_hidden: bool = False
    is_key: bool = False
    sort_by_column: str = ""
    lineage_tag: str = ""

    @property
    def has_description(self) -> bool:
        return bool(self.description.strip())


@dataclass
class Measure:
    name: str
    expression: str = ""
    format_string: str = ""
    display_folder: str = ""
    description: str = ""
    lineage_tag: str = ""

    @property
    def has_description(self) -> bool:
        return bool(self.description.strip())

    @property
    def referenced_measures(self) -> list[str]:
        """Extract measure references like [Total Revenue] from the expression."""
        return re.findall(r'\[([^\]]+)\]', self.expression)


@dataclass
class HierarchyLevel:
    name: str
    column: str = ""


@dataclass
class Hierarchy:
    name: str
    levels: list[HierarchyLevel] = field(default_factory=list)


@dataclass
class Partition:
    name: str
    mode: str = "import"
    source_type: str = ""  # "m" for Power Query, "calculated", etc.
    expression: str = ""


@dataclass
class Table:
    name: str
    lineage_tag: str = ""
    data_category: str = ""
    columns: list[Column] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    hierarchies: list[Hierarchy] = field(default_factory=list)
    partitions: list[Partition] = field(default_factory=list)

    @property
    def column_count(self) -> int:
        return len(self.columns)

    @property
    def measure_count(self) -> int:
        return len(self.measures)

    @property
    def undocumented_columns(self) -> list[Column]:
        return [c for c in self.columns if not c.has_description]

    @property
    def undocumented_measures(self) -> list[Measure]:
        return [m for m in self.measures if not m.has_description]


@dataclass
class Relationship:
    name: str = ""
    from_table: str = ""
    from_column: str = ""
    to_table: str = ""
    to_column: str = ""
    cross_filtering: str = ""
    is_active: bool = True


@dataclass
class TablePermission:
    table: str = ""
    filter_expression: str = ""


@dataclass
class Role:
    name: str = ""
    model_permission: str = "read"
    description: str = ""
    table_permissions: list[TablePermission] = field(default_factory=list)


@dataclass
class ModelInfo:
    culture: str = ""
    default_source_version: str = ""
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass
class SemanticModel:
    """Complete parsed representation of a TMDL semantic model."""
    model_info: ModelInfo = field(default_factory=ModelInfo)
    tables: list[Table] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    roles: list[Role] = field(default_factory=list)
    source_path: str = ""

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def total_columns(self) -> int:
        return sum(t.column_count for t in self.tables)

    @property
    def total_measures(self) -> int:
        return sum(t.measure_count for t in self.tables)

    @property
    def relationship_count(self) -> int:
        return len(self.relationships)

    @property
    def role_count(self) -> int:
        return len(self.roles)

    def get_table(self, name: str) -> Table | None:
        for t in self.tables:
            if t.name == name:
                return t
        return None

    def to_summary_dict(self) -> dict[str, Any]:
        """Produce a summary dict suitable for LLM analysis."""
        return {
            "culture": self.model_info.culture,
            "table_count": self.table_count,
            "total_columns": self.total_columns,
            "total_measures": self.total_measures,
            "relationship_count": self.relationship_count,
            "role_count": self.role_count,
            "tables": [
                {
                    "name": t.name,
                    "columns": [
                        {"name": c.name, "type": c.data_type, "documented": c.has_description}
                        for c in t.columns
                    ],
                    "measures": [
                        {
                            "name": m.name,
                            "expression": m.expression,
                            "documented": m.has_description,
                            "folder": m.display_folder,
                        }
                        for m in t.measures
                    ],
                    "hierarchies": [h.name for h in t.hierarchies],
                    "data_category": t.data_category,
                }
                for t in self.tables
            ],
            "relationships": [
                {
                    "from": f"{r.from_table}.{r.from_column}",
                    "to": f"{r.to_table}.{r.to_column}",
                    "active": r.is_active,
                }
                for r in self.relationships
            ],
            "roles": [
                {
                    "name": r.name,
                    "permission": r.model_permission,
                    "filters": [
                        {"table": tp.table, "expression": tp.filter_expression}
                        for tp in r.table_permissions
                    ],
                }
                for r in self.roles
            ],
        }


# ── Parser ───────────────────────────────────────────────────────────────────

class TMDLParser:
    """Parses a PBIP project's TMDL files into a SemanticModel."""

    def parse_project(self, pbip_path: str | Path) -> SemanticModel:
        """Parse an entire PBIP project directory.

        Args:
            pbip_path: Path to the .pbip project folder (containing .SemanticModel)

        Returns:
            SemanticModel with all parsed tables, relationships, roles
        """
        pbip_path = Path(pbip_path)
        model = SemanticModel(source_path=str(pbip_path))

        # Find the semantic model directory
        sm_dir = self._find_semantic_model_dir(pbip_path)
        if not sm_dir:
            log.error(f"No SemanticModel directory found in {pbip_path}")
            return model

        definition_dir = sm_dir / "definition"
        if not definition_dir.exists():
            log.error(f"No definition directory found in {sm_dir}")
            return model

        log.info(f"Parsing TMDL from: {definition_dir}")

        # Parse model.tmdl
        model_file = definition_dir / "model.tmdl"
        if model_file.exists():
            model.model_info = self._parse_model_file(model_file)

        # Parse tables
       # Parse tables. Two known TMDL layouts are supported:
        #   1. Folder-per-table:  tables/<TableName>/definition.tmdl
        #   2. Flat files:        tables/<TableName>.tmdl
        tables_dir = definition_dir / "tables"
        if tables_dir.exists():
            for entry in sorted(tables_dir.iterdir()):
                tmdl_file = None
                if entry.is_dir():
                    candidate = entry / "definition.tmdl"
                    if candidate.exists():
                        tmdl_file = candidate
                elif entry.is_file() and entry.suffix == ".tmdl":
                    tmdl_file = entry

                if tmdl_file:
                    table = self._parse_table_file(tmdl_file)
                    if table.name:
                        model.tables.append(table)
                        log.info(
                            f"  Table '{table.name}': "
                            f"{table.column_count} cols, {table.measure_count} measures"
                        )

        # Parse relationships
        rel_file = definition_dir / "relationships.tmdl"
        if rel_file.exists():
            model.relationships = self._parse_relationships_file(rel_file)
            log.info(f"  Relationships: {len(model.relationships)}")

        # Parse roles
        roles_dir = definition_dir / "roles"
        if roles_dir.exists():
            for role_file in sorted(roles_dir.glob("*.tmdl")):
                role = self._parse_role_file(role_file)
                model.roles.append(role)
            log.info(f"  Roles: {len(model.roles)}")

        log.info(
            f"Parsed model: {model.table_count} tables, "
            f"{model.total_columns} columns, {model.total_measures} measures, "
            f"{model.relationship_count} relationships, {model.role_count} roles"
        )
        return model

    def _find_semantic_model_dir(self, pbip_path: Path) -> Path | None:
        """Find the .SemanticModel directory within the PBIP project."""
        for item in pbip_path.iterdir():
            if item.is_dir() and item.name.endswith(".SemanticModel"):
                return item
        # Also check if pbip_path itself is the semantic model dir
        if pbip_path.name.endswith(".SemanticModel"):
            return pbip_path
        return None

    def _parse_model_file(self, path: Path) -> ModelInfo:
        """Parse model.tmdl for top-level model metadata."""
        info = ModelInfo()
        content = path.read_text(encoding="utf-8")

        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("culture:"):
                info.culture = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("defaultPowerBIDataSourceVersion:"):
                info.default_source_version = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("annotation "):
                match = re.match(r'annotation\s+(\S+)\s*=\s*(.*)', stripped)
                if match:
                    info.annotations[match.group(1)] = match.group(2).strip().strip('"')

        return info

    def _parse_table_file(self, path: Path) -> Table:
        """Parse a table's definition.tmdl file."""
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()

        table = Table(name="")
        current_column: Column | None = None
        current_measure: Measure | None = None
        current_hierarchy: Hierarchy | None = None
        current_partition: Partition | None = None
        current_level: HierarchyLevel | None = None
        in_measure_expr = False
        in_partition_source = False
        measure_expr_lines: list[str] = []
        partition_expr_lines: list[str] = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            indent = len(line) - len(line.lstrip('\t'))

            # Table-level properties (indent 0)
            if indent == 0 and stripped.startswith("table "):
                table.name = stripped[6:].strip().strip("'\"")
                continue

            # Flush measure expression if we've left the measure block
            if in_measure_expr and indent <= 1 and stripped and not stripped.startswith("///"):
                if current_measure and not self._is_measure_property(stripped):
                    # Still in measure — check if it's a continuation
                    pass
                elif current_measure:
                    current_measure.expression = "\n".join(measure_expr_lines).strip()
                    in_measure_expr = False
                    measure_expr_lines = []

            # Flush partition source
            if in_partition_source and indent <= 1 and stripped and not stripped.startswith("///"):
                if current_partition and not self._is_partition_continuation(stripped, indent):
                    current_partition.expression = "\n".join(partition_expr_lines).strip()
                    in_partition_source = False
                    partition_expr_lines = []

            # Table-level attributes (indent 1)
            if indent == 1:
                # Save any pending objects
                if stripped.startswith("column ") or stripped.startswith("measure ") or \
                   stripped.startswith("hierarchy ") or stripped.startswith("partition "):
                    self._flush_current(
                        table, current_column, current_measure,
                        current_hierarchy, current_partition,
                        measure_expr_lines, partition_expr_lines,
                        in_measure_expr, in_partition_source
                    )
                    current_column = None
                    current_measure = None
                    current_hierarchy = None
                    current_partition = None
                    current_level = None
                    in_measure_expr = False
                    in_partition_source = False
                    measure_expr_lines = []
                    partition_expr_lines = []

                if stripped.startswith("lineageTag:"):
                    table.lineage_tag = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("dataCategory:"):
                    table.data_category = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("column "):
                    name = stripped[7:].strip().strip("'\"")
                    current_column = Column(name=name)
                elif stripped.startswith("measure "):
                    # measure 'Name' = expression_start
                    match = re.match(r"measure\s+'([^']+)'\s*=\s*(.*)", stripped)
                    if not match:
                        match = re.match(r"measure\s+(\S+)\s*=\s*(.*)", stripped)
                    if match:
                        current_measure = Measure(name=match.group(1))
                        expr_start = match.group(2).strip()
                        if expr_start:
                            measure_expr_lines.append(expr_start)
                        in_measure_expr = True
                elif stripped.startswith("hierarchy "):
                    name = stripped[10:].strip().strip("'\"")
                    current_hierarchy = Hierarchy(name=name)
                elif stripped.startswith("partition "):
                    match = re.match(r"partition\s+(.+?)\s*=\s*(\w+)", stripped)
                    if match:
                        current_partition = Partition(
                            name=match.group(1).strip(),
                            source_type=match.group(2).strip()
                        )

            # Column/measure/hierarchy properties (indent 2)
            elif indent == 2:
                if current_column:
                    self._parse_column_property(current_column, stripped)
                elif current_measure:
                    if in_measure_expr and not self._is_measure_property(stripped):
                        measure_expr_lines.append(stripped)
                    else:
                        in_measure_expr = False
                        if measure_expr_lines and not current_measure.expression:
                            current_measure.expression = "\n".join(measure_expr_lines).strip()
                            measure_expr_lines = []
                        self._parse_measure_property(current_measure, stripped)
                elif current_hierarchy:
                    if stripped.startswith("level "):
                        name = stripped[6:].strip().strip("'\"")
                        current_level = HierarchyLevel(name=name)
                        current_hierarchy.levels.append(current_level)
                elif current_partition:
                    if stripped.startswith("mode:"):
                        current_partition.mode = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("source"):
                        in_partition_source = True

            # Hierarchy level properties (indent 3)
            elif indent == 3:
                if current_level and stripped.startswith("column:"):
                    current_level.column = stripped.split(":", 1)[1].strip()
                elif in_partition_source and current_partition:
                    partition_expr_lines.append(stripped)

            # Partition source continuation (indent 3+)
            elif indent > 3 and in_partition_source and current_partition:
                partition_expr_lines.append(stripped)

            # Measure expression continuation (indent 2+)
            elif indent >= 2 and in_measure_expr and current_measure:
                measure_expr_lines.append(stripped)

        # Flush remaining
        if in_measure_expr and current_measure and measure_expr_lines:
            current_measure.expression = "\n".join(measure_expr_lines).strip()
        if in_partition_source and current_partition and partition_expr_lines:
            current_partition.expression = "\n".join(partition_expr_lines).strip()

        self._flush_current(
            table, current_column, current_measure,
            current_hierarchy, current_partition,
            [], [], False, False
        )

        return table

    def _flush_current(
        self, table: Table,
        column: Column | None, measure: Measure | None,
        hierarchy: Hierarchy | None, partition: Partition | None,
        measure_expr_lines: list[str], partition_expr_lines: list[str],
        in_measure_expr: bool, in_partition_source: bool,
    ):
        """Add any pending column/measure/hierarchy/partition to the table."""
        if column:
            table.columns.append(column)
        if measure:
            if in_measure_expr and measure_expr_lines and not measure.expression:
                measure.expression = "\n".join(measure_expr_lines).strip()
            table.measures.append(measure)
        if hierarchy:
            table.hierarchies.append(hierarchy)
        if partition:
            if in_partition_source and partition_expr_lines and not partition.expression:
                partition.expression = "\n".join(partition_expr_lines).strip()
            table.partitions.append(partition)

    def _parse_column_property(self, col: Column, line: str):
        """Parse a single column property line."""
        if line.startswith("dataType:"):
            col.data_type = line.split(":", 1)[1].strip()
        elif line.startswith("formatString:"):
            col.format_string = line.split(":", 1)[1].strip()
        elif line.startswith("sourceColumn:"):
            col.source_column = line.split(":", 1)[1].strip()
        elif line.startswith("description:"):
            col.description = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("summarizeBy:"):
            col.summarize_by = line.split(":", 1)[1].strip()
        elif line.startswith("isHidden:"):
            col.is_hidden = line.split(":", 1)[1].strip().lower() == "true"
        elif line.startswith("isKey:"):
            col.is_key = line.split(":", 1)[1].strip().lower() == "true"
        elif line.startswith("sortByColumn:"):
            col.sort_by_column = line.split(":", 1)[1].strip()
        elif line.startswith("lineageTag:"):
            col.lineage_tag = line.split(":", 1)[1].strip()

    def _parse_measure_property(self, measure: Measure, line: str):
        """Parse a single measure property line."""
        if line.startswith("formatString:"):
            measure.format_string = line.split(":", 1)[1].strip()
        elif line.startswith("displayFolder:"):
            measure.display_folder = line.split(":", 1)[1].strip()
        elif line.startswith("description:"):
            measure.description = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("lineageTag:"):
            measure.lineage_tag = line.split(":", 1)[1].strip()

    def _is_measure_property(self, line: str) -> bool:
        """Check if a line is a known measure property (not expression)."""
        props = ["formatString:", "displayFolder:", "description:", "lineageTag:"]
        return any(line.startswith(p) for p in props)

    def _is_partition_continuation(self, line: str, indent: int) -> bool:
        """Check if a line is part of partition definition."""
        return indent >= 2

    def _parse_relationships_file(self, path: Path) -> list[Relationship]:
        """Parse relationships.tmdl."""
        content = path.read_text(encoding="utf-8")
        relationships = []
        current: Relationship | None = None

        for line in content.splitlines():
            stripped = line.strip()
            indent = len(line) - len(line.lstrip('\t'))

            if indent == 0 and stripped.startswith("relationship "):
                if current:
                    relationships.append(current)
                name = stripped[13:].strip()
                current = Relationship(name=name)
            elif indent == 1 and current:
                if stripped.startswith("fromTable:"):
                    current.from_table = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("fromColumn:"):
                    current.from_column = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("toTable:"):
                    current.to_table = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("toColumn:"):
                    current.to_column = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("crossFilteringBehavior:"):
                    current.cross_filtering = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("isActive:"):
                    current.is_active = stripped.split(":", 1)[1].strip().lower() != "false"

        if current:
            relationships.append(current)

        return relationships

    def _parse_role_file(self, path: Path) -> Role:
        """Parse a role .tmdl file."""
        content = path.read_text(encoding="utf-8")
        role = Role()
        current_perm: TablePermission | None = None

        for line in content.splitlines():
            stripped = line.strip()
            indent = len(line) - len(line.lstrip('\t'))

            if indent == 0 and stripped.startswith("role "):
                role.name = stripped[5:].strip().strip("'\"")
            elif indent == 1:
                if stripped.startswith("modelPermission:"):
                    role.model_permission = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("description:"):
                    role.description = stripped.split(":", 1)[1].strip().strip('"')
                elif stripped.startswith("tablePermission "):
                    if current_perm:
                        role.table_permissions.append(current_perm)
                    table_name = stripped[16:].strip()
                    current_perm = TablePermission(table=table_name)
            elif indent == 2 and current_perm:
                if stripped.startswith("filterExpression:"):
                    current_perm.filter_expression = stripped.split(":", 1)[1].strip()

        if current_perm:
            role.table_permissions.append(current_perm)

        return role


# ── Report parser ────────────────────────────────────────────────────────────

@dataclass
class Visual:
    name: str = ""
    visual_type: str = ""
    projections: dict[str, list[str]] = field(default_factory=dict)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


@dataclass
class ReportPage:
    name: str = ""
    display_name: str = ""
    ordinal: int = 0
    width: int = 0
    height: int = 0
    visuals: list[Visual] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)


@dataclass
class ReportDefinition:
    """Parsed report definition."""
    name: str = ""
    description: str = ""
    pages: list[ReportPage] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def total_visuals(self) -> int:
        return sum(len(p.visuals) for p in self.pages)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "page_count": self.page_count,
            "total_visuals": self.total_visuals,
            "pages": [
                {
                    "name": p.display_name or p.name,
                    "visuals": [
                        {"name": v.name, "type": v.visual_type, "projections": v.projections}
                        for v in p.visuals
                    ],
                    "filter_count": len(p.filters),
                }
                for p in self.pages
            ],
        }


class ReportParser:
    """Parses Power BI report definition files."""

    def parse_report(self, pbip_path: str | Path) -> ReportDefinition | None:
        """Parse the report definition from a PBIP project."""
        pbip_path = Path(pbip_path)
        report_def = ReportDefinition(source_path=str(pbip_path))

        # Find the .Report directory
        report_dir = self._find_report_dir(pbip_path)
        if not report_dir:
            log.warning(f"No Report directory found in {pbip_path}")
            return None

        report_json = report_dir / "definition" / "report.json"
        if not report_json.exists():
            log.warning(f"No report.json found at {report_json}")
            return None

        log.info(f"Parsing report from: {report_json}")

        with open(report_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        report_def.name = data.get("name", "")
        report_def.description = data.get("description", "")
        report_def.config = data.get("config", {})

        for section in data.get("sections", []):
            page = ReportPage(
                name=section.get("name", ""),
                display_name=section.get("displayName", ""),
                ordinal=section.get("ordinal", 0),
                width=section.get("width", 0),
                height=section.get("height", 0),
                filters=section.get("filters", []),
            )

            for vc in section.get("visualContainers", []):
                config = vc.get("config", {})
                single_visual = config.get("singleVisual", {})
                projections_raw = single_visual.get("projections", {})

                # Flatten projections to {role: [queryRef, ...]}
                projections: dict[str, list[str]] = {}
                for role, items in projections_raw.items():
                    projections[role] = [
                        item.get("queryRef", "") for item in items if isinstance(item, dict)
                    ]

                visual = Visual(
                    name=config.get("name", ""),
                    visual_type=single_visual.get("visualType", config.get("type", "")),
                    projections=projections,
                    x=vc.get("x", 0),
                    y=vc.get("y", 0),
                    width=vc.get("width", 0),
                    height=vc.get("height", 0),
                )
                page.visuals.append(visual)

            report_def.pages.append(page)

        log.info(
            f"Parsed report '{report_def.name}': "
            f"{report_def.page_count} pages, {report_def.total_visuals} visuals"
        )
        return report_def

    def _find_report_dir(self, pbip_path: Path) -> Path | None:
        """Find the .Report directory within the PBIP project."""
        for item in pbip_path.iterdir():
            if item.is_dir() and item.name.endswith(".Report"):
                return item
        return None
