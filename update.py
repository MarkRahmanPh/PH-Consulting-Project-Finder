#!/usr/bin/env python3
"""PH Consulting official-first WA/OR opportunity watcher (Python 3.12, stdlib only).

Checks publicly accessible official listings, selected issuing-agency detail pages,
and optional RSS discovery feeds. Official dates are rechecked only when explicitly
present on a successfully fetched listing/detail page. Does not claim statewide
coverage or classify undisclosed deadlines as active. See README.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
import agency_sources as AS

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'opportunities.json'
TZ = ZoneInfo('America/Los_Angeles')
USER_AGENT = 'PH-Consulting-Project-Finder/6.0 (polite public procurement monitoring)'
OFFICIAL_INDEXES = [
    {'name': 'WA OMWBE public bid postings', 'state': 'WA', 'kind': 'omwbe',
     'url': 'https://omwbe.wa.gov/small-business-assistance/bids-contracting-opportunities'},
    {'name': 'WA WEBS public bid calendar', 'state': 'WA', 'kind': 'webs',
     'url': 'https://pr-webs-vendor.des.wa.gov/bidcalendar.aspx'},
    {'name': 'OR Port of Coos Bay solicitations', 'state': 'OR', 'kind': 'coos',
     'url': 'https://www.portofcoosbay.com/solicitations-public-notices'},
]
# Detailed checks only for issuing-agency/public procurement pages, not third-party news.
ALLOWED_DETAIL_HOSTS = {
    'www.portofcoosbay.com', 'portofcoosbay.com',
    'omwbe.wa.gov', 'www.omwbe.wa.gov',
    'www.shoalwaterbay-nsn.gov', 'shoalwaterbay-nsn.gov',
}
# Search phrases reflect PH Consulting's eight approved practice areas.
# Source/title classification below is stricter than queries: a query hit alone
# NEVER qualifies an opportunity for inclusion.
QUERIES = {
    'WA': [
        ('signal', 'Washington "signal timing" OR "traffic engineering" RFQ consultant'),
        ('signal', 'Washington "signal coordination" "controller" RFP'),
        ('its', 'Washington "ITS" "ATSPM" OR "transit signal priority" consultant RFP'),
        ('its', 'Washington "traffic signal preemption" "detection" RFQ'),
        ('rail', 'Washington "railroad crossing" "grade separation" RFQ engineering'),
        ('rail', 'Washington "quiet zone" "FRA" "RCE" consultant'),
        ('ada', 'Washington "ADA curb ramps" "pedestrian crossings" design RFQ'),
        ('ada', 'Washington "accessible pedestrian signals" RFP'),
        ('civil', 'Washington "roadway design" "intersection improvements" engineering RFQ'),
        ('civil', 'Washington "civil engineering" "roadway" on-call RFQ'),
        ('safety', 'Washington "SS4A" "crash analysis" safety action plan consultant'),
        ('safety', 'Washington "HSIP" "speed management" traffic safety RFQ'),
        ('planning', 'Washington "traffic impact study" "transportation planning" RFQ'),
        ('planning', 'Washington "traffic modeling" "corridor study" consultant'),
        ('transit', 'Washington "transit operations" "freight corridor" planning RFP'),
        ('transit', 'Washington "port transportation" "multimodal study" RFQ'),
    ],
    'OR': [
        ('signal', 'Oregon "traffic signal timing" "MAXTIME" RFQ engineering'),
        ('its', 'Oregon "ITS" "ATSPM" "TSP" consultant RFP'),
        ('rail', 'Oregon "railroad crossing" "rail safety" FRA RFQ'),
        ('rail', 'Oregon "grade separation" "quiet zone" engineering study'),
        ('ada', 'Oregon "ADA curb ramps" "pedestrian" consultant RFQ'),
        ('civil', 'Oregon "roadway design" "civil engineering" on-call RFQ'),
        ('safety', 'Oregon "SS4A" "HSIP" "crash analysis" RFP'),
        ('planning', 'Oregon "transportation system plan" "traffic impact" consultant'),
        ('transit', 'Oregon "transit operations" "freight corridor" RFQ'),
    ],
}

# Rules examine a SINGLE procurement TITLE, never an entire list page.
# Words such as 'engineering', 'design', 'planning', 'ADA', and 'safety' alone
# are too generic to establish a PH Consulting specialty.
PROCUREMENT = re.compile(
    r"\b(?:RFP|RFQ|RSOQ|SOQ|request for (?:qualifications|proposals)|on[ -]?call|"
    r"professional services|consultant|engineering(?: services| and design|/design)?|"
    r"design(?: services)?|stud(?:y|ies)|planning|prequalification|roster|PS&E)\b", re.I)
UNRELATED = re.compile(
    r"\b(?:storm\s*water|stormwater|wastewater|sewer|water treatment|WTP|"
    r"wetland|stream services|broadband|core\s*fiber|fiber optic network|"
    r"recruitment|human resources|staffing|employee|employment|"
    r"gender dysphoria|healthcare|medical facility|sports medicine|"
    r"school building|school replacement|elementary school|Husky Hall|"
    r"equine|arena|housing replacement|housing construction|"
    r"readiness center|electrical maintenance|building renovation|"
    r"janitorial|IT services|software licensing|"
    r"paratransit (?:eligibility|assessment)|ADA assessment for paratransit|"
    r"construction only|construction-only|ITB|invitation to bid|"
    r"bid tabulation|equipment purchase|waterfront property RFP)\b", re.I)

# PH seeks design, signal/ITS, study, planning and engineering consulting work.
# A construction bid, construction management-only RFQ, or agency guidance page
# is NOT a consulting design opportunity, even when its subject is a roadway,
# railroad crossing, pedestrian signal or safety improvement.
CONSTRUCTION_DELIVERY_ONLY = re.compile(
    r"\b(?:construction[ -]only|construction management|construction inspection|"
    r"construction administration|construction oversight|construction supervision|"
    r"construction engineering and inspection|CE[&/]I|CM[&/]GC|CMAR|"
    r"resident engineer(?:ing)?|contractor prequalification|general contractor|"
    r"invitation (?:to|for) bid(?:s)?|invitation to tender|advertisement for bids|"
    r"request for bids|bid for construction|construction bids?|"
    r"construction contracts?|construction of|roadway construction|"
    r"bridge construction|paving contract|construction procurement|"
    r"construction[- ]phase services|construction[- ]phase support)\b", re.I)
# Design scope must be explicit to retain projects with both design and CM.
DESIGN_SCOPE_WITH_CM = re.compile(
    r"\b(?:design services|design and (?:engineering|construction management|"
    r"construction administration)|engineering design|design engineering|"
    r"engineering and design|design plans?|plans? and specifications|"
    r"preliminary engineering|PS[&/]E|signal timing|retiming|"
    r"signal coordination|ATSPM|traffic modeling|safety study|"
    r"traffic study|traffic analysis|engineering study|feasibility study)\b", re.I)
CONSTRUCTION_PROCUREMENT = re.compile(
    r"\b(?:construction of|construction[- ]only|construction contracts?|"
    r"construction bids?|bid for construction|request for bids|"
    r"advertisement for bids|invitation to bid|"
    r"invitation for bids|contractor prequalification|general contractor)\b", re.I)
NON_SOLICITATION_PATHS = (
    '/engineering-standards/planning-guidance/',
    '/hillsboro-major-projects/',
)
def excluded_non_consulting(title, url=''):
    """Exclude construction-only procurement and non-solicitation project pages.

    Design-plus-construction management is eligible when actual design work is
    named; pure construction management/inspection and contractor-led bids are not.
    """
    label = clean(title)
    location = (url or '').lower()
    if any(part in location for part in NON_SOLICITATION_PATHS):
        return True
    if CONSTRUCTION_DELIVERY_ONLY.search(label):
        if CONSTRUCTION_PROCUREMENT.search(label):
            return True  # Contractor procurement, even if called design-build.
        if not DESIGN_SCOPE_WITH_CM.search(label):
            return True
    if re.search(r"\bdesign[ -]build\b", label, re.I):
        # Usually a construction contract for a design-builder, not an RFQ for
        # independent PH engineering services.
        if not re.search(r"\b(?:engineering design services|consultant design services|"
                         r"design consultant services)\b", label, re.I):
            return True
    return False


# Specific matches, ranked when a title spans multiple disciplines.
# Signal design + pedestrian access is signal unless the procurement is
# primarily ADA. Freight rail infrastructure belongs to Railroad / FRA / RCE.
FIT_RULES = [
    ('rail', re.compile(
        r"\b(?:railroad|railway|rail line|rail crossing|grade separations?|quiet zones?|"
        r"rail infrastructure|rail rehabilitation|rail signal|freight rail|BNSF|"
        r"CRISI|railroad crossing elimination|RCE program|CBRL|rail feasibility|"
        r"rail safety|rail grade crossings?|rail track|railway crossing|"
        r"on.dock rail|rail bridge|FRA[ -]funded)\b", re.I)),
    ('its', re.compile(
        r"\b(?:intelligent transportation systems?|ITS|ATSPM|ATMS|"
        r"adaptive signals?|adaptive signal control|transit signal priority|"
        r"bus priority|next gen(?:eration)? TSP|TSP|emergency (?:vehicle )?preemption|"
        r"signal preemption|traffic (?:signal )?detection|signal communications?|"
        r"traffic communications?|connected vehicle|traffic management center|"
        r"traffic signal systems? integration|traffic signal communications?)\b", re.I)),
    ('signal', re.compile(
        r"\b(?:traffic signals?|signal timing|signal retiming|signal coordination|"
        r"signal optimization|signal controllers?|controller programming|"
        r"controller upgrades?|signal designs?|signalized intersections?|"
        r"MAXTIME|Econolite|Cobalt EOS|ASC/3|FYA|PPLT|"
        r"leading pedestrian intervals?|LPI|traffic engineering|"
        r"traffic operations?|traffic counts?|traffic calming|"
        r"intersection (?:operations?|signal|timing)\b)", re.I)),
    ('ada', re.compile(
        r"\b(?:ADA (?:curb ramps?|sidewalks?|pedestrian|accessibility|"
        r"improvements?|compliance|ramps?)|accessible pedestrian signals?|"
        r"pedestrian (?:crossings?|improvements?|safety|accessibility|signals?)|"
        r"crosswalk improvements?|sidewalk improvements?|"
        r"curb ramps?|bicycle (?:improvements?|facilities|lanes?)|"
        r"RRFB|rectangular rapid flashing beacon|"
        r"safe routes to school|pedestrian and bicycle|pedestrian/bicycle|"
        r"shared[ -]use (?:path|trail)|multi[ -]use (?:path|trail)|"
        r"bicycle and pedestrian (?:path|trail|improvements?))\b", re.I)),
    ('safety', re.compile(
        r"\b(?:SS4A|safe streets(?: and roads for all)?|HSIP|"
        r"highway safety improvement|safety action plan|"
        r"traffic safety|roadway safety|road safety|"
        r"systemic (?:intersection |traffic |roadway )?safety|"
        r"crash analysis|crash reduction|speed management|"
        r"intersection safety|vision zero|safety studies|"
        r"safety study|traffic (?:safety )?audit|road safety audit)\b", re.I)),
    ('civil', re.compile(
        r"\b(?:roadway (?:engineering|design|improvements?|rehabilitation|reconstruction)|"
        r"road (?:design|engineering|reconstruction|rehabilitation|improvements?|slide repair)|"
        r"street (?:improvements?|design|reconstruction|rehabilitation)|"
        r"street[s]?cape|civil engineering|"
        r"intersection (?:improvements?|redesign|reconstruction|design)|"
        r"roadway signing|traffic signs? (?:and|&) (?:pavement )?markings?|"
        r"pavement markings?|street lighting|roadway lighting|"
        r"complete streets|multimodal corridor (?:design|improvements?)|"
        r"roadway (?:PS&E|construction documents))\b", re.I)),
    ('transit', re.compile(
        r"\b(?:transit (?:operations?|planning|stud(?:y|ies)|development plans?|"
        r"service planning|priority studies)|"
        r"freight (?:corridors?|stud(?:y|ies)|planning|operations?|transportation)|"
        r"port transportation|port traffic|terminal (?:planning|traffic impact|traffic stud(?:y|ies))|"
        r"intermodal (?:port|terminal|freight|stud(?:y|ies)|planning)|"
        r"multimodal (?:stud(?:y|ies)|transportation)|"
        r"goods movement|truck route studies|rail freight (?:operations?|stud(?:y|ies)|planning))\b", re.I)),
    ('planning', re.compile(
        r"\b(?:transportation (?:system|safety|options|land.use|development|master) "
        r"plans?|transportation planning|transportation system planning|"
        r"transportation system plans?|transportation master plans?|"
        r"traffic impact (?:stud(?:y|ies)|analysis)|"
        r"traffic (?:stud(?:y|ies)|forecasting|forecast|modeling|models?|analysis|assessment)|"
        r"travel demand modeling|transportation forecasting|"
        r"transportation (?:stud(?:y|ies)|modeling|forecast|analysis)|"
        r"corridor (?:stud(?:y|ies)|planning|analysis|design|improvements?)|"
        r"multimodal (?:planning|stud(?:y|ies))|"
        r"Synchro|VISSIM|Aimsun|Capitol Corridor Phase|"
        r"WSDOT Consultant Prequalification)\b", re.I)),

]
FEED_EXCLUDE = re.compile(r"\b(?:job posting|hiring|contract award|awarded to|ceremony|grand opening|"
    r"meeting agenda|press release|construction underway|bid tabulation)\b", re.I)
DATE_NUM = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b')
MONTHS = r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)'
DATE_LONG = re.compile(r'\b(' + MONTHS + r')\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b', re.I)
# Only date in explicit deadline field counts as verified.
DEADLINE = re.compile(r'(?:submission deadline|closing date|proposal(?:s)? due|responses? due|qualifications due|SOQs? due|bid closing date|solicitation close date|due date|deadline)\s*[:\-–]?\s*(.{0,110})', re.I)
ADDENDA = re.compile(r'\baddend(?:um|a)\b', re.I)
TAG = re.compile(r'<[^>]+>')


def clean(s):
    return re.sub(r'\s+', ' ', unescape(s or '')).strip()


def ident(url):
    # Queryless URL is stable even when a title/addendum changes.
    p = urllib.parse.urlsplit(url)
    normalized = (p.netloc.lower() + p.path.rstrip('/').lower())
    return 'official-' + hashlib.sha1(normalized.encode()).hexdigest()[:18]


def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/rss+xml,application/xml,*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(1_500_000).decode('utf-8', 'replace')


class Node:
    def __init__(self, tag='', attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs or []), parent
        self.children = []

    def text(self):
        return clean(' '.join(c if isinstance(c, str) else c.text() for c in self.children))

    def findall(self, tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.findall(tag)


class Document(HTMLParser):
    VOID = set('area base br col embed hr img input link meta param source track wbr'.split())
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node('root')
        self.current = self.root
        self.skip = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        cursor = self.current
        while cursor and cursor.tag != tag:
            cursor = cursor.parent
        if cursor and cursor.parent:
            self.current = cursor.parent

    def handle_data(self, text):
        if self.current.tag not in {'script', 'style', 'noscript'}:
            self.current.children.append(text)


def absolute(base, href):
    u = urllib.parse.urljoin(base, href or '')
    p = urllib.parse.urlsplit(u)
    if p.scheme != 'https' or not p.netloc:
        return ''
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))


def wrapper(node):
    c = node
    for _ in range(9):
        if not c: break
        cls = c.attrs.get('class', '')
        if c.tag in ('tr', 'article', 'li') or re.search(r'views-row|listing|result|bid[-_ ]item', cls, re.I):
            return c
        c = c.parent
    return node.parent or node


def parse_date(text):
    text = clean(text)
    m = DATE_LONG.search(text)
    if m:
        month = m.group(1).replace('.', '')[:3].title()
        try: return datetime.strptime(f'{month} {m.group(2)} {m.group(3)}', '%b %d %Y').date().isoformat()
        except ValueError: pass
    m = DATE_NUM.search(text)
    if m:
        yr = int(m.group(3)); yr = (2000 + yr) if yr < 100 else yr
        try: return date(yr, int(m.group(1)), int(m.group(2))).isoformat()
        except ValueError: pass
    return None


def deadline(text, listing=False):
    for m in DEADLINE.finditer(text):
        found = parse_date(m.group(1))
        if found: return found
    # OMWBE listing and WEBS calendars show unlabelled closing dates per row.
    if listing: return parse_date(text)
    return None


def classify_title(title, summary='', require_procurement=True):
    """Return exactly one PH discipline or None. NEVER use page-wide text as title.

    Summary is accepted ONLY for manual/curated records and must never rescue an
    unrelated title. This guards against adjacent OMWBE listings contaminating rows.
    """
    title = clean(title)[:260]
    if not title or len(title) < 9 or UNRELATED.search(title) or FEED_EXCLUDE.search(title) or excluded_non_consulting(title):
        return None
    if title.lower().startswith(('request for proposal no. rfp260903',)):
        return None
    # A vague engineering, safety, design or ADA title is NOT sufficient.
    cat = next((name for name, rule in FIT_RULES if rule.search(title)), None)
    if cat is None: return None
    # A public official RFQ index is procurement-related, but a generic project
    # description still needs a procurement/service indicator to stay on the list.
    if require_procurement and not PROCUREMENT.search(title):
        return None
    return cat


def category(text):
    return classify_title(text, require_procurement=False)


def is_relevant(text):
    return classify_title(text, require_procurement=True) is not None


def is_strictly_relevant_record(row):
    title = row.get('title', '')
    # Do not keep general guidance webpages as open procurement opportunities.
    u = (row.get('url') or '').lower()
    if excluded_non_consulting(title, u):
        return False
    # Manually curated seeded records may omit RFP/RFQ words, but must contain an
    # unequivocal traffic/transport/rail/roadway subject in their own title.
    return classify_title(title, require_procurement=False) is not None


def single_title_date(title):
    """An OMWBE result's own link text may have a trailing deadline."""
    matches = list(DATE_NUM.finditer(title)) + list(DATE_LONG.finditer(title))
    if len(matches) == 1:
        match = matches[0]
        if match.end() >= len(title.strip()) - 7:
            return parse_date(match.group(0))
    return None


