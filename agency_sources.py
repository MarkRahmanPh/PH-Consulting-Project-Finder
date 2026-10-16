"""Incremental WA/OR municipal procurement coverage, using public jurisdiction directories.

No API keys. No scraping behind logins. Each run checks a small rotating batch
of official agency websites and keeps an honest coverage/status log. The catalog
is stored in opportunities.json, so existing GitHub Actions git-add still works.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

DIRECTORIES = [
    dict(state='WA', kind='city', name='WA — MRSC city & town directory',
         url='https://mrsc.org/research-tools/washington-city-and-town-profiles'),
    dict(state='WA', kind='county', name='WA — MRSC county directory',
         url='https://mrsc.org/research-tools/county-profiles'),
    dict(state='OR', kind='city', name='OR — League of Oregon Cities directory',
         url='https://www.orcities.org/resources/reference/city-directory'),
    dict(state='OR', kind='county', name='OR — Oregon state county directory',
         url='https://www.oregon.gov/pages/counties.aspx'),
]

WA_COUNTIES = [
    'Adams','Asotin','Benton','Chelan','Clallam','Clark','Columbia','Cowlitz','Douglas',
    'Ferry','Franklin','Garfield','Grant','Grays Harbor','Island','Jefferson','King',
    'Kitsap','Kittitas','Klickitat','Lewis','Lincoln','Mason','Okanogan','Pacific',
    'Pend Oreille','Pierce','San Juan','Skagit','Skamania','Snohomish','Spokane',
    'Stevens','Thurston','Wahkiakum','Walla Walla','Whatcom','Whitman','Yakima',
]
OR_COUNTIES = [
    'Baker','Benton','Clackamas','Clatsop','Columbia','Coos','Crook','Curry',
    'Deschutes','Douglas','Gilliam','Grant','Harney','Hood River','Jackson',
    'Jefferson','Josephine','Klamath','Lake','Lane','Lincoln','Linn','Malheur',
    'Marion','Morrow','Multnomah','Polk','Sherman','Tillamook','Umatilla',
    'Union','Wallowa','Wasco','Washington','Wheeler','Yamhill',
]
# Fallback cities if an official directory is temporarily unreachable. Full city
# lists are discovered from directories; this is NOT a claim that each city is scraped.
WA_CITIES = '''Aberdeen|Airway Heights|Anacortes|Arlington|Auburn|Bainbridge Island|Battle Ground|Bellevue|Bellingham|Blaine|Bonney Lake|Bothell|Bremerton|Burien|Burlington|Camas|Centralia|Chehalis|Cheney|Cle Elum|Covington|Des Moines|DuPont|Duvall|East Wenatchee|Edgewood|Edmonds|Ellensburg|Enumclaw|Everett|Federal Way|Ferndale|Fife|Fircrest|Gig Harbor|Grandview|Issaquah|Kenmore|Kennewick|Kent|Kirkland|Lacey|Lake Stevens|Lakewood|Liberty Lake|Longview|Lynnwood|Maple Valley|Marysville|Mercer Island|Mill Creek|Monroe|Moses Lake|Mount Vernon|Mountlake Terrace|Mukilteo|Oak Harbor|Olympia|Omak|Pasco|Port Angeles|Port Orchard|Poulsbo|Prosser|Pullman|Puyallup|Redmond|Renton|Richland|Ridgefield|Sammamish|SeaTac|Seattle|Sedro-Woolley|Sequim|Shoreline|Snohomish|Snoqualmie|Spokane|Spokane Valley|Stanwood|Steilacoom|Sumner|Tacoma|Tukwila|Tumwater|University Place|Vancouver|Walla Walla|Washougal|Wenatchee|West Richland|Woodinville|Woodland|Yakima|Yelm|Zillah'''.split('|')
OR_CITIES = '''Albany|Ashland|Astoria|Baker City|Bandon|Banks|Beaverton|Bend|Brookings|Canby|Central Point|Coos Bay|Coquille|Cornelius|Corvallis|Cottage Grove|Dallas|Eugene|Fairview|Florence|Forest Grove|Gladstone|Grants Pass|Gresham|Happy Valley|Hermiston|Hillsboro|Hood River|Independence|Keizer|Klamath Falls|La Grande|Lake Oswego|Lincoln City|Madras|McMinnville|Medford|Milwaukie|Molalla|Monmouth|Newberg|Newport|North Plains|Ontario|Oregon City|Pendleton|Philomath|Portland|Prineville|Redmond|Roseburg|Salem|Sandy|Scappoose|Seaside|Sherwood|Silverton|Springfield|St. Helens|Stayton|Sutherlin|Sweet Home|The Dalles|Tigard|Tillamook|Troutdale|Tualatin|West Linn|Wilsonville|Woodburn'''.split('|')

OTHER_AGENCIES = [
    ('WA','state','Washington State Department of Transportation','https://wsdot.wa.gov/'),
    ('WA','state','WA Office of Minority and Women’s Business Enterprises','https://omwbe.wa.gov/small-business-assistance/bids-contracting-opportunities'),
    ('WA','port','Port of Seattle','https://www.portseattle.org/'),
    ('WA','port','Port of Tacoma','https://www.portoftacoma.com/'),
    ('WA','port','Port of Benton','https://portofbenton.com/business-with-us/'),
    ('WA','port','Port of Vancouver USA','https://www.portvanusa.com/'),
    ('WA','transit','Sound Transit','https://www.soundtransit.org/'),
    ('WA','transit','King County Metro','https://kingcounty.gov/'),
    ('WA','transit','Pierce Transit','https://www.piercetransit.org/'),
    ('WA','transit','Community Transit','https://www.communitytransit.org/'),
    ('WA','transit','Spokane Transit','https://www.spokanetransit.com/'),
    ('OR','state','Oregon Department of Transportation','https://www.oregon.gov/odot/'),
    ('OR','state','OregonBuys','https://oregonbuys.gov/'),
    ('OR','port','Port of Coos Bay','https://www.portofcoosbay.com/solicitations-public-notices'),
    ('OR','port','Port of Portland','https://www.portofportland.com/'),
    ('OR','port','Port of Morrow','https://www.portofmorrow.com/'),
    ('OR','transit','TriMet','https://trimet.org/'),
    ('OR','transit','Lane Transit District','https://www.ltd.org/'),
    ('OR','transit','Salem Area Mass Transit District','https://www.cherriots.org/'),
    ('OR','regional','Metro (Oregon)','https://www.oregonmetro.gov/'),
]

EXCLUDE_HOSTS = ('facebook.com','instagram.com','linkedin.com','twitter.com',
                 'x.com','youtube.com','wikipedia.org','google.com','arcgis.com',
                 'mrsc.org','orcities.org','sos.oregon.gov','oregon.gov/pages/counties.aspx')
PORTAL_HOSTS = ('bidnetdirect.com','bonfirehub.com','publicpurchase.com',
                'opengov.com','planetbids.com','bidsandtenders.ca',
                'mrscrosters.org','vendorregistry.com','ionwave.net',
                'demandstar.com','oregonbuys.gov','pr-webs-vendor.des.wa.gov')
NAV_RE = re.compile(r'\b(?:bids?|rfqs?|rfps?|requests? for (?:proposals?|qualifications?)|'
                    r'procurement|solicitations?|contracting opportunities|'
                    r'current opportunities|business with us|purchasing|'
                    r'public notices|consultant opportunities|doing business)\b',re.I)
GENERIC_LINK = re.compile(r'^(?:more|read more|click here|view details|details|home|about us|'
                          r'download|bid opportunities|bids|rfps?|rfqs?|purchasing|'
                          r'procurement|solicitations|public notices|view all)$', re.I)


def key(state, kind, name):
    return f'{state}|{kind}|{name.strip().casefold()}'


def new_agency(state,kind,name,profile_url='',website='',procurement_url='',priority=0):
    return dict(id=key(state,kind,name),state=state,kind=kind,name=name,
                profile_url=profile_url,website=website,procurement_url=procurement_url,
                last_check='',status='Not yet checked',priority=priority)


# Official agency procurement/public bid pages independently identified from issuing-agency websites.
# Some pages lead to supplier portals; a listed URL is NOT proof bids can be scraped.
VERIFIED_PROCUREMENT_PAGES = [
    # Transit agencies are direct TSP/ITS procurement issuers.
    ("WA", "transit", "Pierce Transit", "https://piercetransit.org/procurement/"),
    ("WA", "transit", "Sound Transit", "https://www.soundtransit.org/get-to-know-us/doing-business-with-us/procurement-contracts-agreements"),
    ("OR", "transit", "TriMet", "https://trimet.org/procurement/"),
    ("WA", "city", "Bothell", "https://www.bothellwa.gov/bids.aspx"),
    ("WA", "city", "Des Moines", "https://www.desmoineswa.gov/Bids.aspx"),
    ("WA", "city", "Pasco", "https://www.pasco-wa.gov/Bids.aspx"),
    ("WA", "city", "Everett", "https://www.everettwa.gov/Bids.aspx"),
    ("WA", "county", "Pierce County", "https://www.piercecountywa.gov/currentsolicitations"),
    ("WA", "county", "Snohomish County", "https://snohomishcountywa.gov/3706/Purchasing-Portal"),
    ("WA", "county", "Whatcom County", "https://www.whatcomcounty.us/Bids.aspx"),
    ("WA", "county", "King County", "https://kingcounty.gov/procurement/solicitations"),
    ("OR", "county", "Washington County", "https://www.washingtoncountyor.gov/procurement"),
    ("WA", "city", "Redmond", "https://www.redmond.gov/bids.aspx"),
    ("WA", "city", "Woodinville", "https://www.woodinville.gov/193/Bids-Proposals"),
    ("WA", "city", "Tacoma", "https://tacoma.gov/government/departments/finance/procurement-and-payables-division/purchasing/contracting-opportunities/"),
    ("WA", "city", "Seattle", "https://www.seattle.gov/purchasing-and-contracting"),
    ("WA", "city", "Vancouver", "https://www.cityofvancouver.us/business/procurement-services/"),
    ("WA", "city", "Spokane", "https://my.spokanecity.org/administrative/purchasing/"),
    ("WA", "city", "Bellingham", "https://cob.org/services/business/purchasing/purchasing-bid-opening"),
    ("WA", "city", "Bellevue", "https://bellevuewa.gov/city-government/departments/ITD/doing-business-with-it"),
    ("WA", "city", "Issaquah", "https://www.issaquahwa.gov/1464/Bids-RFPs"),
    ("WA", "city", "Sumner", "https://sumnerwa.gov/bids/"),
    ("WA", "city", "Federal Way", "https://www.federalwaywa.gov/bids"),
    ("WA", "city", "Lacey", "https://cityoflacey.org/rfp-rfq/"),
    ("WA", "city", "Wenatchee", "https://www.wenatcheewa.gov/services/bid-opportunities"),
    ("OR", "city", "Portland", "https://www.portland.gov/business-opportunities"),
    ("OR", "city", "Eugene", "https://www.eugene-or.gov/108/Purchasing"),
    ("OR", "city", "Bend", "https://bendoregon.gov/departments/administration/procurement/"),
    ("OR", "city", "Hillsboro", "https://www.hillsboro-oregon.gov/our-city/departments/finance/procurement"),
    ("OR", "city", "Beaverton", "https://beavertonoregon.gov/bid-proposal-opportunities"),
    ("OR", "county", "Clackamas County", "https://www.clackamas.us/procurement-process"),
    ("OR", "county", "Multnomah County", "https://multco.us/info/bids-proposal-opportunities"),
    ("WA", "port", "Port of Benton", "https://portofbenton.com/business-with-us/"),
    ("OR", "port", "Port of Coos Bay", "https://www.portofcoosbay.com/solicitations-public-notices"),
]

def seeded_catalog(existing=None):
    catalog={a['id']:dict(a) for a in (existing or []) if isinstance(a,dict) and a.get('id')}
    for state, counties in [('WA',WA_COUNTIES),('OR',OR_COUNTIES)]:
        for name in counties:
            row=new_agency(state,'county',name+' County',priority=10 if state=='WA' else 6)
            catalog.setdefault(row['id'],row)
    for state, cities in [('WA',WA_CITIES),('OR',OR_CITIES)]:
        for name in cities:
            row=new_agency(state,'city',name,priority=9 if state=='WA' else 5)
            catalog.setdefault(row['id'],row)
    for state,kind,name,website in OTHER_AGENCIES:
        row=new_agency(state,kind,name,website=website,priority=15)
        catalog.setdefault(row['id'],row)
    # Fill previously empty URLs and replace older mistakenly learned PDF or
    # individual-bid links with a verified agency-wide procurement landing page.
    for state,kind,name,url in VERIFIED_PROCUREMENT_PAGES:
        aid=key(state,kind,name)
        agency=catalog.get(aid)
        if agency is None:
            agency=new_agency(state,kind,name,priority=12 if state=='WA' else 8)
            catalog[aid]=agency
        agency['website']=url
        agency['procurement_url']=url
        agency['priority']=max(agency.get('priority') or 0,12 if state=='WA' else 8)
    return catalog


def _good_name(s,kind):
    s=' '.join(s.split()).strip(' -')
    if not 2<=len(s)<=65 or s.lower() in {'city','county','city name','name','view details','county website','city website'}:
        return ''
    if any(x in s.lower() for x in ('population','website','view details','2026','city officials','classification','profile')):
        return ''
    if not re.fullmatch(r"[A-Za-zÀ-ÿ .'-]+",s):return ''
    if kind=='county' and not s.lower().endswith('county'): s+=' County'
    return s


def parse_directory(html,source,Document,absolute):
    """Extract municipalities from a directory's individual table rows only."""
    doc=Document(html)
    state,kind,base=source['state'],source['kind'],source['url']
    found=[]; seen=set()
    for tr in doc.root.findall('tr'):
        cells=[x for x in tr.children if not isinstance(x,str) and x.tag in ('th','td')]
        if len(cells)<2 or cells[0].tag!='td':continue
        text=cells[0].text().strip()
        # League of Oregon Cities can have a separate "View Details" cell.
        name=_good_name(text,kind)
        if not name or name.casefold() in seen: continue
        seen.add(name.casefold())
        profile=''; website=''
        for a in tr.findall('a'):
            url=absolute(base,a.attrs.get('href',''))
            if not url:continue
            host=urlsplit(url).hostname or ''
            anchor=a.text().lower()
            if host.endswith(('mrsc.org','orcities.org','oregon.gov','sos.oregon.gov')):
                if not profile:profile=url
            elif not any(x in host for x in EXCLUDE_HOSTS):
                if not website:website=url
        found.append(new_agency(state,kind,name,profile_url=profile,website=website,priority=9 if state=='WA' else 5))
    # Oregon's county index sometimes uses cards rather than table rows. Only
    # accept exact "Name County" links; do not harvest generic site navigation.
    if kind=='county' and len(found)<15:
        allowed=set(OR_COUNTIES if state=='OR' else WA_COUNTIES)
        for a in doc.root.findall('a'):
            name=_good_name(a.text().strip(),kind)
            if not name or not name.endswith(' County'):continue
            if name[:-7] not in allowed or name.casefold() in seen:continue
            url=absolute(base,a.attrs.get('href',''))
            if not url:continue
            host=(urlsplit(url).hostname or '').lower()
            if any(x in host for x in EXCLUDE_HOSTS):
                website='';profile=url
            else:
                website=url;profile=''
            found.append(new_agency(state,kind,name,profile_url=profile,
                                    website=website,priority=10 if state=='WA' else 6))
            seen.add(name.casefold())
    return found


