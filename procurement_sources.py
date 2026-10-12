"""Supplemental public procurement-listing discovery for PH Consulting.

These parsers read only publicly accessible listing HTML. They never use supplier
credentials or bypass logins. A fetched search page is not proof every entry is an
open consultant opportunity. Construction-only and CM-only exclusion comes from
the caller's strict title classifier. Date metadata retains its real meaning.
"""
from __future__ import annotations
import re
from urllib.parse import urlsplit

OREGON_BUYS_URL = ("https://oregonbuys.gov/bso/view/search/external/"
                   "advancedSearchBid.xhtml?openBids=true")
WSDOT_CONTRACTS_URL = (
    "https://wsdot.wa.gov/business-wsdot/contracts/search-contracting-opportunities"
)
DJC_MANUAL_URL = "https://www.djc.com/ae/wanted.html"

PUBLIC_SOURCES = [
    {"name": "OregonBuys public open-bid search", "state": "OR",
     "kind": "oregonbuys_public", "url": OREGON_BUYS_URL},
    {"name": "WSDOT consultant contracts search", "state": "WA",
     "kind": "wsdot_contracts", "url": WSDOT_CONTRACTS_URL},
]
MANUAL_SOURCES = [
    {"name": "DJC A/E Wanted — subscriber login required",
     "url": DJC_MANUAL_URL, "status": "Manual review — subscription/login",
     "detail": "The A/E Wanted page redirects to a subscriber login. "
               "It is not scraped and does not count as a successful search."},
    {"name": "OregonBuys supplier portal — account may be required",
     "url": "https://oregonbuys.gov/bso/",
     "status": "Manual review for additional notices / attachments",
     "detail": "Public search results are checked separately; some details "
               "or response actions may require vendor access."},
]

PRE_NOTICE = re.compile(
    r"\b(?:pre[ -]?solicitation|advance notice|request for information|"
    r"notice of intent|informational notice|sources sought)\b", re.I
)
DISQUALIFY = re.compile(
    r"\b(?:notice of intent to award|intent to award|sole source|"
    r"notice of award|awarded|cancelled|canceled|closed|"
    r"itb\b|invitation to bid|construction management|"
    r"construction inspection|construction[- ]only)\b", re.I
)
BID_ID = re.compile(r"^S-[A-Za-z0-9-]+$", re.I)
WSDOT_DEADLINE = re.compile(
    r"\bSubmittal due\s*:\s*(.{0,95})", re.I
)
WSDOT_PUBLISHED = re.compile(
    r"\bPublication date\s*:\s*(.{0,95})", re.I
)


def _cells(tr):
    return [node for node in tr.children if not isinstance(node, str)
            and node.tag in ("td", "th")]


def scan_oregonbuys(html, base, today, Document, absolute,
                    classify_title, standard_row, parse_date, clean):
    """Read visible public result table rows only, never surrounding page text.

    The publicly visible table columns in October 2026 are:
    bid#, bid#, organization, blanket#, blanket#, buyer, description,
    bid opening, awarded vendor, status, alternate ID.
    If OregonBuys changes the layout, skip it rather than mislabel another
    field as a bid or deadline.
    """
    doc = Document(html)
    seen = set()
    for tr in doc.root.findall("tr"):
        cells = _cells(tr)
        if len(cells) < 10:
            continue
        bidno = cells[1].text().strip() or cells[0].text().strip()
        if not BID_ID.fullmatch(bidno) or bidno in seen:
            continue
        title = clean(cells[6].text())
        agency = clean(cells[2].text())
        date_text = clean(cells[7].text())
        row_status = clean(cells[9].text()).lower()
        # In the public bid search "Sent" is a platform status, NOT proof
        # that proposals are currently being solicited.
        if not agency or not title or not date_text:
            continue
        if row_status not in {"sent", "open", "advertised", "active"}:
            continue
        if DISQUALIFY.search(title) or not classify_title(
                title, require_procurement=False):
            continue
        anchor = next((a for a in tr.findall("a")
                       if BID_ID.fullmatch(a.text().strip())
                       and a.attrs.get("href")), None)
        if anchor is None:
            continue
        url = absolute(base, anchor.attrs.get("href", ""))
        host = (urlsplit(url).hostname or "").lower()
        if host not in {"oregonbuys.gov", "www.oregonbuys.gov"}:
            continue
        opening_date = parse_date(date_text)
        if not opening_date:
            continue
        # A pre-solicitation's listed opening date is NOT an RFP submission
        # deadline; store it as reference only and label the stage precisely.
        preliminary = bool(PRE_NOTICE.search(title))
        entry = standard_row(title, agency, "OR", url, title,
                             "OregonBuys public bid search", today,
                             listing=True, observed_due=None)
        entry["source_kind"] = "public_bid_search"
        entry["status"] = ("Pre-solicitation / information notice — NOT an open RFP"
                           if preliminary else
                           "Public bid listing — confirm that proposals are being accepted")
        entry["opportunity_stage"] = (
            "pre_solicitation" if preliminary else "needs_open_status_review"
        )
        entry["bid_number"] = bidno
        entry["bid_opening_date"] = opening_date
        entry["due_date"] = None  # Search results alone do not verify proposal due date.
        entry["verified_on"] = today
        entry["priority"] = "REVIEW"
        seen.add(bidno)
        yield entry


