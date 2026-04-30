from __future__ import annotations

from .base import REGISTRY, TableSpec, extract_table_names, flatten_ctes, collect_cte_deps
from .context import build_context

N_ROWS = 200

COLORS = {
    "numeric": "#89b4fa",
    "string": "#8ee087dc",
    "boolean": "#fab387dc",
    "temporal": "#b4befe",
    "badge_bg": "#313244",
    "border": "#45475a",
    "default": "#555555",
    "default_bg": "#eeeeee",
    "highlighted_border": "#7190f6b0",
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


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def result_to_html(cols, types, rows, truncated) -> str:
    colors = [COLORS[TYPE_ROLES.get(t, "default")] for t in types]
    bg = COLORS["badge_bg"]
    html = '<div style="max-height:400px; overflow-y:auto"><table style="border-collapse:collapse"><thead><tr>'
    sep = f'border-right:1px solid {COLORS["border"]}'
    for col, t, c in zip(cols, types, colors):
        html += f'<th style="text-align:center;{sep}">{col}<br><span style="font-size:0.75em;color:{c};background:{bg};padding:1px 5px;border-radius:3px;font-weight:500">{t}</span></th>'
    html += "</tr></thead><tbody>"
    for row in rows:
        html += "<tr>" + "".join(
            f'<td style="color:{colors[i]};{sep}">{_escape_html(str(v)) if v is not None else ""}</td>'
            for i, v in enumerate(row)
        ) + "</tr>"
    html += "</tbody></table></div>"
    if truncated:
        html += f"<em>... showing first {len(rows)} rows</em>"
    elif rows:
        html += f"<em>({len(rows)} rows)</em>"
    return html


def _node_label(spec: TableSpec) -> str:
    parts = spec.func_name.split("__", 1)
    display = f"{parts[0]}.{parts[1]}" if len(parts) == 2 else parts[0]
    if not spec.args:
        return display
    named = []
    for k, v in spec.args.items():
        if hasattr(v, "name"):
            if v.name in REGISTRY:
                p = v.name.split("__", 1)
                val = f"{p[0]}.{p[1]}" if len(p) == 2 else p[0]
            else:
                val = v.name
        else:
            val = str(v).replace("'", "")
        named.append(f"<b>{k}</b>: {val}")
    args = "\n".join(named)
    formatted_args = f"<div style='text-align:left'><small><pre>{args}</pre></small></div>"
    return f"`**{display}**\n{formatted_args}`"


def to_mermaid(table_spec: TableSpec) -> str:
    ctx = build_context(table_spec)
    target = table_spec.name
    lines = ["graph TD"]
    link_idx = 0
    dotted_links: list[int] = []

    subgraphs: dict[tuple, tuple[str, list[TableSpec], str]] = {}
    parent_styles: set[str] = set()

    for name in ctx.topological_order(target):
        spec = ctx.nodes[name]
        label = _node_label(spec)
        for dep in spec.deps:
            dep_label = _node_label(dep)
            lines.append(f'    {dep.name}["{dep_label}"] --> {name}["{label}"]')
            link_idx += 1
        if spec.ctes:
            all_ctes = flatten_ctes(spec.ctes)
            cte_names = sorted(c.name for c in all_ctes)
            key = (spec.func_name, tuple(cte_names))

            sub_label = _node_label(spec)
            if sub_label.startswith("`"):
                parts = spec.func_name.split("__", 1)
                sub_label = f"{parts[0]}.{parts[1]}" if len(parts) == 2 else parts[0]

            if key not in subgraphs:
                subgraph_id = f"sg_{len(subgraphs)}"
                subgraphs[key] = (subgraph_id, all_ctes, sub_label)
            else:
                subgraph_id = subgraphs[key][0]

            parent_styles.add(name)
            dotted_links.append(link_idx)
            lines.append(f"    {subgraph_id} -.- {name}")
            link_idx += 1

    highlighted = COLORS["highlighted_border"]
    for subgraph_id, all_ctes, sub_label in subgraphs.values():
        cte_names = {c.name for c in all_ctes}
        lines.append(f'    subgraph {subgraph_id}["CTEs of **{sub_label}**"]')
        for cte in all_ctes:
            cte_id = f"{subgraph_id}__{cte.name}"
            lines.append(f'        {cte_id}["{cte.name}"]')
        for cte in all_ctes:
            for ref in extract_table_names(cte.sql) & cte_names:
                if ref != cte.name:
                    lines.append(f"        {subgraph_id}__{ref} --> {subgraph_id}__{cte.name}")
                    link_idx += 1
        lines.append("    end")
        lines.append(f"    style {subgraph_id} stroke:{highlighted},stroke-width:2px,stroke-dasharray:5 3")
        for cte in all_ctes:
            lines.append(f"    style {subgraph_id}__{cte.name} stroke:{highlighted},stroke-width:2px")

    for i in dotted_links:
        lines.append(f"    linkStyle {i} stroke:{highlighted},stroke-dasharray:5 3,stroke-width:2px")

    for name in parent_styles:
        lines.append(f"    style {name} stroke-width:2px")

    return "\n".join(lines)
