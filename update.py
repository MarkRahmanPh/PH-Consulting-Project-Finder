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

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'opportunities.json'
TZ = ZoneInfo('America/Los_Angeles')
USER_AGENT = 'PH-Consulting-Project-Finder/3.0 (public procurement monitoring)'
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
QUERIES = {
    'WA': [
        ('signal', 'Washington traffic signal timing RFQ consultant'),
        ('signal', 'Washington traffic engineering on-call RFQ'),
        ('signal', 'Washington ATSPM ITS transit signal priority RFP'),
        ('rail', 'Washington railroad crossing elimination engineering RFQ'),
        ('rail', 'Washington grade separation quiet zone consultant RFP'),
        ('planning', 'Washington transportation safety SS4A engineering RFQ'),
        ('planning', 'Washington transportation planning traffic study RFP'),
        ('civil', 'Washington ADA curb ramps consultant RFQ'),
        ('civil', 'Washington civil roadway design on-call engineering RFQ'),
    ],
    'OR': [
        ('signal', 'Oregon signal retiming ITS traffic operations RFP'),
        ('rail', 'Oregon railroad preliminary engineering FRA crossing RFP'),
        ('planning', 'Oregon transportation planning safety study consultant RFP'),
        ('civil', 'Oregon roadway ADA curb ramp design engineering RFQ'),
    ],
}
CONSULTANT = re.compile(r'\b(rfp|rfq|rsoq|soq|request for (qualifications|proposals)|on[ -]?call|consultant|professional services|prequalification|engineering services|study|planning)\b', re.I)
FIELD = re.compile(r'\b(traffic|signal(?:ized)?|intersection|transit|transportation|pedestrian|bike|bicycle|roadway|rail|railroad|crossing|grade separation|safety|corridor|ITS|ATSPM|TSP|planning|ADA|curb ramps?|sidewalk|accessible|civil engineering|design|freight|SS4A|quiet zone)\b', re.I)
EXCLUDE = re.compile(r'\b(job posting|hiring|employment|janitorial|construction[- ]only|lowest bidder|bid tabulation|sealed construction bids|equipment purchase|construction advertisement)\b', re.I)
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


def category(text):
    if re.search(r'\b(CBRL|railroad|rail line|rail crossing|rail infrastructure|quiet zone|grade separation|FRA|RCE)\b', text, re.I): return 'rail'
    if re.search(r'\b(ADA|curb ramp|sidewalk|civil engineering|roadway design|road reconstruction)\b', text, re.I): return 'civil'
    if re.search(r'\b(traffic signal|signal timing|signalized|ITS|ATSPM|TSP|signal controller|traffic engineering)\b', text, re.I): return 'signal'
    return 'planning'


def is_relevant(text):
    return bool(CONSULTANT.search(text) and FIELD.search(text) and not EXCLUDE.search(text))


def priority(text):
    return 'HIGH' if re.search(r'\b(signal timing|traffic engineering|railroad|rail crossing|ATSPM|on-call traffic|traffic study|ADA curb ramp)\b', text, re.I) else 'REVIEW'


def standard_row(title, agency, state, url, body, source, today, listing=False):
    due = deadline(body, listing=listing)
    cat = category(title + ' ' + body)
    return dict(id=ident(url), state=state, category=cat, agency=agency, title=title[:200],
                summary=clean(body)[:410], priority=priority(title + ' ' + body),
                url=url, source=source, source_kind='official_listing',
                status='Official listing — deadline observed' if due else 'Official listing — deadline unverified',
                due_date=due, due_time='', role='Review prime/subconsultant fit',
                verified_on=today, last_seen=today, addenda_count=None)


def scan_omwbe(html, base, today):
    doc = Document(html)
    seen = set()
    for a in doc.root.findall('a'):
        url = absolute(base, a.attrs.get('href', ''))
        p = urllib.parse.urlsplit(url)
        if p.netloc not in ('omwbe.wa.gov', 'www.omwbe.wa.gov') or not p.path.startswith('/bid-opportunities/'):
            continue
        title = a.text()
        parent = wrapper(a)
        if len(title) < 12 or title.lower().startswith(('read more', 'details')):
            headings = [x.text() for x in parent.findall() if x.tag in ('h2', 'h3', 'h4')]
            title = headings[0] if headings else title
        surrounding = parent.text()
        # Due date may be the sibling of the link within a table row.
        if len(surrounding) < 35 and parent.parent:
            surrounding = parent.parent.text()[:500]
        if not is_relevant(title + ' ' + surrounding) or url in seen: continue
        seen.add(url)
        yield standard_row(title, 'Agency named in notice — check source', 'WA', url, surrounding,
                           'WA OMWBE official bid listing', today, listing=True)