def remove_trailing_date(title):
    return clean(re.sub(r'\s*(?:\d{1,2}/\d{1,2}/\d{2,4})\s*$', '', title))


def priority(text):
    return 'HIGH' if re.search(r'\b(signal timing|traffic engineering|railroad|rail crossing|ATSPM|on-call traffic|traffic study|ADA curb ramp)\b', text, re.I) else 'REVIEW'


def standard_row(title, agency, state, url, body, source, today, listing=False,
                 observed_due=None):
    due = observed_due if listing else deadline(body, listing=False)
    cat = classify_title(title, require_procurement=False)
    return dict(id=ident(url), state=state, category=cat, agency=agency, title=title[:200],
                summary=clean(body)[:410], priority=priority(title),
                url=url, source=source, source_kind='official_listing',
                status='Official listing — deadline observed' if due else 'Official listing — deadline unverified',
                due_date=due, due_time='', role='Review prime/subconsultant fit',
                verified_on=today if due else None, last_seen=today, addenda_count=None)


def safe_single_item_scope(a, url):
    """Only use surrounding metadata if a tight ancestor has ONE bid-link.

    This prevents unrelated titles and deadlines being borrowed from neighboring
    OMWBE notices through a shared parent list/container.
    """
    c = a.parent
    for _ in range(5):
        if c is None: break
        other = [node for node in c.findall('a')
                 if '/bid-opportunities/' in (node.attrs.get('href', '') or '')]
        if len(other) == 1 and c.tag in ('tr', 'li', 'article', 'div'):
            text = c.text()
            if len(text) < 650: return text
        if len(other) > 1: break
        c = c.parent
    return a.text()


