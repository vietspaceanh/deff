from __future__ import annotations

from . import config
from .specs import TableSpec, flatten_ctes
from .runtime import runtime, Graph
from .theme import resolve_colors, deff_theme, PRESET_FACTORIES

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
    def _truncate_cell(v, max_len=2000):
        if v is None:
            return "&nbsp;"
        s = str(v)
        if len(s) > max_len:
            s = s[:max_len] + "..."
        return _escape_html(s)

    cols, types, rows, truncated = _extract_preview(result, max_rows)
    roles = [TYPE_ROLES.get(t, "default") for t in types]
    html = _build_html_style()
    html += '<div class="deff-wrap"><div class="deff-scroll" style="max-height:400px;overflow-y:auto"><table class="deff-tbl"><thead><tr>'
    for col, t, r in zip(cols, types, roles):
        html += f'<th>{col}<br><span class="deff-tbl-badge" style="color:var(--c-{r})">{t}</span></th>'
    html += "</tr></thead><tbody>"
    for row in rows:
        html += "<tr>" + "".join(
            f'<td style="color:var(--c-{roles[i]})">{_truncate_cell(v)}</td>'
            for i, v in enumerate(row)
        ) + "</tr>"
    html += "</tbody></table></div></div>"
    if truncated:
        html += f'<div style="text-align:right"><em>... showing first {len(rows)} rows, {len(cols)} columns</em></div>'
    elif rows:
        html += f'<div style="text-align:right"><em>({len(rows)} rows, {len(cols)} columns)</em></div>'
    return html


def result_to_rich(result, max_rows):
    import rich.table as rt
    from rich.text import Text

    colors = resolve_colors()
    cols, types, rows, truncated = _extract_preview(result, max_rows)

    table = rt.Table()
    for col, t in zip(cols, types):
        color = colors[TYPE_ROLES.get(t, "default")]
        header = Text.assemble(
            (col, "bold"),
            ("\n", ""),
            (t, f"{color}"),
        )
        table.add_column(header, no_wrap=True)

    for row in rows:
        styled_row = []
        for i, v in enumerate(row):
            color = colors[TYPE_ROLES.get(types[i], "default")]
            if v is None:
                styled_row.append("")
            else:
                styled_row.append(Text(str(v), style=color))
        table.add_row(*styled_row)
    yield table
    if truncated:
        yield Text("(Showing first {} rows, {} columns. Use .fetchall() for full data.)".format(
            len(rows), len(cols)
        ), style="italic dim align-right")


def generate_mermaid_code(table_spec: TableSpec) -> str:
    colors = resolve_colors()
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

    highlighted = colors["highlighted_border"]
    for subgraph_id, all_ctes, sub_label, parent_specs in subgraphs.values():
        _write_subgraph_header(subgraph_id, sub_label, all_ctes, lines)
        _add_cte_internal_edges(subgraph_id, all_ctes, lines)
        _close_subgraph(subgraph_id, all_ctes, highlighted, lines)
        _add_cte_external_deps(subgraph_id, parent_specs, highlighted, ctx, lines)

    for name in parent_styles:
        lines.append(f"    style {name} stroke-width:2px")

    return "\n".join(lines)


# ───────────────────────────── Helper functions ───────────────────────────── #

def _extract_preview(result, max_rows=50):
    cols = result.columns
    types = result.types
    rows = list(result.fetchmany(max_rows + 1, fresh=True))
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


def _escape_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


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
            val = str(v).replace("'", "").replace('"', "")
        display_val = (val[:40] + '...') if len(val) > 40 else val
        if len(val) > 40:
            display_val = f'<span title="{_escape_attr(val)}">{display_val}</span>'
        named.append(f"<b>{k}</b>: {display_val}")
    arg_block = "\n".join(named)
    formatted_args = f"<div style='text-align:left'><small><pre>{arg_block}</pre></small></div>"
    return f"`<b>{display}</b>\n{formatted_args}`"


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


# ────────────────────────────────── Theming ───────────────────────────────── #


def _build_html_style() -> str:
    def block(colors):
        return "".join(f"--c-{k.replace('_', '-')}:{v};" for k, v in colors.items())

    cfg = deff_theme.config
    themed = resolve_colors()
    if not themed:
        return ""

    vars_block = block(themed)
    if cfg.mode == "auto":
        l = block(resolve_colors(PRESET_FACTORIES["light"]()))
        d = block(resolve_colors(PRESET_FACTORIES["dark"]()))
        style = (
            "<style>"
            f".deff-wrap{{{l}}}"
            f"@media(prefers-color-scheme:dark){{.deff-wrap{{{d}}}}}"
            f'body[data-jp-theme-light="true"] .deff-wrap{{{l}}}'
            f'body[data-jp-theme-light="false"] .deff-wrap{{{d}}}'
            f"body.vscode-light .deff-wrap{{{l}}}"
            f"body.vscode-dark .deff-wrap,body.vscode-high-contrast .deff-wrap{{{d}}}"
        )
    else:
        style = (
            "<style>"
            f".deff-wrap{{{vars_block}}}"
        )

    return style + (
        ".deff-wrap .deff-tbl{border-collapse:separate;border-spacing:0;border:none;margin-top:0;border-radius:0}"
        ".deff-wrap{overflow:hidden;contain:layout paint;border:1px solid var(--c-border);border-radius:var(--el-border-radius,14px)}"
        ".deff-scroll{overflow-y:auto;scrollbar-color:rgba(128,128,128,0.35) var(--c-badge-bg)}"
        ".deff-wrap .deff-tbl th{border:none;border-right:1px solid rgba(128,128,128,0.2);text-align:center;position:sticky;top:0;z-index:1;backdrop-filter:blur(24px);background:rgba(128,128,128,0.04)}"
        ".deff-wrap .deff-tbl th:last-child,.deff-wrap .deff-tbl td:last-child{border-right:none}"
        ".deff-wrap .deff-tbl td{border:none;border-right:1px solid rgba(128,128,128,0.2);border-bottom:1px solid rgba(128,128,128,0.2);min-width:10ch}"
        ".deff-wrap .deff-tbl-badge{font-size:0.75em;background:var(--c-badge-bg);padding:1px 5px;border-radius:3px;font-weight:500}"
        "</style>"
    )
