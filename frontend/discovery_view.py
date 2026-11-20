"""The Discovery tab: alerts on new cell and gene therapy papers, and the papers.

Pure builders: HTML from the two reads of ``backend/discovery_board.py``, knowing
nothing of the API or of Streamlit. Three things are kept in view everywhere, because
each is easy to misread:

- a rank is against a year of papers, read by a model from the title and abstract alone.
  It is "top 3%", never a probability and never a view on the science;
- a lab is matched by name and institution, and the row says how it was matched;
- several alerts about one paper are one row, since they are one event.

No colour carries a score here. The terminal's green and red mean up and down, and a
paper's rank is neither.
"""

from __future__ import annotations

import html

# Bumped when the copy changes, as calendar_view does.
REVISION = 1
ALERTS_DAYS = 14
PAPERS_DAYS = 30
PAPERS_SHOWN = 40
SORTS = (("feas", "Feasibility"), ("comm", "Commercial pull"), ("date", "Newest"))
MAX_TITLE = 150

EMPTY_ALERTS = ("No alert in the last {days} days",
                "An alert is raised when a new paper ranks in the top {share}% on either "
                "score, or when a lab head ranked in the top {limit} publishes, reaches a "
                "later model stage or first publishes with a company.")
NOT_READ_YET = ("Europe PMC has not been read yet",
                "The papers arrive with the daily refresh. Nothing is shown until it has "
                "run once with this source.")
NOTE = (
    "New papers and preprints in cell and gene therapy, read from Europe PMC by the day "
    "they entered its index. Each is given two ranks against the last year of such papers. "
    "Feasibility was trained on whether a paper went on to be cited by clinical work, and "
    "commercial pull on whether it was cited by work with a company author. Both read the "
    "title and abstract only and know nothing of who wrote the paper. On papers held back "
    "from training, feasibility separated the two groups with an AUC of 0.84 and commercial "
    "pull with 0.79, so a top rank is a reason to read the paper, not a finding. "
    "A lab head is matched by full name and institution, or by name alone for a preprint "
    "with no address when one ranked lab has that name. Against known identities the match "
    "was wrong about 1 time in 140. The lab ranking is dated and is not updated daily. "
    "A paper with no abstract yet is held and scored when one arrives. Nothing here moves "
    "a value, a forecast or a company's note.")