def safe_listing_due(title, body):
    # An unlabeled date is reliable only when attached to this particular link.
    result = single_title_date(title)
    if result: return result
    explicit = deadline(body, listing=False)
    if explicit: return explicit
    matches = list(DATE_NUM.finditer(body)) + list(DATE_LONG.finditer(body))
    if len(matches) == 1 and len(body) < 330:
        return parse_date(matches[0].group(0))
    return None


def scan_omwbe(html, base, today):
    doc = Document(html)
    seen = set()
    for a in doc.root.findall('a'):
        url = absolute(base, a.attrs.get('href', ''))
        p = urllib.parse.urlsplit(url)
        if p.netloc not in ('omwbe.wa.gov', 'www.omwbe.wa.gov') or not p.path.startswith('/bid-opportunities/'):
            continue
        raw_title = a.text()
        if len(raw_title) < 10 or raw_title.lower().startswith(('read more', 'details')):
            continue
        title = remove_trailing_date(raw_title)
        if not classify_title(title, require_procurement=True) or url in seen:
            continue
        seen.add(url)
        local_text = safe_single_item_scope(a, url)
        due = safe_listing_due(raw_title, local_text)
        # Summary should NEVER contain an entire list of unrelated advertisements.
        yield standard_row(title, 'Agency named in notice — check source', 'WA', url,
                           title, 'WA OMWBE official bid listing', today,
                           listing=True, observed_due=due)


