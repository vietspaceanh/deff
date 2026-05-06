from __future__ import annotations

from .specs import TableSpec, flatten_ctes
from .runtime import runtime, Graph

COLORS = {
    "numeric": "#89b4fa",
    "string": "#8ee087",
    "boolean": "#fab387",
    "temporal": "#b4befe",
    "badge_bg": "#313244",
    "border": "#45475a",
    "default": "#555555",
    "default_bg": "#eeeeee",
    "highlighted_border": "#589bffb8",
}
NUMERIC = ("INTEGER", "BIGINT", "HUGEINT", "SMALLINT", "TINYINT", "FLOAT", "DOUBLE", "DECIMAL")
TEMPORAL = ("DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE", "TIME", "INTERVAL")
STRING = ("VARCHAR", "CHAR", "TEXT")
TYPE_ROLES = {
    **{t: "numeric" for t in NUMERIC},
    **{t: "temporal" for t in TEMPORAL},
    **{t: "string" for t in STRING},
    "BOOLEAN": "boolean",
}


def result_to_html(result, max_rows) -> str:
    cols, types, rows, truncated = _extract_preview(result, max_rows)
    colors = [COLORS[TYPE_ROLES.get(t, "default")] for t in types]
    border = COLORS["border"]
    html = f"""<style>
    .deff-tbl {{ border-collapse:separate }}
    .deff-tbl th {{ text-align:center;position:sticky;top:0;z-index:1;backdrop-filter:blur(24px);background:rgba(128,128,128,0.04);border-right:1px solid {border} }}
    .deff-tbl td {{ border-right:1px solid {border} }}
    .deff-tbl-badge {{ font-size:0.75em;background:{COLORS["badge_bg"]};padding:1px 5px;border-radius:3px;font-weight:500 }}
    </style>
    <div style="max-height:400px;overflow-y:auto"><table class="deff-tbl"><thead><tr>
    """
    for col, t, c in zip(cols, types, colors):
        html += f'<th>{col}<br><span class="deff-tbl-badge" style="color:{c}">{t}</span></th>'
    html += "</tr></thead><tbody>"
    for row in rows:
        html += "<tr>" + "".join(
            f'<td style="color:{colors[i]}">{_escape_html(str(v)) if v is not None else "&nbsp;"}</td>'
            for i, v in enumerate(row)
        ) + "</tr>"
    html += "</tbody></table></div>"
    if truncated:
        html += f"<em>... showing first {len(rows)} rows, {len(cols)} columns</em>"
    elif rows:
        html += f"<em>({len(rows)} rows, {len(cols)} columns)</em>"
    return html


def result_to_rich(result, max_rows):
    import rich.table as rt
    from rich.text import Text

    cols, types, rows, truncated = _extract_preview(result, max_rows)

    table = rt.Table()
    for col, t in zip(cols, types):
        color = COLORS[TYPE_ROLES.get(t, "default")]
        header = Text.assemble(
            (col, "bold"),
            ("\n", ""),
            (t, f"{color}"),
        )
        table.add_column(header, no_wrap=True)

    for row in rows:
        styled_row = []
        for i, v in enumerate(row):
            color = COLORS[TYPE_ROLES.get(types[i], "default")]
            if v is None:
                styled_row.append("")
            else:
                styled_row.append(Text(str(v), style=color))
        table.add_row(*styled_row)
    yield table
    if truncated:
        yield Text("(Showing first {} rows, {} columns. Use .fetchall() for full data.)".format(
            len(rows), len(cols)
        ), style="italic dim")


def generate_mermaid_code(table_spec: TableSpec) -> str:
    ctx = runtime.graph(table_spec)
    target = table_spec.name
    lines = ["graph TD"]

    subgraphs: dict = {}
    node_to_subgraph: dict[str, str] = {}
    parent_styles: set[str] = set()

    for name in ctx.topological_order(target):
        spec = ctx.nodes[name]
        if spec.is_cte:
            continue
        label = _node_label(spec)
        if spec.ctes:
            _register_subgraph(name, spec, subgraphs, node_to_subgraph, parent_styles, label, lines)
        for dep_name in ctx.edges.get(name, set()):
            dep = ctx.nodes.get(dep_name)
            if dep is None or dep.is_cte:
                continue
            if node_to_subgraph.get(name) and dep_name not in spec.query.table_names:
                continue
            lines.append(f'    {dep.name}["{_node_label(dep)}"] --> {name}["{label}"]')

    highlighted = COLORS["highlighted_border"]
    for subgraph_id, all_ctes, sub_label, parent_specs in subgraphs.values():
        _write_subgraph_header(subgraph_id, sub_label, all_ctes, lines)
        _add_cte_internal_edges(subgraph_id, all_ctes, lines)
        _close_subgraph(subgraph_id, all_ctes, highlighted, lines)
        _add_cte_external_deps(subgraph_id, parent_specs, highlighted, ctx, lines)

    for name in parent_styles:
        lines.append(f"    style {name} stroke-width:2px")

    return "\n".join(lines)


