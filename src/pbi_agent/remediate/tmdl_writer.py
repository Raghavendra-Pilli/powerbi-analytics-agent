"""TMDL Writer — serializes parsed Table objects back into valid .tmdl text.

Used by the model remediation feature to write fixed/enriched tables
(new measures, corrected date table flags, filled-in metadata) back to
disk without hand-patching the original file text.
"""

from __future__ import annotations

from pbi_agent.inspector.tmdl_parser import Table, Column, Measure, Hierarchy, Partition

TAB = "\t"


def _quote_if_needed(name: str) -> str:
    """TMDL requires single-quoting identifiers that contain spaces or special chars."""
    if not name:
        return "''"
    if all(c.isalnum() or c == "_" for c in name):
        return name
    return f"'{name}'"


def write_table_tmdl(table: Table) -> str:
    """Serialize a Table object to TMDL text (flat-file format)."""
    lines: list[str] = [f"table {_quote_if_needed(table.name)}"]

    if table.lineage_tag:
        lines.append(f"{TAB}lineageTag: {table.lineage_tag}")
    if table.data_category:
        lines.append(f"{TAB}dataCategory: {table.data_category}")
    lines.append("")

    for col in table.columns:
        lines.extend(_write_column(col))

    for measure in table.measures:
        lines.extend(_write_measure(measure))

    for hierarchy in table.hierarchies:
        lines.extend(_write_hierarchy(hierarchy))

    for partition in table.partitions:
        lines.extend(_write_partition(partition, table.name))

    return "\n".join(lines) + "\n"


def _write_column(col: Column) -> list[str]:
    lines = [f"{TAB}column {_quote_if_needed(col.name)}"]
    if col.data_type:
        lines.append(f"{TAB * 2}dataType: {col.data_type}")
    if col.is_hidden:
        lines.append(f"{TAB * 2}isHidden: true")
    if col.is_key:
        lines.append(f"{TAB * 2}isKey: true")
    if col.format_string:
        lines.append(f"{TAB * 2}formatString: {col.format_string}")
    if col.sort_by_column:
        lines.append(f"{TAB * 2}sortByColumn: {col.sort_by_column}")
    lines.append(f"{TAB * 2}summarizeBy: {col.summarize_by or 'none'}")
    if col.source_column:
        lines.append(f"{TAB * 2}sourceColumn: {col.source_column}")
    if col.lineage_tag:
        lines.append(f"{TAB * 2}lineageTag: {col.lineage_tag}")
    if col.description:
        escaped = col.description.replace('"', '\\"')
        lines.append(f'{TAB * 2}description: "{escaped}"')
    lines.append("")
    return lines


def _write_measure(measure: Measure) -> list[str]:
    expr = measure.expression.strip()
    expr_lines = expr.splitlines() if expr else [""]

    lines = [f"{TAB}measure {_quote_if_needed(measure.name)} = {expr_lines[0]}"]
    for extra in expr_lines[1:]:
        lines.append(f"{TAB * 2}{extra}")

    if measure.format_string:
        lines.append(f"{TAB * 2}formatString: {measure.format_string}")
    if measure.display_folder:
        lines.append(f"{TAB * 2}displayFolder: {measure.display_folder}")
    if measure.lineage_tag:
        lines.append(f"{TAB * 2}lineageTag: {measure.lineage_tag}")
    if measure.description:
        escaped = measure.description.replace('"', '\\"')
        lines.append(f'{TAB * 2}description: "{escaped}"')
    lines.append("")
    return lines


def _write_hierarchy(hierarchy: Hierarchy) -> list[str]:
    lines = [f"{TAB}hierarchy {_quote_if_needed(hierarchy.name)}"]
    for level in hierarchy.levels:
        lines.append(f"{TAB * 2}level {_quote_if_needed(level.name)}")
        if level.column:
            lines.append(f"{TAB * 3}column: {level.column}")
    lines.append("")
    return lines


def _write_partition(partition: Partition, table_name: str) -> list[str]:
    lines = [f"{TAB}partition {_quote_if_needed(partition.name)} = {partition.source_type or 'm'}"]
    lines.append(f"{TAB * 2}mode: {partition.mode}")
    lines.append(f"{TAB * 2}source =")
    for line in partition.expression.splitlines():
        lines.append(f"{TAB * 3}{line}")
    lines.append("")
    return lines