def scan_webs(html, base, today):
    doc = Document(html)
    for tr in doc.root.findall('tr'):
        anchors = [a for a in tr.findall('a') if a.text().strip()]
        if not anchors: continue
        candidate = next((a for a in sorted(anchors, key=lambda x: len(x.text()), reverse=True)
                          if classify_title(remove_trailing_date(a.text()))), None)
        if candidate is None: continue
        title = remove_trailing_date(candidate.text())
        url = absolute(base, candidate.attrs.get('href', ''))
        if not url: continue
        due = safe_listing_due(candidate.text(), tr.text()[:450])
        yield standard_row(title, 'WA WEBS (see notice for agency)', 'WA', url,
                           title, 'WA WEBS public calendar', today,
                           listing=True, observed_due=due)


def scan_coos(html, base, today):
    doc = Document(html)
    seen = set()
    for a in doc.root.findall('a'):
        url = absolute(base, a.attrs.get('href', ''))
        p = urllib.parse.urlsplit(url)
        if p.netloc not in ('portofcoosbay.com', 'www.portofcoosbay.com'): continue
        if '/request-for-proposals-' not in p.path: continue
        title = a.text()
        if url in seen or not classify_title(title): continue
        seen.add(url)
        yield standard_row(title, 'Oregon International Port of Coos Bay', 'OR', url, title,
                           'Port of Coos Bay official solicitations', today)