def scan_webs(html, base, today):
    doc = Document(html)
    for tr in doc.root.findall('tr'):
        contents = tr.text()
        if not is_relevant(contents): continue
        anchors = [a for a in tr.findall('a') if a.text().strip()]
        if not anchors: continue
        a = sorted(anchors, key=lambda x: len(x.text()), reverse=True)[0]
        url = absolute(base, a.attrs.get('href', ''))
        if not url: continue
        title = a.text()
        if not is_relevant(title + ' ' + contents): continue
        yield standard_row(title, 'WA WEBS (see notice for agency)', 'WA', url, contents[:650],
                           'WA WEBS public calendar', today, listing=True)


def scan_coos(html, base, today):
    doc = Document(html)
    seen = set()
    for a in doc.root.findall('a'):
        url = absolute(base, a.attrs.get('href', ''))
        p = urllib.parse.urlsplit(url)
        if p.netloc not in ('portofcoosbay.com', 'www.portofcoosbay.com'): continue
        if '/request-for-proposals-' not in p.path: continue
        title = a.text()
        if url in seen or not is_relevant(title + ' ' + p.path.replace('-', ' ')): continue
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
            'category': category(row.get('title', '') + ' ' + text),
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
        if not title or not url.startswith('https://') or not is_relevant(title + ' ' + desc): continue
        stamp = item.findtext('pubDate')
        if stamp:
            try:
                if (date.fromisoformat(today) - parsedate_to_datetime(stamp).date()).days > 35: continue
            except (ValueError, TypeError, OverflowError): pass
        rid = 'feed-' + hashlib.sha1((title.lower() + '|' + url).encode()).hexdigest()[:18]
        yield dict(id=rid, title=title[:190], agency='Not confirmed', state=state, category=cat,
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


def merge_prior(prior):
    # Existing 2026-10-11 baseline is not treated as a fresh confirmed scrape.
    result = {}
    for row in prior:
        if not isinstance(row, dict) or not row.get('id'): continue
        row = dict(row)
        if row.get('source_kind') is None:
            row['source_kind'] = 'existing_watchlist' if row.get('source', '').startswith('Official') else 'news_feed'
            row['status'] = ('Previously recorded — recheck notice' if row['source_kind'] == 'existing_watchlist'
                             else 'Unverified lead — not confirmed open')
        row.setdefault('first_seen', row.get('found') or '2026-10-11')
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


def main():
    now = datetime.now(TZ)
    today = os.environ.get('PH_TEST_DATE') or now.date().isoformat()
    prior, old_data = load_prior()
    rows = merge_prior(prior)
    logs = []
    seen = set()
    if os.environ.get('PH_OFFLINE') != '1':
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
    payload = {
        'updated_pacific': now.strftime('%b %d, %Y %I:%M %p %Z'),
        'last_run_iso': now.isoformat(),
        'official_sources_checked': sum(x['ok'] for x in logs if x['source'] in [s['name'] for s in OFFICIAL_INDEXES]),
        'official_sources_total': len(OFFICIAL_INDEXES),
        'source_checks': logs,
        'items': records,
        'disclaimer': ('Official-listing checks are best effort and cannot cover every WA/OR agency. '
                       'Deadline verification applies only when explicitly visible in a fetched notice. '
                       'OregonBuys vendor-portal bids and amendments may require manual login. '
                       'Unverified news results are not confirmed open procurements.'),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'PH Finder: {len(records)} records; {passed} deadline passed; '
          f'{payload["official_sources_checked"]}/{len(OFFICIAL_INDEXES)} official indexes fetched; '
          f'{len(logs)} source checks; at {payload["updated_pacific"]}')
    # Exit cleanly on source blocks, preserving prior data; failures stay visible.


if __name__ == '__main__':
    main()
