"""Export d'une analyse de CDC vers Excel (.xlsx) ou Markdown (.md)."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


STATUS_LABEL = {
    "covered": "Couvert",
    "partial": "Partiel",
    "missing": "Manquant",
    "ambiguous": "Ambigu",
}

STATUS_COLOR = {
    "covered": "C8F1D6",
    "partial": "FCE7B1",
    "missing": "F6C7C7",
    "ambiguous": "E2E8F0",
}


def _flatten_evidence(evidence: List[Any]) -> str:
    if not evidence:
        return ""
    parts: List[str] = []
    for e in evidence:
        if isinstance(e, str):
            parts.append(e)
        elif isinstance(e, dict):
            parts.append(str(e.get("text") or e.get("content") or ""))
    return "\n— ".join(["", *parts]).lstrip("\n").strip()


def _flatten_sources(sources: List[Any]) -> str:
    if not sources:
        return ""
    parts: List[str] = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        src = s.get("source") or "?"
        page = s.get("page")
        if page is not None:
            parts.append(f"{src} (p.{page})")
        else:
            parts.append(str(src))
    return "; ".join(parts)


def build_xlsx(filename: str, report: Dict[str, Any]) -> bytes:
    """Produit un .xlsx avec deux feuilles : Synthèse + Exigences."""
    wb = Workbook()

    # --- Feuille 1 : Synthèse ---
    ws1 = wb.active
    ws1.title = "Synthèse"

    title_font = Font(name="Calibri", size=14, bold=True, color="0B1B2B")
    label_font = Font(name="Calibri", size=11, bold=True)
    ws1["A1"] = "Analyse de cahier des charges"
    ws1["A1"].font = title_font
    ws1["A2"] = filename
    ws1["A2"].font = Font(italic=True, color="6B7A90")
    ws1["A3"] = f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws1["A3"].font = Font(italic=True, color="6B7A90")

    summary = report.get("summary") or {}
    rows = [
        ("Total exigences", summary.get("total", 0)),
        ("Couvertes", summary.get("covered", 0)),
        ("Partielles", summary.get("partial", 0)),
        ("Manquantes", summary.get("missing", 0)),
        ("Ambiguës", summary.get("ambiguous", 0)),
        ("Couverture", f"{summary.get('coverage_percent', 0):.1f}%"),
    ]
    for i, (label, value) in enumerate(rows, start=5):
        ws1.cell(row=i, column=1, value=label).font = label_font
        ws1.cell(row=i, column=2, value=value)

    ws1.column_dimensions["A"].width = 24
    ws1.column_dimensions["B"].width = 18

    # --- Feuille 2 : Exigences ---
    ws2 = wb.create_sheet("Exigences")
    headers = [
        "ID",
        "Titre",
        "Catégorie",
        "Priorité",
        "Statut",
        "Verdict",
        "Description",
        "Critères d'acceptation",
        "Localisation source",
        "Preuves",
        "Sources retrouvées",
    ]
    header_fill = PatternFill("solid", fgColor="2E6BE6")
    header_font = Font(bold=True, color="FFFFFF")
    for col_idx, h in enumerate(headers, start=1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", horizontal="left")
    ws2.row_dimensions[1].height = 22

    requirements = report.get("requirements") or []
    for i, r in enumerate(requirements, start=2):
        status = (r.get("status") or "").lower()
        ws2.cell(row=i, column=1, value=r.get("id", ""))
        ws2.cell(row=i, column=2, value=r.get("title", ""))
        ws2.cell(row=i, column=3, value=r.get("category", ""))
        ws2.cell(row=i, column=4, value=r.get("priority", ""))
        status_cell = ws2.cell(row=i, column=5, value=STATUS_LABEL.get(status, status))
        if status in STATUS_COLOR:
            status_cell.fill = PatternFill("solid", fgColor=STATUS_COLOR[status])
        ws2.cell(row=i, column=6, value=r.get("verdict", ""))
        ws2.cell(row=i, column=7, value=r.get("description", ""))
        ac = r.get("acceptance_criteria") or []
        ws2.cell(row=i, column=8, value="\n".join(f"• {x}" for x in ac))
        ws2.cell(row=i, column=9, value=r.get("source_location", ""))
        ws2.cell(row=i, column=10, value=_flatten_evidence(r.get("evidence") or []))
        ws2.cell(row=i, column=11, value=_flatten_sources(r.get("sources") or []))

    widths = [10, 36, 22, 12, 14, 50, 50, 40, 22, 50, 40]
    for idx, w in enumerate(widths, start=1):
        ws2.column_dimensions[get_column_letter(idx)].width = w
    ws2.freeze_panes = "A2"
    for row in ws2.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_markdown(filename: str, report: Dict[str, Any]) -> str:
    """Produit un rapport Markdown synthétique de l'analyse."""
    summary = report.get("summary") or {}
    requirements = report.get("requirements") or []
    lines: List[str] = []
    lines.append(f"# Analyse de cahier des charges — {filename}")
    lines.append("")
    lines.append(f"_Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}_")
    lines.append("")

    lines.append("## Synthèse")
    lines.append("")
    lines.append("| Indicateur | Valeur |")
    lines.append("|---|---|")
    lines.append(f"| Total exigences | {summary.get('total', 0)} |")
    lines.append(f"| Couvertes | {summary.get('covered', 0)} |")
    lines.append(f"| Partielles | {summary.get('partial', 0)} |")
    lines.append(f"| Manquantes | {summary.get('missing', 0)} |")
    lines.append(f"| Ambiguës | {summary.get('ambiguous', 0)} |")
    lines.append(f"| **Couverture** | **{summary.get('coverage_percent', 0):.1f}%** |")
    lines.append("")

    # Group by status for readability
    groups: Dict[str, List[Dict[str, Any]]] = {
        "covered": [],
        "partial": [],
        "missing": [],
        "ambiguous": [],
    }
    for r in requirements:
        st = (r.get("status") or "").lower()
        groups.setdefault(st, []).append(r)

    headers = [
        ("covered", "Exigences couvertes"),
        ("partial", "Exigences partielles"),
        ("missing", "Exigences manquantes"),
        ("ambiguous", "Exigences ambiguës"),
    ]
    for key, h in headers:
        items = groups.get(key) or []
        if not items:
            continue
        lines.append(f"## {h} ({len(items)})")
        lines.append("")
        for r in items:
            lines.append(f"### {r.get('id', '')} — {r.get('title', '')}")
            if r.get("category"):
                lines.append(f"**Catégorie** : {r['category']}  ")
            if r.get("priority"):
                lines.append(f"**Priorité** : {r['priority']}  ")
            if r.get("source_location"):
                lines.append(f"**Localisation source** : {r['source_location']}  ")
            lines.append("")
            if r.get("description"):
                lines.append(r["description"])
                lines.append("")
            if r.get("verdict"):
                lines.append(f"> **Verdict** — {r['verdict']}")
                lines.append("")
            ac = r.get("acceptance_criteria") or []
            if ac:
                lines.append("**Critères d'acceptation** :")
                for x in ac:
                    lines.append(f"- {x}")
                lines.append("")
            ev = r.get("evidence") or []
            if ev:
                lines.append("**Preuves** :")
                for e in ev:
                    if isinstance(e, str):
                        lines.append(f"- {e}")
                    elif isinstance(e, dict):
                        txt = e.get("text") or e.get("content") or ""
                        lines.append(f"- {txt}")
                lines.append("")
            srcs = r.get("sources") or []
            if srcs:
                lines.append("**Sources retrouvées** :")
                for s in srcs:
                    if not isinstance(s, dict):
                        continue
                    src = s.get("source") or "?"
                    page = s.get("page")
                    score = s.get("score")
                    extra = []
                    if page is not None:
                        extra.append(f"p.{page}")
                    if isinstance(score, (int, float)):
                        extra.append(f"score {score:.3f}")
                    suffix = f" ({', '.join(extra)})" if extra else ""
                    lines.append(f"- {src}{suffix}")
                lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)