def official_detail(html, row, today):
    doc = Document(html)
    main = next(iter(doc.root.findall('main')), None)
    if main is None:
        main = next(iter(doc.root.findall('article')), None)
    if main is None:
        main = next(iter(doc.root.findall('body')), doc.root)
    text = main.text()
    if len(text) < 60: return None
    # Some issuing agencies display navigation within main, but require an explicit deadline label.
    due = deadline(text)
    # Article-specific amendment links; do not misread links to generic help pages.
    addenda = set()
    for a in main.findall('a'):
        if ADDENDA.search(a.text()):
            u = absolute(row['url'], a.attrs.get('href', ''))
            if u: addenda.add(u)
    if not addenda:
        # HTML document may identify addenda without a linked PDF.
        mentions = re.findall(r'\b(?:addendum|addenda)\s*\d+\b', text, re.I)
        addenda = {clean(x).lower() for x in mentions}
    return {'due_date': due, 'addenda_count': len(addenda),
            'category': classify_title(row.get('title', ''), require_procurement=False),
            'detail_excerpt': text[:410], 'verified_on': today}


def google_news(query):
    qs = urllib.parse.quote(query + ' when:30d')
    return 'https://news.google.com/rss/search?q=' + qs + '&hl=en-US&gl=US&ceid=US:en'


def parse_feed(html, state, cat, today):
    root = ET.fromstring(html)
    for item in root.findall('.//item')[:25]:
        title = clean(item.findtext('title'))
        desc = clean(TAG.sub(' ', item.findtext('description') or ''))
        url = clean(item.findtext('link'))
        if not title or not url.startswith('https://') or not classify_title(title, require_procurement=True): continue
        stamp = item.findtext('pubDate')
        if stamp:
            try:
                if (date.fromisoformat(today) - parsedate_to_datetime(stamp).date()).days > 35: continue
            except (ValueError, TypeError, OverflowError): pass
        rid = 'feed-' + hashlib.sha1((title.lower() + '|' + url).encode()).hexdigest()[:18]
        yield dict(id=rid, title=title[:190], agency='Not confirmed', state=state, category=classify_title(title, require_procurement=False) or cat,
                   summary=desc[:330] or 'Discovery result; check issuing agency notice.', priority='REVIEW',
                   url=url, source='Google News RSS — discovery only', source_kind='news_feed',
                   status='Unverified lead — not confirmed open', role='Review relevance',
                   due_date=None, due_time='', verified_on=None, found=today, last_seen=today)


def load_prior():
    if not OUTPUT.exists(): return [], {}
    try:
        data = json.loads(OUTPUT.read_text(encoding='utf-8'))
        return data.get('items', []), data
    except (OSError, ValueError): return [], {}


