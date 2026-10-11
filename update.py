"""Daily public-feed discovery. Results are leads, NOT verified open solicitations."""
import json, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
queries = {
 'WA': [
  ('signal','Washington traffic signal timing ITS ATSPM RFQ RFP consultant'),
  ('planning','Washington traffic engineering transportation planning on-call RFQ SOQ'),
  ('rail','Washington railroad crossing elimination grade separation rail engineering RFQ RFP'),
  ('rail','Washington FRA BNSF quiet zone railroad safety consultant solicitation')],
 'OR': [
  ('signal','Oregon signal timing ITS traffic engineering RFQ RFP consultant'),
  ('planning','Oregon transportation planning traffic operations on-call engineering RFP'),
  ('rail','Oregon railroad crossing elimination rail engineering quiet zone RFP RFQ')]
}
def fetch(q):
 url='https://news.google.com/rss/search?q='+urllib.parse.quote(q+' when:30d')+'&hl=en-US&gl=US&ceid=US:en'
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 PHConsultingOpportunityFinder/1.0'})
 with urllib.request.urlopen(req,timeout=25) as response: return ET.fromstring(response.read())
def clean(t):return re.sub(r'<[^>]+>',' ',t or '').strip()
def main():
 now=datetime.now(ZoneInfo('America/Los_Angeles')); items=[]; seen=set(); failures=[]
 for state, groups in queries.items():
  for category,q in groups:
   try: root=fetch(q)
   except Exception as e: failures.append(f'{state}/{category}: {e}');continue
   for node in root.findall('./channel/item')[:35]:
    title=clean(node.findtext('title')); link=node.findtext('link') or '';desc=clean(node.findtext('description'))
    if not title or not link:continue
    if not re.search(r'\b(RFP|RFQ|SOQ|solicitation|consultant|engineering services|request for qualifications|request for proposals|on.call|bid)\b',title+' '+desc,re.I):continue
    key=title.lower().strip()
    if key in seen:continue
    seen.add(key)
    priority='HIGH' if re.search(r'signal timing|traffic engineering|railroad crossing|on.call traffic|ATSPM|ITS',title,re.I) else 'REVIEW'
    items.append(dict(title=title,summary=desc[:350],state=state,category=category,source='Google News / linked publisher',url=link,found=now.strftime('%Y-%m-%d'),due_date=None,priority=priority))
 path=Path(__file__).with_name('opportunities.json')
 old=[]
 if path.exists():
  try:old=json.loads(path.read_text()).get('items',[])
  except Exception:pass
 known={x['title'].lower() for x in items}
 for x in old:
  if x['title'].lower() not in known and (now.date()-datetime.fromisoformat(x['found']).date()).days<=30:items.append(x)
 payload={'updated_pacific':now.strftime('%b %d, %Y %I:%M %p'),'items':items,'feed_errors':failures,'disclaimer':'Discovery leads only; verify official due dates and open status.'}
 path.write_text(json.dumps(payload,indent=2,ensure_ascii=False))
 print('Leads:',len(items),'Feed failures:',len(failures))
if __name__=='__main__':main()