def _link_for_heading(heading, base, absolute):
    for node in (heading, heading.parent):
        if not node:
            continue
        for a in node.findall("a"):
            url = absolute(base, a.attrs.get("href", ""))
            if url and urlsplit(url).hostname in {"wsdot.wa.gov", "www.wsdot.wa.gov"}:
                return url
        if node.tag == "a":
            url = absolute(base, node.attrs.get("href", ""))
            if url and urlsplit(url).hostname in {"wsdot.wa.gov", "www.wsdot.wa.gov"}:
                return url
    return ""


def scan_wsdot(html, base, today, Document, absolute,
               classify_title, standard_row, parse_date, clean):
    """Accept ONLY individually scoped WSDOT advertised consultant contracts.

    Public works / construction entries on the same page are never accepted.
    WSDOT can block automated fetches; the caller must log failures honestly.
    """
    doc = Document(html)
    seen = set()
    for heading in doc.root.findall():
        if heading.tag not in {"h2", "h3"}:
            continue
        title = clean(heading.text())
        if not title or DISQUALIFY.search(title):
            continue
        if not classify_title(title, require_procurement=False):
            continue
        url = _link_for_heading(heading, base, absolute)
        if not url or url == base or url in seen:
            continue
        # Scope the status to ONE result, not the entire WSDOT results page.
        container = heading.parent
        detail = ""
        for _ in range(6):
            if container is None:
                break
            headings = sum(1 for h in container.findall()
                           if h.tag in {"h2", "h3"})
            content = clean(container.text())
            if (headings == 1 and len(content) < 2800
                    and "Publication date:" in content
                    and "Submittal due:" in content):
                detail = content
                break
            if headings > 1:
                break
            container = container.parent
        if not detail:
            continue
        if not re.search(r"\bConsultant Services\b", detail, re.I):
            continue
        if re.search(r"\b(?:Public Works|Closed|Cancelled|Canceled|Awarded|Planned)\b",
                     detail, re.I):
            continue
        if not re.search(r"\bAdvertised\b", detail, re.I):
            continue
        due_match = WSDOT_DEADLINE.search(detail)
        due = parse_date(due_match.group(1)) if due_match else None
        if not due or due < today:
            continue
        publish_match = WSDOT_PUBLISHED.search(detail)
        published = parse_date(publish_match.group(1)) if publish_match else None
        entry = standard_row(title, "Washington State Department of Transportation",
                             "WA", url, title, "WSDOT consultant contracts",
                             today, listing=True, observed_due=due)
        entry["source_kind"] = "official_listing"
        entry["status"] = "WSDOT Consultant Services — Advertised; due date in listing"
        entry["opportunity_stage"] = "open_solicitation"
        entry["date_type"] = "Proposal submittal due"
        entry["published_date"] = published
        entry["verified_on"] = today
        seen.add(url)
        yield entry


def scan(source, html, today, Document, absolute, classify_title,
         standard_row, parse_date, clean):
    if source["kind"] == "oregonbuys_public":
        return list(scan_oregonbuys(html, source["url"], today, Document,
                                   absolute, classify_title, standard_row,
                                   parse_date, clean))
    if source["kind"] == "wsdot_contracts":
        return list(scan_wsdot(html, source["url"], today, Document,
                               absolute, classify_title, standard_row,
                               parse_date, clean))
    return []