def allowed_detail(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.hostname not in ALLOWED_DETAIL_HOSTS: return False
    if p.hostname and 'portofcoosbay' in p.hostname: return '/request-for-proposals-' in p.path
    if p.hostname and 'omwbe' in p.hostname: return p.path.startswith('/bid-opportunities/')
    if p.hostname and 'shoalwaterbay' in p.hostname: return '/requests-for-proposal/' in p.path
    return False


def merge_prior(prior, reset_legacy_dates=False):
    # Existing 2026-10-11 baseline is not treated as a fresh confirmed scrape.
    result = {}
    for row in prior:
        if not isinstance(row, dict) or not row.get('id') or not is_strictly_relevant_record(row): continue
        row = dict(row)
        if row.get('source_kind') is None:
            row['source_kind'] = 'existing_watchlist' if row.get('source', '').startswith('Official') else 'news_feed'
            row['status'] = ('Previously recorded — recheck notice' if row['source_kind'] == 'existing_watchlist'
                             else 'Unverified lead — not confirmed open')
        row.setdefault('first_seen', row.get('found') or '2026-10-11')
        row['category'] = classify_title(row.get('title',''), require_procurement=False)
        # Previous versions scraped combined OMWBE listing text and falsely flagged
        # deadline changes. Never carry that fabricated history into this release.
        if reset_legacy_dates and row.get('source', '').startswith(('WA OMWBE', 'WA WEBS')):
            if row.get('change_type') == 'DEADLINE CHANGED':
                row['change_type'] = ''
                row.pop('previous_due_date', None)
                row.pop('change_on', None)
            row['summary'] = clean(row.get('title',''))[:410]
            # These historical dates were parsed from adjacent bid listings;
            # remove until the safer v4 parser observes this exact entry's date.
            row['due_date'] = None
            row['verified_on'] = None
            row['status'] = 'Deadline needs recheck on the issuing notice'
        result[row['id']] = row
    return result


def apply_observation(rows, observation, today):
    url = observation.get('url')
    # If the legacy watchlist entry uses a different id, preserve it rather than showing duplicates.
    previous = next((v for v in rows.values() if v.get('url', '').rstrip('/') == (url or '').rstrip('/') and
                     v.get('source_kind') != 'news_feed'), None)
    old = previous or rows.get(observation['id'])
    if old:
        row = dict(old)
        row.update({k: v for k, v in observation.items() if v is not None and k not in ('id', 'found')})
        row['id'] = old['id']
        row['first_seen'] = old.get('first_seen', old.get('found', today))
        # Never discard an existing due date merely because a listing omitted it.
        if not observation.get('due_date'):
            row['due_date'] = old.get('due_date')
            row['status'] = 'Official listing found — deadline requires review'
        if old.get('due_date') and observation.get('due_date') and old['due_date'] != observation['due_date']:
            row['change_type'] = 'DEADLINE CHANGED'
            row['previous_due_date'] = old['due_date']
            row['change_on'] = today
        else:
            # Keep recent changes visible for 7 days; don't reset them each run.
            if row.get('change_on') and (date.fromisoformat(today) - date.fromisoformat(row['change_on'])).days > 7:
                row['change_type'] = ''
        rows[row['id']] = row
    else:
        row = dict(observation)
        row['first_seen'] = today
        row['found'] = today
        row['change_type'] = 'NEWLY FOUND'
        row['change_on'] = today
        rows[row['id']] = row
    return rows[row['id']]


def check_details(rows, today, logs):
    # Avoid fetching unlimited new discoveries; selected official listings only.
    candidates = [v for v in rows.values() if v.get('source_kind') != 'news_feed'
                  and allowed_detail(v.get('url', ''))]
    candidates.sort(key=lambda x: (x.get('state') != 'WA', x.get('due_date') or '9999-12-31'))
    for row in candidates[:35]:
        try:
            result = official_detail(fetch(row['url']), row, today)
            if not result: continue
            old_due = row.get('due_date')
            new_due = result['due_date']
            old_count = row.get('addenda_count')
            if new_due:
                if old_due and old_due != new_due:
                    row['change_type'] = 'DEADLINE CHANGED'
                    row['previous_due_date'] = old_due
                    row['change_on'] = today
                row['due_date'] = new_due
                row['verified_on'] = today
                row['status'] = 'Issuing notice checked — deadline observed'
            elif row.get('source_kind') == 'existing_watchlist':
                row['status'] = 'Issuing notice checked — deadline needs review'
            if old_count is not None and result['addenda_count'] > old_count and row.get('change_type') != 'DEADLINE CHANGED':
                row['change_type'] = 'ADDENDUM POSTED'
                row['change_on'] = today
            row['addenda_count'] = result['addenda_count']
            row['category'] = result['category']
            row['last_seen'] = today
            row['source_kind'] = 'official_detail'
            logs.append({'source': row['title'][:55], 'ok': True})
        except Exception as exc:
            logs.append({'source': row['title'][:55], 'ok': False, 'error': type(exc).__name__})


def classify_expiry(rows, today):
    d = date.fromisoformat(today)
    for rid, row in list(rows.items()):
        due = row.get('due_date')
        try: expired = bool(due and date.fromisoformat(due) < d)
        except ValueError: expired = False
        if expired:
            if row.get('status') != 'Deadline passed (based on stored date)' and row.get('change_type') != 'EXPIRED':
                row['change_type'] = 'EXPIRED'
                row['change_on'] = today
            row['status'] = 'Deadline passed (based on stored date)'
            row['expired'] = True
            if (d - date.fromisoformat(due)).days > 60:
                del rows[rid]
        else:
            row['expired'] = False
        # Cap stale unverified RSS leads. Never label them official/active.
        if row.get('source_kind') == 'news_feed':
            try:
                if (d - date.fromisoformat(row.get('first_seen') or row.get('found'))).days > 30:
                    del rows[rid]
            except (TypeError, ValueError): pass




def update_agency_directories(catalog,old_data,today):
    """Fetch up to four official jurisdiction directories once per week.

    City profiles are official-directory metadata, not proof that the municipal
    procurement portal has been checked. Failure never deletes prior agencies.
    """
    previous=old_data.get('catalog_last_refresh', '')
    if previous:
        try:
            if (date.fromisoformat(today)-date.fromisoformat(previous)).days<7:
                return old_data.get('directory_checks', [])
        except ValueError:pass
    checks=[]
    for source in AS.DIRECTORIES:
        try:
            html=fetch(source['url'],timeout=8)
            found=AS.parse_directory(html,source,Document,absolute)
            for a in found:
                old=catalog.get(a['id'])
                if old:
                    if a.get('website') and not old.get('website'):old['website']=a['website']
                    if a.get('profile_url') and not old.get('profile_url'):old['profile_url']=a['profile_url']
                else:catalog[a['id']]=a
            checks.append({'source':source['name'],'url':source['url'],'ok':True,'found':len(found),'checked':today})
        except Exception as e:
            checks.append({'source':source['name'],'url':source['url'],'ok':False,'error':type(e).__name__,'checked':today})
    return checks


def scan_local_agencies(catalog,rows,today):
    """Rotate through city/county/state/port/transit sites, WA weighted 65%.

    No invented URLs. If directory profiles have no site URL, status remains
    pending; if a vendor login is needed, status is manual review. For each
    agency, only its own bid page is parsed, not adjoining bid listings.
    """
    try:batch=max(0,min(40,int(os.getenv('PH_AGENCY_BATCH','18'))))
    except ValueError:batch=18
    report=[]
    selected=AS.selected_agencies(catalog,today,batch)
    for agency in selected:
        site=agency.get('website') or ''
        profile=agency.get('profile_url') or ''
        status='No official website in directory yet'; err=''; found=0; checked_url=''
        try:
            if not site and profile:
                profile_html=fetch(profile,timeout=7)
                site=AS.external_website_from_profile(profile_html,profile,Document,absolute)
                if site:agency['website']=site
                else: status='Directory profile did not expose a reliable site URL'
            if site:
                # Do not try to bypass supplier login portals or scrape pages
                # that only expose client-side JS API data.
                if any(d in (urllib.parse.urlsplit(site).hostname or '') for d in AS.PORTAL_HOSTS):
                    status='Supplier portal — manual review';checked_url=site
                else:
                    proc=agency.get('procurement_url') or ''
                    if proc and any(x in (urllib.parse.urlsplit(proc).hostname or '') for x in AS.PORTAL_HOSTS):
                        status='Supplier portal — manual review';checked_url=proc
                    else:
                        homepage=fetch(site,timeout=7)
                        checked_url=site
                        if not proc:
                            proc=AS.find_procurement_page(homepage,site,Document,absolute)
                            if proc:agency['procurement_url']=proc
                        html=homepage
                        if proc and proc!=site:
                            if any(x in (urllib.parse.urlsplit(proc).hostname or '') for x in AS.PORTAL_HOSTS):
                                status='Supplier portal — manual review';checked_url=proc
                            else:
                                html=fetch(proc,timeout=7)
                                checked_url=proc
                        # No general-homepage scanning: only a discoverable bid page
                        # is a defensible procurement listing.
                        if status!='Supplier portal — manual review' and proc:
                            results=AS.scan_agency_bids(html,checked_url,agency,Document,absolute,
                                classify_title,safe_single_item_scope,safe_listing_due,
                                remove_trailing_date,standard_row,today)
                            for item in results:apply_observation(rows,item,today)
                            found=len(results)
                            status='Official procurement page accessed'
                        elif status!='Supplier portal — manual review':
                            status='Official website accessed — no public bids link found'
        except Exception as exc:
            err=type(exc).__name__
            status='Inaccessible / retry next rotation'
        agency['last_check']=today
        agency['last_check_at']=datetime.now(TZ).isoformat()
        agency['status']=status
        agency['last_matches']=found
        report.append({'agency':agency['name'],'state':agency['state'],'kind':agency['kind'],
                       'source':checked_url or agency.get('profile_url',''),
                       'ok':status.startswith('Official'),
                       'attempted':bool(site or profile),
                       'status':status,'matches':found,**({'error':err} if err else {})})
    return report


def coverage_summary(catalog,agency_checks,directory_checks):
    all_agencies=list(catalog.values())
    checked=[a for a in all_agencies if a.get('last_check')]
    successful=[a for a in all_agencies if a.get('status','').startswith('Official')]
    return {'total':len(all_agencies),
            'wa':sum(a.get('state')=='WA' for a in all_agencies),
            'or':sum(a.get('state')=='OR' for a in all_agencies),
            'cities':sum(a.get('kind')=='city' for a in all_agencies),
            'counties':sum(a.get('kind')=='county' for a in all_agencies),
            'checked_ever':len(checked),'accessible_ever':len(successful),
            'attempted_this_run':sum(x.get('attempted',False) for x in agency_checks),
            'accessible_this_run':sum(x['ok'] for x in agency_checks),
            'matches_this_run':sum(x['matches'] for x in agency_checks),
            'directories_accessible':sum(x.get('ok',False) for x in directory_checks),
            'directories_total':len(AS.DIRECTORIES),
            'note':('Agency directory targets are NOT all scanned every run. Only rotating batches '
                    'are checked. Some cities require portal accounts; some directory sites do not '
                    'expose websites to automated tools. Coverage and lead status are best-effort.')}

def main():
    now = datetime.now(TZ)
    today = os.environ.get('PH_TEST_DATE') or now.date().isoformat()
    prior, old_data = load_prior()
    rows = merge_prior(prior, reset_legacy_dates=old_data.get('parser_version') != 5)
    removed_irrelevant = len(prior) - len(rows)
    logs = []
    seen = set()
    catalog = AS.seeded_catalog(old_data.get('agency_catalog', []))
    directory_checks = list(old_data.get('directory_checks', []))
    agency_checks = []
    if os.environ.get('PH_OFFLINE') != '1':
        directory_checks = update_agency_directories(catalog, old_data, today)
        agency_checks = scan_local_agencies(catalog, rows, today)
        for source in OFFICIAL_INDEXES:
            try:
                html = fetch(source['url'])
                parsers = {'omwbe': scan_omwbe, 'webs': scan_webs, 'coos': scan_coos}
                results = list(parsers[source['kind']](html, source['url'], today))
                for result in results:
                    row = apply_observation(rows, result, today)
                    seen.add(row['id'])
                logs.append({'source': source['name'], 'ok': True, 'matches': len(results)})
            except Exception as exc:
                logs.append({'source': source['name'], 'ok': False, 'error': type(exc).__name__})
        check_details(rows, today, logs)
        # Feed leads are intentionally separate from agency-verified opportunities.
        for state, searches in QUERIES.items():
            for cat, q in searches:
                try:
                    parsed = list(parse_feed(fetch(google_news(q), timeout=8), state, cat, today))
                    for result in parsed[:5]:
                        if result['id'] not in rows: apply_observation(rows, result, today)
                except Exception:
                    pass
    classify_expiry(rows, today)
    records = sorted(rows.values(), key=lambda r: (
        bool(r.get('expired')), r.get('state') != 'WA', r.get('priority') != 'HIGH',
        r.get('due_date') or '9999-12-31', r.get('title', '').lower()))
    # Search-feed cap; preserve official listing and previously manually recorded rows.
    feed = [r for r in records if r.get('source_kind') == 'news_feed']
    if len(feed) > 60:
        keep = {r['id'] for r in sorted(feed, key=lambda r: r.get('first_seen', ''), reverse=True)[:60]}
        records = [r for r in records if r.get('source_kind') != 'news_feed' or r['id'] in keep]
    passed = sum(bool(r.get('expired')) for r in records)
    cover = coverage_summary(catalog, agency_checks, directory_checks)
    payload = {
        'parser_version': 6,
        'updated_pacific': now.strftime('%b %d, %Y %I:%M %p %Z'),
        'last_run_iso': now.isoformat(),
        'official_sources_checked': sum(x['ok'] for x in logs if x['source'] in [s['name'] for s in OFFICIAL_INDEXES]),
        'official_sources_total': len(OFFICIAL_INDEXES),
        'source_checks': logs,
        'agency_coverage': cover,
        'agency_catalog': sorted(catalog.values(), key=lambda a: (a.get('state') != 'WA', a.get('kind',''), a.get('name',''))),
        'directory_checks': directory_checks,
        'agency_checks': agency_checks,
        'catalog_last_refresh': today if any(x.get('ok') for x in directory_checks) and
            (not old_data.get('catalog_last_refresh') or (date.fromisoformat(today) - date.fromisoformat(old_data['catalog_last_refresh'])).days >= 7)
            else old_data.get('catalog_last_refresh', ''),
        'items': records,
        'disclaimer': ('Official-listing checks are best effort and cannot cover every WA/OR agency. '
                       'Deadline verification applies only when explicitly visible in a fetched notice. '
                       'OregonBuys vendor-portal bids and amendments may require manual login. '
                       'Unverified news results are not confirmed open procurements.'),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'PH Finder: {len(records)} records; agency targets={cover["total"]}; agency checks={cover["attempted_this_run"]}; {passed} deadline passed; '
          f'{payload["official_sources_checked"]}/{len(OFFICIAL_INDEXES)} official indexes fetched; '
          f'{len(logs)} source checks; {removed_irrelevant} irrelevant old records filtered; at {payload["updated_pacific"]}')
    # Exit cleanly on source blocks, preserving prior data; failures stay visible.


if __name__ == '__main__':
    main()