def external_website_from_profile(html,profile_url,Document,absolute):
    doc=Document(html); candidates=[]
    sourcehost=(urlsplit(profile_url).hostname or '').lower()
    for a in doc.root.findall('a'):
        url=absolute(profile_url,a.attrs.get('href',''))
        if not url: continue
        host=(urlsplit(url).hostname or '').lower()
        if host==sourcehost or any(bad in host for bad in EXCLUDE_HOSTS): continue
        label=a.text().casefold()
        score=(7 if re.search(r'\b(?:website|web site|city website|county website|visit website|official site)\b',label) else 0)
        if host.endswith('.gov'):score+=3
        if urlsplit(url).path in ('','/'):score+=1
        if any(z in host for z in PORTAL_HOSTS):score-=5
        candidates.append((score,url))
    candidates.sort(reverse=True)
    return candidates[0][1] if candidates and candidates[0][0]>=7 else ''


def find_procurement_page(html,website,Document,absolute):
    doc=Document(html); candidates=[]
    homehost=(urlsplit(website).hostname or '').lower()
    for a in doc.root.findall('a'):
        text=a.text().strip(); href=a.attrs.get('href','')
        if not NAV_RE.search(text+' '+href):continue
        link=absolute(website,href)
        if not link:continue
        host=(urlsplit(link).hostname or '').lower()
        if host!=homehost and not (host.endswith('.'+homehost) or any(x in host for x in PORTAL_HOSTS)):
            continue
        if link==website or re.search(r'\.pdf(?:$|\?)',link,re.I):continue
        # Only save a procurement landing page, not an individual RFQ notice.
        if '/bid-opportunities/' in link and '/bid-opportunities/' not in website:
            continue
        score=10 if re.search(r'\b(?:bid opportunities|rfps?|rfqs?|solicitations|procurement|purchasing)\b',text,re.I) else 4
        if host!=homehost:score-=2
        candidates.append((score,link))
    candidates.sort(reverse=True)
    return candidates[0][1] if candidates else ''