# ───────────────────────────── Helper functions ───────────────────────────── #

def _extract_preview(result, max_rows):
    cols = result.columns
    types = result.types
    rows = list(result.fetchmany(max_rows + 1))
    truncated = len(rows) == max_rows + 1
    if truncated:
        rows = rows[:max_rows]
    return cols, types, rows, truncated


def _extract_preview(result, max_rows=50):
    cols = result.columns
    types = result.types
    rows = list(result.fetchmany(max_rows + 1))
    truncated = len(rows) == max_rows + 1
    if truncated:
        rows = rows[:max_rows]
    return cols, types, rows, truncated


def _display_name(func_name: str) -> str:
    parts = func_name.split("__", 1)
    if len(parts) == 2:
        if parts[0] == "_main":
            return parts[1]
        return f"{parts[0]}.{parts[1]}"
    return parts[0]


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _node_label(spec: TableSpec) -> str:
    if spec.is_cte:
        display = spec.func_name.split("__", 1)[-1]
    else:
        display = _display_name(spec.func_name)
    if not spec.args:
        return f"<b>{display}</b>"
    named = []
    for k, v in spec.args.items():
        if hasattr(v, "func_name"):
            p = v.func_name.split("__", 1)
            if len(p) == 2:
                if p[0] == "_main":
                    val = p[1]
                else:
                    val = f"{p[0]}.{p[1]}"
            else:
                val = p[0]
        elif hasattr(v, "name"):
            val = v.name
        else:
            val = str(v).replace("'", "")
        named.append(f"<b>{k}</b>: {val}")
    arg_block = "\n".join(named)
    formatted_args = f"<div style='text-align:left'><small><pre>{arg_block}</pre></small></div>"
    return f"`**{display}**\n{formatted_args}`"


def _register_subgraph(
    name: str,
    spec: TableSpec,
    subgraphs: dict,
    node_to_subgraph: dict[str, str],
    parent_styles: set[str],
    label: str,
    lines: list[str],
):
    all_ctes = flatten_ctes(spec.ctes)
    cte_names = sorted(c.name for c in all_ctes)
    key = (spec.func_name, tuple(cte_names))

    sub_label = _display_name(spec.func_name)

    if key not in subgraphs:
        subgraph_id = f"sg_{len(subgraphs)}"
        subgraphs[key] = (subgraph_id, all_ctes, sub_label, [spec])
    else:
        subgraph_id = subgraphs[key][0]
        subgraphs[key][3].append(spec)

    node_to_subgraph[name] = subgraph_id
    parent_styles.add(name)
    lines.append(f'    {subgraph_id} --> {name}["{label}"]')


def _write_subgraph_header(
    subgraph_id: str,
    sub_label: str,
    all_ctes: list[TableSpec],
    lines: list[str],
):
    lines.append(f'    subgraph {subgraph_id}["Sub-tables of <b>{sub_label}</b>"]')
    for cte in all_ctes:
        cte_id = f"{subgraph_id}__{cte.name}"
        lines.append(f'        {cte_id}["{_node_label(cte)}"]')


def _add_cte_internal_edges(
    subgraph_id: str,
    all_ctes: list[TableSpec],
    lines: list[str],
):
    cte_names = {c.name for c in all_ctes}
    for cte in all_ctes:
        for ref in cte.query.table_names & cte_names:
            if ref != cte.name:
                lines.append(f"        {subgraph_id}__{ref} --> {subgraph_id}__{cte.name}")


def _add_cte_external_deps(
    subgraph_id: str,
    parent_specs: list[TableSpec],
    highlighted: str,
    ctx: Graph,
    lines: list[str],
):
    link_idx = sum(1 for l in lines if "-->" in l or "-.->" in l)
    seen: set[tuple[str, str]] = set()
    for ps in parent_specs:
        for cte in flatten_ctes(ps.ctes):
            cte_direct = cte.query.table_names
            for dep_name in ctx.edges.get(ps.name, set()):
                if dep_name not in cte_direct:
                    continue
                edge = (dep_name, cte.name)
                if edge in seen:
                    continue
                seen.add(edge)
                dep = ctx.nodes.get(dep_name)
                if dep is None or dep.is_cte:
                    continue
                lines.append(
                    f'    {dep.name}["{_node_label(dep)}"] -.-> {subgraph_id}__{cte.name}'
                )
                lines.append(
                    f"    linkStyle {link_idx} stroke:{highlighted},stroke-width:1px"
                )
                link_idx += 1


def _close_subgraph(
    subgraph_id: str,
    all_ctes: list[TableSpec],
    highlighted: str,
    lines: list[str],
):
    lines.append("    end")
    lines.append(f"    style {subgraph_id} stroke:{highlighted},stroke-width:2px,stroke-dasharray:5 3")
    for cte in all_ctes:
        lines.append(f"    style {subgraph_id}__{cte.name} stroke:{highlighted},stroke-width:2px")