def _e(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def _clip(text, limit: int = MAX_TITLE) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _where(paper: dict) -> str:
    """"Blood, 2026-11-01" or "bioRxiv preprint, 2026-11-17"."""
    place = paper.get("journal") or ""
    if paper.get("preprint"):
        place = f"{place} preprint".strip()
    return ", ".join(x for x in (place, paper.get("published")) if x)


def _who(paper: dict) -> str:
    return ", ".join(x for x in (paper.get("senior_author"), paper.get("institution")) if x)


def _ranks(paper: dict) -> str:
    """Both ranks in words, the better first."""
    pairs = sorted(((paper.get("feas_pct"), paper.get("feas_top"), "feasibility"),
                    (paper.get("comm_pct"), paper.get("comm_top"), "commercial pull")),
                   key=lambda x: -(x[0] or 0))
    return ", ".join(f"{top} for {name}" for pct, top, name in pairs if pct is not None)


def _raised(paper: dict, score: str) -> str:
    reasons = (paper.get("reasons") or {}).get(score) or {}
    return ", ".join((reasons.get("flags") or []) + (reasons.get("phrases") or [])[:3])


def basis(got: dict) -> str:
    """The chip beside the section title: what the ranks stand on, with its dates."""
    b = got.get("basis") or {}
    parts = []
    if b.get("last_read"):
        parts.append(f"Europe PMC read {b['last_read'][:10]}")
    if b.get("labs"):
        parts.append(f"{b['labs']:,} lab heads ranked {b.get('labs_ranked_as_of') or ''}".strip())
    return " · ".join(parts)


def _lead(alert: dict) -> str:
    """What happened, in a line. The paper's title follows it as the link."""
    lab, paper, kind = alert.get("lab") or {}, alert.get("paper") or {}, alert.get("kind")
    named = f"{lab.get('name')}, ranked {lab.get('rank')}" if lab else "A ranked lab head"
    if kind == "discovery_paper_top":
        ranks = _ranks(paper)
        return ranks[:1].upper() + ranks[1:] if ranks else "Ranked in the top of a score"
    if kind == "discovery_lab_stage":
        stage = paper.get("stage_name") or "a later model"
        return (f"{named}: first paper in {stage}, after "
                f"{alert.get('before') or 'none naming a model'}")
    if kind == "discovery_lab_company":
        return f"{named}: first paper with a company among the authors"
    return f"{named}, published"


def alerts_html(got: dict, days_open: int = 3) -> str:
    """The alerts by day, newest first, one row a paper. The newest days are open and
    the rest folded. "" when there is none."""
    by_day: dict = {}
    for alert in got.get("alerts") or []:
        by_day.setdefault(alert.get("date") or "", {}).setdefault(
            alert.get("paper_id") or alert.get("id"), []).append(alert)
    out = []
    for n, (day, groups) in enumerate(sorted(by_day.items(), reverse=True)):
        body = []
        for group in groups.values():
            first = group[0]
            paper = first.get("paper") or {}
            high = any(a.get("significance") == "high" for a in group)
            chips = "".join(f'<span class="dsc-kind">{_e(a.get("kind_name"))}</span>'
                            for a in group)
            leads = "".join(f'<div class="dsc-lead">{_e(_lead(a))}</div>' for a in group)
            # The paper row can be gone (it leaves the table after a year); the stored
            # headline still says the whole thing.
            title = (f'<a href="{_e(first.get("url"))}" target="_blank" rel="noopener">'
                     f'{_e(_clip(paper.get("title")))}</a>' if paper.get("title")
                     else f'<span>{_e(first.get("headline"))}</span>')
            meta = " · ".join(x for x in (_who(paper), _where(paper)) if x)
            ranks = _ranks(paper)
            matched = paper.get("lab_match")
            extra = " · ".join(x for x in (
                ranks[:1].upper() + ranks[1:] if ranks and not any(
                    a.get("kind") == "discovery_paper_top" for a in group) else "",
                ", ".join((paper.get("areas") or [])[:3]),
                f"lab matched by {matched}" if matched and any(a.get("lab") for a in group)
                else "") if x)
            body.append(
                f'<div class="dsc-item{" high" if high else ""}">'
                f'<div class="dsc-chips">{chips}</div>{leads}'
                f'<div class="dsc-title">{title}</div>'
                + (f'<div class="dsc-meta">{_e(meta)}</div>' if meta else "")
                + (f'<div class="dsc-meta">{_e(extra)}</div>' if extra else "")
                + "</div>")
        count = f"{len(groups)} paper{'' if len(groups) == 1 else 's'}"
        if n < days_open:
            out.append(f'<div class="dsc-day">{_e(day)} · {count}</div>' + "".join(body))
        else:
            out.append(f'<details class="pt-more"><summary>{_e(day)} · {count}</summary>'
                       f'{"".join(body)}</details>')
    return "".join(out)


def papers_html(got: dict, limit: int = PAPERS_SHOWN) -> str:
    """The scored papers as a table, in the order the read sorted them. "" for none."""
    rows = (got.get("papers") or [])[:limit]
    if not rows:
        return ""
    score = "comm" if got.get("sort") == "comm" else "feas"
    body = []
    for p in rows:
        lab = p.get("lab") or {}
        meta = " · ".join(x for x in (_who(p), _where(p)) if x)
        company = "yes" if p.get("company_author") else (
            "" if p.get("company_author") is None else "no")
        body.append(
            "<tr>"
            f'<td class="n">{_e((p.get("feas_top") or "").replace("top ", ""))}</td>'
            f'<td class="n">{_e((p.get("comm_top") or "").replace("top ", ""))}</td>'
            f'<td class="p"><a href="{_e(p.get("url"))}" target="_blank" rel="noopener">'
            f'{_e(_clip(p.get("title")))}</a><div class="dsc-meta">{_e(meta)}</div></td>'
            f'<td class="n" title="{_e(lab.get("name") or "")}">'
            f'{_e(lab.get("rank") or "")}</td>'
            f'<td>{_e(p.get("stage_name") or "")}</td>'
            f'<td>{company}</td>'
            f'<td class="w">{_e(_raised(p, score))}</td>'
            "</tr>")
    raised = "commercial pull" if score == "comm" else "feasibility"
    return ('<table class="dsc"><thead><tr>'
            '<th class="n" title="Rank against a year of papers">Feasibility, top</th>'
            '<th class="n" title="Rank against a year of papers">Commercial pull, top</th>'
            '<th>Paper</th>'
            '<th class="n" title="Rank of the senior author among the lab heads">Lab rank</th>'
            '<th>Latest model</th><th>Company author</th>'
            f'<th>What raised {raised}</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def papers_count(got: dict, limit: int = PAPERS_SHOWN) -> str:
    total = got.get("total") or 0
    shown = min(total, limit, len(got.get("papers") or []))
    return f"{shown} of {total:,}" if total > shown else f"{total:,}"


def held_line(got: dict) -> str:
    held = (got.get("basis") or {}).get("held_without_abstract") or 0
    if not held:
        return ""
    return (f"{held:,} paper{'' if held == 1 else 's'} held without an abstract, "
            "scored when one arrives.")