def scan_agency_bids(html,base,agency,Document,absolute,classify_title,
                     safe_single_item_scope,safe_listing_due,remove_trailing_date,
                     standard_row,today):
    doc=Document(html)
    seen=set(); output=[]
    allowedhost=(urlsplit(base).hostname or '').lower()
    for a in doc.root.findall('a'):
        raw=a.text().strip()
        title=remove_trailing_date(raw)
        if len(title)<10 or GENERIC_LINK.fullmatch(title):continue
        # A bid page sometimes links an RFQ by project name only; later we
        # validate a tightly scoped single-listing snippet for solicitation type.
        cat=classify_title(title,require_procurement=False)
        if not cat:continue
        u=absolute(base,a.attrs.get('href',''))
        if not u or u in seen:continue
        # A completed study or general project-information page is not an RFQ.
        path=(urlsplit(u).path or '').lower()
        if any(fragment in path for fragment in ('/hillsboro-major-projects/',
            '/engineering-standards/planning-guidance/', '/home/components/news/')):
            continue
        # Titles on an agency website are NOT automatically live solicitations.
        # Require procurement language on the link or a solicitation-specific URL.
        is_notice=bool(re.search(
            r'\b(?:rfp|rfq|rfi|rsoq|soq|request for (?:proposals?|qualifications?|information)|'
            r'on[ -]?call|professional services|solicitation|consultant roster|prequalification)\b',
            title,re.I))
        is_bid_url=bool(re.search(r'/(?:rfp|rfq|rfi|bids?|solicitations?)[/-]',path,re.I))
        # Also allow scoped RFQs with a project-only anchor title; verify
        # procurement/service language in that one result card below.
        host=(urlsplit(u).hostname or '').lower()
        if host != allowedhost and not (host.endswith('.'+allowedhost) or any(x in host for x in PORTAL_HOSTS)):
            continue
        # Never infer an RFQ from the surrounding whole listings page.
        # A title may omit "RFQ" only if this individual card supplies a
        # consultant/engineering scope and an explicit procurement term.
        local=safe_single_item_scope(a,u)
        context=title
        scoped=a.parent
        for _ in range(4):
            if scoped is None:break
            snippet=scoped.text()
            klass=(scoped.attrs.get('class') or '').lower()
            if 30<len(snippet)<1100 and (
                    scoped.tag in ('tr','li','article') or
                    (scoped.tag=='div' and re.search(
                        r'bid|rfq|rfp|solicit|item|result|card|posting',klass))):
                context=snippet
                break
            scoped=scoped.parent
        direct_notice=bool(re.search(
            r'\b(?:RFQ|RFP|RFI|RSOQ|SOQ|request for (?:proposals?|qualifications?)|'
            r'on[ -]?call|professional services|solicitation|consultant roster|prequalification)\b',
            title,re.I))
        scoped_consulting=bool(re.search(
            r'\b(?:request for (?:qualifications|proposals)|RFQ|RFP|SOQ)\b',context,re.I)) and bool(
            re.search(r'\b(?:engineering|design services|professional services|'
                      r'consultants?|planning study|traffic study|transportation study)\b',context,re.I))
        if not (direct_notice or scoped_consulting or
                (is_bid_url and re.search(r'\b(?:RFQ|RFP|SOQ|request for qualifications|professional services)\b',context,re.I))):continue
        seen.add(u)
        # Only use a date belonging to this actual bid link/card.
        local=safe_single_item_scope(a,u)
        due=safe_listing_due(raw,local if len(local)<450 else raw)
        row=standard_row(title,agency['name'],agency['state'],u,title,
            f"{agency['name']} public procurement listing",today,listing=True,observed_due=due)
        row['agency_id']=agency['id']
        # Search results are official-link observations, but not a direct
        # validation of the solicitation PDF or current open status.
        row['status']='Agency procurement listing — review official notice'
        if not due:row['verified_on']=None
        output.append(row)
    return output[:45]


def selected_agencies(catalog,today,count=14):
    """Round-robin: unvisited first; then oldest check. Approx. all targets per days."""
    if count<=0:return []
    rows=[a for a in catalog.values() if a.get('website') or a.get('profile_url')]
    # Agencies without a discoverable official URL stay in the directory as
    # pending, instead of wasting a network scan slot or inflating coverage.
    # Refresh priority WA before OR, but never starve Oregon agencies.
    wa=[x for x in rows if x.get('state')=='WA']; orr=[x for x in rows if x.get('state')=='OR']
    def order(xs):
        return sorted(xs,key=lambda x:(x.get('last_check_at') or '0000-00-00',
                                      -(x.get('priority') or 0),x.get('name','')))
    w=order(wa); o=order(orr)
    wn=min(len(w),max(1,round(count*.65))); on=min(len(o),count-wn)
    out=w[:wn]+o[:on]
    if len(out)<count:out+=w[wn:wn+count-len(out)]
    if len(out)<count:out+=o[on:on+count-len(out)]
    return out[:count]
