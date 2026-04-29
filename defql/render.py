from __future__ import annotations

from .base import REGISTRY, TableSpec, TableNode, extract_table_names, flatten_ctes
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


def _node_label(node: TableNode) -> str:
    parts = node.spec.func_name.split("__", 1)
    display = f"{parts[0]}.{parts[1]}" if len(parts) == 2 else parts[0]
    if not node.spec.args:
        return display
    named = []
    for k, v in node.spec.args.items():
        if hasattr(v, "name"):
            if v.name in REGISTRY:
                p = v.name.split("__", 1)
                val = f"{p[0]}.{p[1]}" if len(p) == 2 else p[0]
            else:
                val = v.name
        else:
            val = str(v).replace("'", "")
        named.append(f"{k}=**{val}**")
    args = ", ".join(named)
    return f"`**{display}**\n{args}`"


def to_mermaid(table_spec: TableSpec) -> str:
    ctx = build_context(table_spec)
    target = table_spec.name
    lines = ["graph TD"]
    link_idx = 0
    dotted_links: list[int] = []

    subgraphs: dict[tuple, tuple[str, list[TableNode], str]] = {}
    parent_styles: set[str] = set()

    for name in ctx.topological_order(target):
        node = ctx.nodes[name]
        label = _node_label(node)
        for dep in node.deps:
            dep_label = _node_label(ctx.nodes[dep])
            lines.append(f'    {dep}["{dep_label}"] --> {name}["{label}"]')
            link_idx += 1
        if node.ctes:
            all_ctes = flatten_ctes(node.ctes)
            cte_names = sorted(c.spec.name for c in all_ctes)
            key = (node.spec.func_name, tuple(cte_names))

            sub_label = _node_label(node)
            if sub_label.startswith("`"):
                parts = node.spec.func_name.split("__", 1)
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

    for subgraph_id, all_ctes, sub_label in subgraphs.values():
        cte_names = {c.spec.name for c in all_ctes}
        lines.append(f'    subgraph {subgraph_id}["{sub_label} CTEs"]')
        for cte in all_ctes:
            cte_id = f"{subgraph_id}__{cte.spec.name}"
            lines.append(f'        {cte_id}["{cte.spec.name}"]')
        for cte in all_ctes:
            for ref in extract_table_names(cte.spec.sql) & cte_names:
                if ref != cte.spec.name:
                    lines.append(f"        {subgraph_id}__{ref} --> {subgraph_id}__{cte.spec.name}")
                    link_idx += 1
        lines.append("    end")
        lines.append(f"    style {subgraph_id} stroke:#90caf9,stroke-width:2px,stroke-dasharray:5 3")
        for cte in all_ctes:
            lines.append(f"    style {subgraph_id}__{cte.spec.name} stroke:#90caf9,stroke-width:2px")

    for i in dotted_links:
        lines.append(f"    linkStyle {i} stroke:#90caf9,stroke-dasharray:5 3,stroke-width:2px")

    for name in parent_styles:
        lines.append(f"    style {name} stroke:#90caf9,stroke-width:2px")

    return "\n".join(lines)
