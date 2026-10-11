"""PH Consulting opportunity discovery, standard-library only.

Reliable startup: keep a dated list of official-source opportunities so a blocked
news feed does not yield an empty dashboard. These dates were manually checked on
2026-10-11; future changes to solicitation/addenda MUST be checked at source.
RSS results are discovery leads and are never labeled confirmed open bids.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'opportunities.json'
TZ = ZoneInfo('America/Los_Angeles')
CHECKED = '2026-10-11'

# Official notices verified October 11, 2026; a daily refresh is NOT an
# independent re-verification of their due dates or current procurement status.
OFFICIAL_WATCHLIST = [
  dict(id='wa-woodinville-pw26-0011',state='WA',category='signal',priority='HIGH',
       agency='City of Woodinville',title='On-Call Traffic Engineering Services (RFQ PW 26-0011)',
       due_date='2026-11-05',due_time='10:00 AM PT',role='Potential prime',
       summary='Two-year on-call municipal traffic engineering agreement; at least two consultants anticipated. Direct fit for signal operations, timing, traffic studies, and intersection safety.',
       url='https://omwbe.wa.gov/bid-opportunities/rfq-pw-26-0011-call-traffic-engineering-services'),
  dict(id='wa-spokane-traffic-2026',state='WA',category='planning',priority='HIGH',
       agency='Spokane Airport Board',title='Traffic Count & Planning Analysis (RFQ 26-43-9999-031)',
       due_date='2026-10-30',due_time='4:00 PM PT',role='Potential prime',
       summary='Traffic counts at airport roads and intersections; traffic operations, safety, and planning analysis. Revised RFQ available on the airport procurement page.',
       url='https://www.spokaneairports.com/corporate/business-opportunities/bids/'),
  dict(id='wa-benton-whitebluffs-2026',state='WA',category='rail',priority='HIGH',
       agency='Port of Benton',title='White Bluffs Rail Rehabilitation — Engineering Services RFQ',
       due_date='2026-10-22',due_time='3:00 PM PT',role='Rail team / specialty subconsultant',
       summary='Rail rehabilitation and railway-signal modernization, design, bidding support, and construction administration; possible roadway/rail crossing coordination.',
       url='https://portofbenton.com/business-with-us/'),
  dict(id='wa-shoalwater-ss4a-2026',state='WA',category='planning',priority='HIGH',
       agency='Shoalwater Bay Indian Tribe',title='SS4A Comprehensive Safety Action Plan (RFP P-2027-2)',
       due_date='2026-11-04',due_time='4:00 PM PT',role='Potential prime — safety analysis component',
       summary='Separate safety-planning components. PH fit: crash and systemic safety analysis, intersection hazards, pedestrian visibility, and project prioritization.',
       url='https://www.shoalwaterbay-nsn.gov/about-the-tribe/requests-for-proposal/ss4a-safety-action-plan-for-the-planning-department/'),
  dict(id='or-coos-cbrl-2026',state='OR',category='rail',priority='HIGH',
       agency='Oregon International Port of Coos Bay',title='Coos Bay Rail Line Upgrades Planning (RFP 2026-03CBRL)',
       due_date='2026-10-28',due_time='4:00 PM PT',role='Rail-team / signal-communications discipline',
       summary='Rail preliminary engineering/design. Discipline 1.7 covers rail signal and communications; coordination and crossing analysis are potential specialty roles.',
       url='https://www.portofcoosbay.com/request-for-proposals-cbrl-upgrades-planning-project'),
  dict(id='or-coos-pcip-2026',state='OR',category='planning',priority='HIGH',
       agency='Oregon International Port of Coos Bay',title='PCIP Terminal Planning — Traffic Study (RFP 2026-01TERM)',
       due_date='2026-10-28',due_time='4:00 PM PT',role='Potential traffic-study discipline prime / sub',
       summary='Terminal planning solicitation includes a traffic-study discipline: counts, trip generation, peak-hour operations, and traffic-impact assessment.',
       url='https://www.portofcoosbay.com/request-for-proposals-pcip-terminal-planning-project'),
  dict(id='or-odot-landuse-2027',state='OR',category='planning',priority='REVIEW',
       agency='Oregon Department of Transportation',title='Transportation Land Use Planning 2027 Price Agreement (S-73000-00017438)',
       due_date='2026-11-20',due_time='9:00 AM PT',role='Prime or planning subconsultant',
       summary='Statewide transportation system/land-use planning and analysis price agreement. Relevant modeling, operations, safety, and travel-demand expertise.',
       url='https://oregonbuys.gov/bso/external/bidDetail.sda?docId=S-73000-00017438&external=true&parentUrl=close'),
  dict(id='wa-wsdot-prequal-2026',state='WA',category='planning',priority='HIGH',
       agency='Washington State Department of Transportation',title='2026 WSDOT Consultant Prequalification / Roster',
       due_date='2027-06-30',due_time='5:00 PM PT',role='Roster / eligibility',
       summary='Applications accepted continuously. Applicable fields include Traffic Engineering, Transportation Planning and Studies, and Rail/Freight/Ports.',
       url='https://wsdot.wa.gov/business-wsdot/contracting-opportunities/2026-wsdot-consultant-prequalification'),
]

# Concise queries work better in news search than a single long list of acronyms.
QUERIES = {
 'WA': [
  ('signal','"traffic signal" "RFQ" Washington'),
  ('signal','"signal timing" "RFP" Washington'),
  ('signal','"traffic engineering" "on-call" Washington'),
  ('signal','"ITS" "consultant" "RFQ" Washington'),
  ('planning','"traffic study" "RFQ" Washington'),
  ('planning','"transportation planning" "RFP" Washington'),
  ('planning','"pedestrian safety" "RFQ" Washington'),
  ('rail','"railroad crossing" "RFQ" Washington'),
  ('rail','"rail" "engineering services" "RFQ" Washington'),
  ('rail','"grade separation" "consultant" Washington'),
  # Civil engineering and ADA professional-services opportunities (not construction-only bids)
  ('civil','"ADA curb ramp" "consultant" Washington'),
  ('civil','"ADA improvements" "engineering services" Washington'),
  ('civil','"roadway design" "RFQ" Washington'),
  ('civil','"civil engineering" "on-call" Washington'),
  ('civil','"sidewalk improvements" "consultant" Washington'),
 ],
 'OR': [
  ('signal','"signal timing" "RFP" Oregon'),
  ('signal','"traffic engineering" "RFQ" Oregon'),
  ('planning','"transportation planning" "RFP" Oregon'),
  ('planning','"traffic impact study" "RFP" Oregon'),
  ('rail','"railroad" "engineering" "RFP" Oregon'),
  ('rail','"rail crossing" "RFQ" Oregon'),
  ('civil','"ADA curb ramp" "consultant" Oregon'),
  ('civil','"ADA improvements" "RFQ" Oregon'),
  ('civil','"roadway design" "engineering services" Oregon'),
  ('civil','"civil engineering" "on-call" Oregon'),
  ('civil','"sidewalk improvements" "consultant" Oregon'),
 ]
}

REQUEST_RE = re.compile(r'\b(rfp|rfq|rsoq|soq|request for (qualifications|proposals)|on[ -]?call|consultant|professional services|solicitation|prequalification)\b', re.I)
FIELD_RE = re.compile(r'\b(traffic|signal|intersection|transit|transportation|pedestrian|bike|roadway|rail|railroad|crossing|grade separation|safety|corridor|ITS|ATSPM|TSP|planning|ADA|curb ramps?|sidewalks?|accessible|accessibility|civil engineering|complete streets)\b', re.I)
BLOCK_RE = re.compile(r'\b(construction bid|construction only|low bid|bid tabulation|bid opening results|job posting|hiring|employment|equipment purchase|janitorial|roof replacement)\b',re.I)
TAG_RE = re.compile(r'<[^>]+>')


def scrub(value: str) -> str:
    return re.sub(r'\s+', ' ', unescape(TAG_RE.sub(' ', value or ''))).strip()


def get_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        'User-Agent':'Mozilla/5.0 (compatible; PHConsultingProjectFinder/2.0)',
        'Accept':'application/rss+xml, application/xml, text/xml, */*'})
    with urllib.request.urlopen(request,timeout=16) as res:
        return res.read(900_000)


def feeds(query: str):
    # Two independent public feeds are attempted. Both can fail or omit notices.
    q = urllib.parse.quote(query)
    return [
        ('Google News',f'https://news.google.com/rss/search?q={q}%20when%3A45d&hl=en-US&gl=US&ceid=US:en'),
        ('Bing News',f'https://www.bing.com/news/search?q={q}&format=rss'),
    ]


def stable_id(title: str, url: str) -> str:
    return 'feed-' + hashlib.sha1((title.lower().strip()+'|'+url).encode()).hexdigest()[:18]


def feed_items(xml: bytes, state: str, category: str, source: str, today: date):
    root=ET.fromstring(xml)
    for item in root.findall('.//item')[:35]:
        title=scrub(item.findtext('title'))
        description=scrub(item.findtext('description'))
        link=(item.findtext('link') or '').strip()
        combined=title+' '+description
        if not link.startswith('https://') or not title:continue
        if not (REQUEST_RE.search(combined) and FIELD_RE.search(combined)):continue
        if BLOCK_RE.search(title):continue
        pub=item.findtext('pubDate')
        if pub:
            try:
                published=parsedate_to_datetime(pub).date()
                if today-published > timedelta(days=50): continue
            except (ValueError,TypeError,OverflowError): pass
        yield {
            'id':stable_id(title,link),'title':title,'agency':'Agency not confirmed',
            'state':state,'category':category,'priority':'REVIEW',
            'summary':description[:340] or 'Possible consulting solicitation; review original notice.',
            'url':link,'source':source+' — discovery only','status':'Unverified search lead',
            'found':today.isoformat(),'due_date':None,'due_time':'',
            'role':'Review potential fit','verified_on':None}


def load_prior():
    if not OUTPUT.exists():return []
    try:return json.loads(OUTPUT.read_text(encoding='utf-8')).get('items',[])
    except (ValueError,OSError):return []


def assemble(today: date, prior, fresh):
    rows={}
    for seed in OFFICIAL_WATCHLIST:
        if date.fromisoformat(seed['due_date']) < today:continue
        row={**seed,'source':'Official agency notice','status':'Agency-listed; check for addenda',
             'found':CHECKED,'verified_on':CHECKED}
        rows[row['id']]=row
    for item in prior:
        try:
            if item.get('status','').startswith('Agency-listed'):continue # rebuild with deadline expiry
            found=date.fromisoformat(item['found'])
            due=item.get('due_date')
            if (today-found).days>35 or (due and date.fromisoformat(due)<today):continue
            if not item.get('url','').startswith('https://'):continue
            rows.setdefault(item.get('id') or stable_id(item['title'],item['url']),item)
        except (KeyError,ValueError,TypeError):continue
    for item in fresh:
        if item['id'] not in rows: rows[item['id']]=item
    return sorted(rows.values(),key=lambda r:(r['state']!='WA',r['priority']!='HIGH',r.get('due_date') or '9999-12-31',r['title'].lower()))


def main():
    now=datetime.now(TZ); today=now.date(); prior=load_prior()
    discovered=[]; errors=[]; calls_ok=0
    if os.environ.get('PH_OFFLINE')!='1':
        for state,pairs in QUERIES.items():
            for category,q in pairs:
                succeeded=False
                for provider,url in feeds(q):
                    try:
                        new=list(feed_items(get_url(url),state,category,provider,today))
                        calls_ok+=1;succeeded=True
                        discovered.extend(new)
                        if new: break # try the secondary feed when there are no matches
                    except (OSError,ET.ParseError,ValueError) as exc:
                        last_error=f'{provider}: {type(exc).__name__}: {str(exc)[:100]}'
                if not succeeded:errors.append(f'{state}/{category}: {last_error}')
    rows=assemble(today,prior,discovered)
    payload={
        'updated_pacific':now.strftime('%b %d, %Y %I:%M %p %Z'),
        'checked_official_on':CHECKED,
        'items':rows,
        'feed_status':'Online discovery attempted' if calls_ok else 'Feeds unavailable / offline; official-source watchlist still visible',
        'feed_errors':errors[:20],
        'disclaimer':'Official-source dates were last manually checked 2026-10-11. Search-feed leads are not verified active bids. Always confirm current source/addenda.'
    }
    OUTPUT.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f'Visible opportunities: {len(rows)} (official-source watchlist: {sum(r["status"].startswith("Agency-listed") for r in rows)}; fresh feed leads: {len(discovered)}; successful feeds: {calls_ok}; feed failures: {len(errors)})')

if __name__=='__main__':main()
