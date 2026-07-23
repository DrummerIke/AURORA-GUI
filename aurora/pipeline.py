from __future__ import annotations

import asyncio, hashlib, html, ipaddress, json, os, re, shutil, socket, subprocess, time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import phonenumbers, requests
try:
    import yaml
except Exception:
    yaml = None
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None
from ddgs import DDGS
from phonenumbers import carrier, geocoder, timezone as phtz

STATUSES={"OK","ERROR","TIMEOUT","CONFIGURATION_REQUIRED","RATE_LIMITED","DISABLED"}
PHONE_STOPLIST={"ваше имя","главная коды","если вам","комментарий имя тип","мошенники","мошенники реклама коллекторы","кто звонил","не бери трубку","обратная связь","пользовательское соглашение","privacy policy","sign in","your name","home codes","submit comment","who called","do not answer","menu","login","register","search","contact us","advertisement","breadcrumbs"}
LOW_TRUST_PHONE_DOMAINS={"baza-nomerov.com","centerica.ru","kodtelefona.ru","mobile-monitor.ru","phoneradar.ru","region-operator.ru","spravochnik.tel","who-call.me","zvonok24.ru","numbase.ru","nomercheck.ru","truecaller.com","numlookup.com","findwhocallsyou.com"}
EMAIL_RE=re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PERSON_RE=re.compile(r"\b([А-ЯЁ][а-яё-]{1,30}\s+[А-ЯЁ][а-яё-]{1,30}(?:\s+[А-ЯЁ][а-яё-]{1,30}){0,2})\b")
USERNAME_RE=re.compile(r"^@?[A-Za-z0-9_.-]{3,64}$")

@dataclass
class Evidence:
    id:str; source:str; source_url:str=""; source_type:str="web"; title:str=""; excerpt:str=""; retrieved_at:str=field(default_factory=lambda:datetime.now(timezone.utc).isoformat()); published_at:str|None=None; reliability:float=.5; direct_match:bool=False; content_hash:str=""; archived_url:str|None=None; screenshot_reference:str|None=None
@dataclass
class EntityClaim:
    field:str; value:str; normalized_value:str; confidence:int; verification_status:str; source_count:int; independent_source_count:int; evidence_ids:list[str]; first_seen:str|None=None; last_seen:str|None=None; extraction_method:str=""; reasoning_summary:str=""; confidence_breakdown:dict[str,Any]=field(default_factory=dict)
@dataclass
class Entity:
    id:str; type:str; claims:list[EntityClaim]=field(default_factory=list)
@dataclass
class ConnectorResult:
    connector_id:str; status:str; started_at:str; completed_at:str; duration_ms:int; entities:list[dict]=field(default_factory=list); evidence:list[dict]=field(default_factory=list); warnings:list[str]=field(default_factory=list); errors:list[str]=field(default_factory=list); raw_reference:str|None=None; metadata:dict[str,Any]=field(default_factory=dict)
@dataclass
class RejectedCandidate:
    value:str; kind:str; reason:str; source_url:str=""; context:str=""
@dataclass
class SearchCase:
    id:str; input:dict; connector_runs:list[dict]; entities:list[dict]; evidence:list[dict]; rejected_candidates:list[dict]; summary:dict; relationships:list[dict]=field(default_factory=list)

class InputClassifier:
    def classify(self, raw:str)->str:
        v=raw.strip(); p=urlparse(v if "://" in v else "//"+v)
        if EMAIL_RE.fullmatch(v): return "email"
        try: ipaddress.ip_address(v); return "ip_address"
        except ValueError: pass
        if v.startswith("@") and USERNAME_RE.fullmatch(v): return "telegram_username"
        if re.fullmatch(r"(?:\+|00)?[\d\s().-]{7,20}", v): return "phone"
        if v.startswith(("http://","https://")): return "url"
        if p.netloc and re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", p.netloc or v): return "domain"
        if USERNAME_RE.fullmatch(v): return "username"
        if len(v.split())>=2: return "person_name"
        return "organization"
class InputNormalizer:
    def normalize(self, raw:str, input_type:str, region:str|None=None)->dict:
        raw=raw.strip(); region=region or os.getenv("AURORA_DEFAULT_REGION","RU")
        if input_type=="phone":
            cleaned=re.sub(r"[^\d+]","",raw)
            if cleaned.startswith("8") and len(re.sub(r"\D","",cleaned))==11: cleaned="+7"+cleaned[1:]
            if cleaned.startswith("00"): cleaned="+"+cleaned[2:]
            parsed=phonenumbers.parse(cleaned, region)
            e164=phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            return {"raw":raw,"type":input_type,"normalized":e164,"valid":phonenumbers.is_valid_number(parsed),"country":phonenumbers.region_code_for_number(parsed),"operator":carrier.name_for_number(parsed,"ru"),"location":geocoder.description_for_number(parsed,"ru"),"line_type":"не подтверждено","timezones":list(phtz.time_zones_for_number(parsed))}
        if input_type=="email": return {"raw":raw,"type":input_type,"normalized":raw.casefold(),"domain":raw.split('@')[-1].casefold(),"valid":bool(EMAIL_RE.fullmatch(raw))}
        if input_type in {"username","telegram_username"}: return {"raw":raw,"type":input_type,"normalized":raw.lstrip('@').casefold(),"valid":bool(USERNAME_RE.fullmatch(raw))}
        if input_type=="url": return {"raw":raw,"type":input_type,"normalized":raw,"domain":urlparse(raw).netloc.lower().removeprefix('www.'),"valid":safe_url(raw)}
        return {"raw":raw,"type":input_type,"normalized":raw.casefold() if input_type=="domain" else raw,"valid":True}

def mask_sensitive(v:str)->str:
    return EMAIL_RE.sub(lambda m:m.group(0)[:2]+"***@"+m.group(0).split('@')[-1], re.sub(r"\+?\d[\d\s().-]{6,}\d", lambda m: re.sub(r"\d(?=\d{2})","*",m.group(0)), v or ""))
def safe_url(url:str)->bool:
    p=urlparse(url); 
    if p.scheme not in {"http","https"} or not p.netloc: return False
    host=p.hostname or ""
    try:
        ip=ipaddress.ip_address(socket.gethostbyname(host))
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast)
    except Exception: return False
def clean_text(s:str)->str:
    
    if BeautifulSoup is None:
        value = re.sub(r"<script\b[^>]*>.*?</script>", " ", s or "", flags=re.I|re.S)
        value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I|re.S)
        value = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", html.unescape(value)).strip()
    soup=BeautifulSoup(s or "","html.parser")
    for t in soup(["script","style","nav","form","button"]): t.decompose()
    return re.sub(r"\s+"," ",html.unescape(soup.get_text(" "))).strip()
def domain(url:str)->str: return urlparse(url).netloc.lower().removeprefix("www.")
def independent_key(ev:dict)->str: return hashlib.sha1(((domain(ev.get('source_url','')) or ev.get('source',''))+ev.get('content_hash','')[:12]).encode()).hexdigest()

class BaseConnector:
    id="base"; name="Base"; supported_input_types=[]; capabilities=[]; requires_api_key=False; api_env_vars=[]; priority=100; timeout_seconds=10; rate_limit=10; enabled=True
    def __init__(self,cfg=None):
        cfg=cfg or {}; self.enabled=cfg.get('enabled',self.enabled); self.timeout_seconds=cfg.get('timeout',self.timeout_seconds); self.priority=cfg.get('priority',self.priority); self.rate_limit=cfg.get('rate_limit',self.rate_limit); self.cache_ttl=cfg.get('cache_ttl',3600); self.failures=0
    async def health_check(self): return {"ok":self.enabled,"missing_env":[v for v in self.api_env_vars if not os.getenv(v)]}
    async def search(self, normalized_input): raise NotImplementedError
    def normalize(self,result): return result
    async def close(self): pass
    async def run(self, inp):
        st=datetime.now(timezone.utc); start=time.monotonic()
        if not self.enabled: status,w,e,ents,ev="DISABLED",[],[],[],[]
        elif any(not os.getenv(v) for v in self.api_env_vars): status,w,e,ents,ev="CONFIGURATION_REQUIRED",["Нужны переменные: "+", ".join(self.api_env_vars)],[],[],[]
        else:
            try:
                data=await asyncio.wait_for(self.search(inp), timeout=self.timeout_seconds); status,w,e,ents,ev=data.status,data.warnings,data.errors,data.entities,data.evidence
            except asyncio.TimeoutError: status,w,e,ents,ev="TIMEOUT",[],["timeout"],[],[]
            except Exception as ex: status,w,e,ents,ev="ERROR",[],[mask_sensitive(str(ex))],[],[]
        done=datetime.now(timezone.utc); return ConnectorResult(self.id,status,st.isoformat(),done.isoformat(),int((time.monotonic()-start)*1000),ents,ev,w,e,metadata={"requires_api_key":self.requires_api_key,"env_vars":self.api_env_vars})

class PhoneMetadataConnector(BaseConnector):
    id="phone_metadata"; name="Phone metadata"; supported_input_types=["phone"]; capabilities=["normalize","carrier","country"]
    async def search(self,inp):
        ev=Evidence("ev_phone_metadata","phonenumbers",source_type="local",title="Метаданные номера",excerpt="Страна, регион и оператор определены локальной библиотекой.",reliability=.85,direct_match=True)
        ent={"type":"phone","claims":[{"field":"phone","value":inp['normalized'],"normalized_value":inp['normalized'],"evidence_ids":[ev.id]}]}
        return ConnectorResult(self.id,"OK","","",0,[ent],[asdict(ev)])
class WebSearchConnector(BaseConnector):
    id="public_web_search"; name="Public web search"; supported_input_types=["phone","email","username","telegram_username","domain","url","ip_address","organization","person_name"]; capabilities=["mentions"]
    async def search(self,inp):
        q='"%s"'%inp['normalized']; rows=[]
        def work():
            with DDGS(timeout=min(10,self.timeout_seconds)) as ddgs: return list(ddgs.text(q,max_results=int(os.getenv('AURORA_SEARCH_MAX_RESULTS','8'))) or [])
        rows=await asyncio.to_thread(work); evs=[]
        for i,r in enumerate(rows):
            url=str(r.get('href') or r.get('url') or ''); text=clean_text((r.get('title','')+' '+(r.get('body') or r.get('snippet') or '')))
            if not url or not text: continue
            evs.append(asdict(Evidence(f"ev_web_{i}","public_web_search",url,"search_result",clean_text(r.get('title','')),text[:500],reliability=.45,direct_match=inp['normalized'].casefold() in text.casefold(),content_hash=hashlib.sha256(text.encode()).hexdigest())))
        return ConnectorResult(self.id,"OK","","",0,[],evs)
class CommandConnector(BaseConnector):
    command=[]
    async def search(self,inp):
        if not shutil.which(self.command[0]): return ConnectorResult(self.id,"CONFIGURATION_REQUIRED","","",0,warnings=[f"Не найден бинарник {self.command[0]}"])
        cmd=[c.format(value=inp['normalized']) for c in self.command]
        p=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT); out=await p.communicate(); text=(out[0] or b'').decode(errors='ignore')[:20000]
        ev=Evidence(f"ev_{self.id}",self.id,source_type="local_tool",title=self.name,excerpt=mask_sensitive(text[:1000]),reliability=.55,direct_match=True,content_hash=hashlib.sha256(text.encode()).hexdigest())
        return ConnectorResult(self.id,"OK" if p.returncode==0 else "ERROR","","",0,evidence=[asdict(ev)],raw_reference=f"{self.id}.txt")
class SherlockConnector(CommandConnector): id="sherlock"; name="Sherlock"; supported_input_types=["username","telegram_username"]; command=["sherlock","{value}","--print-found"]
class MaigretConnector(CommandConnector): id="maigret"; name="Maigret"; supported_input_types=["username","telegram_username"]; command=["maigret","{value}","--no-progressbar"]
class HoleheConnector(CommandConnector): id="holehe"; name="Holehe"; supported_input_types=["email"]; command=["holehe","{value}","--only-used"]
class PhoneInfogaConnector(CommandConnector): id="phoneinfoga"; name="PhoneInfoga"; supported_input_types=["phone"]; command=["phoneinfoga","scan","-n","{value}"]
class ApiConnector(BaseConnector):
    url=""; api_env_vars=[]; requires_api_key=True
    async def search(self,inp):
        def req(): return requests.get(self.url.format(value=inp['normalized']),headers=self.headers(),timeout=self.timeout_seconds)
        r=await asyncio.to_thread(req)
        if r.status_code==401: return ConnectorResult(self.id,"CONFIGURATION_REQUIRED","","",0,errors=["401 Unauthorized"])
        if r.status_code==429: return ConnectorResult(self.id,"RATE_LIMITED","","",0,warnings=["429 rate limit"])
        r.raise_for_status(); text=r.text[:5000]
        ev=Evidence(f"ev_{self.id}",self.name,self.url,"api",self.name,mask_sensitive(text[:800]),.7,True,hashlib.sha256(text.encode()).hexdigest())
        return ConnectorResult(self.id,"OK","","",0,evidence=[asdict(ev)])
    def headers(self): return {}
class VT(ApiConnector): id="virustotal"; name="VirusTotal"; supported_input_types=["domain","url","ip_address"]; api_env_vars=["VIRUSTOTAL_API_KEY"]; url="https://www.virustotal.com/api/v3/domains/{value}"; headers=lambda self:{"x-apikey":os.getenv('VIRUSTOTAL_API_KEY','')}
class Shodan(ApiConnector): id="shodan"; name="Shodan"; supported_input_types=["ip_address","domain"]; api_env_vars=["SHODAN_API_KEY"]; url="https://api.shodan.io/shodan/host/{value}?key="+os.getenv('SHODAN_API_KEY','')
class Censys(ApiConnector): id="censys"; name="Censys"; supported_input_types=["domain","ip_address"]; api_env_vars=["CENSYS_API_ID","CENSYS_API_SECRET"]; url="https://search.censys.io/api/v2/hosts/{value}"
class SecurityTrails(ApiConnector): id="securitytrails"; name="SecurityTrails"; supported_input_types=["domain"]; api_env_vars=["SECURITYTRAILS_API_KEY"]; url="https://api.securitytrails.com/v1/domain/{value}"; headers=lambda self:{"APIKEY":os.getenv('SECURITYTRAILS_API_KEY','')}
class HIBP(ApiConnector): id="haveibeenpwned"; name="Have I Been Pwned"; supported_input_types=["email"]; api_env_vars=["HIBP_API_KEY"]; url="https://haveibeenpwned.com/api/v3/breachedaccount/{value}?truncateResponse=true"; headers=lambda self:{"hibp-api-key":os.getenv('HIBP_API_KEY',''),"user-agent":"AURORA"}
class Twilio(ApiConnector): id="twilio_lookup"; name="Twilio Lookup"; supported_input_types=["phone"]; api_env_vars=["TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN"]; url="https://lookups.twilio.com/v2/PhoneNumbers/{value}"
class IPQS(ApiConnector): id="ipqualityscore"; name="IPQualityScore"; supported_input_types=["phone","email","ip_address","url"]; api_env_vars=["IPQUALITYSCORE_API_KEY"]; url="https://ipqualityscore.com/api/json/phone/"+os.getenv('IPQUALITYSCORE_API_KEY','')+"/{value}"
class AbstractPhone(ApiConnector): id="abstract_phone"; name="Abstract Phone Validation"; supported_input_types=["phone"]; api_env_vars=["ABSTRACT_PHONE_API_KEY"]; url="https://phonevalidation.abstractapi.com/v1/?api_key="+os.getenv('ABSTRACT_PHONE_API_KEY','')+"&phone={value}"
class SimpleHttpConnector(ApiConnector): requires_api_key=False; api_env_vars=[]
class RDAP(SimpleHttpConnector): id="rdap_whois"; name="RDAP/WHOIS"; supported_input_types=["domain","ip_address"]; url="https://rdap.org/domain/{value}"
class CT(SimpleHttpConnector): id="certificate_transparency"; name="Certificate Transparency"; supported_input_types=["domain"]; url="https://crt.sh/?q={value}&output=json"
class Wayback(SimpleHttpConnector): id="wayback_cdx"; name="Wayback CDX"; supported_input_types=["domain","url"]; url="https://web.archive.org/cdx?url={value}&output=json&limit=10"
class Github(SimpleHttpConnector): id="github_public"; name="GitHub public API"; supported_input_types=["email","username","organization","domain"]; url="https://api.github.com/search/users?q={value}"
class DNS(BaseConnector):
    id="dns_lookup"; name="DNS lookup"; supported_input_types=["domain"]
    async def search(self,inp):
        ips=await asyncio.to_thread(socket.getaddrinfo, inp['normalized'], None); vals=sorted({x[4][0] for x in ips}); ev=Evidence("ev_dns","dns",source_type="dns",title="DNS A/AAAA",excerpt=", ".join(vals),reliability=.8,direct_match=True); return ConnectorResult(self.id,"OK","","",0,evidence=[asdict(ev)])

CONNECTOR_CLASSES=[PhoneMetadataConnector,WebSearchConnector,RDAP,CT,Wayback,Github,DNS,PhoneInfogaConnector,SherlockConnector,MaigretConnector,HoleheConnector,VT,Shodan,Censys,SecurityTrails,HIBP,Twilio,IPQS,AbstractPhone]

def load_cfg():
    p=Path(os.getenv('AURORA_CONNECTORS_CONFIG','config/connectors.yaml'))
    
    if not p.exists(): return {"connectors":{}}
    if yaml is None: return {"connectors":{}}
    return yaml.safe_load(p.read_text(encoding='utf-8'))
class SearchPlanner:
    def __init__(self,cfg): self.cfg=cfg
    def connectors_for(self,input_type):
        conns=[]
        for cls in CONNECTOR_CLASSES:
            c=cls(self.cfg.get('connectors',{}).get(cls.id,{}))
            if input_type in c.supported_input_types: conns.append(c)
        return sorted(conns,key=lambda c:c.priority)
class ConnectorOrchestrator:
    def __init__(self,conns,limit=6): self.conns=conns; self.sem=asyncio.Semaphore(limit)
    async def run(self,inp):
        async def one(c):
            async with self.sem: return asdict(await c.run(inp))
        return await asyncio.gather(*(one(c) for c in self.conns))
class CandidateFilter:
    def valid_person(self,value, evidence, input_value):
        v=re.sub(r"\s+"," ",value).strip(); cf=v.casefold()
        if cf in PHONE_STOPLIST or any(s in cf for s in PHONE_STOPLIST): return False,"stoplist/template"
        if not re.fullmatch(r"[А-ЯЁ][а-яё-]{1,30}(\s+[А-ЯЁ][а-яё-]{1,30}){1,3}",v): return False,"not_name_shape"
        if any(domain(e.get('source_url','')) in LOW_TRUST_PHONE_DOMAINS for e in evidence): return False,"low_trust_phone_catalog"
        if not any(input_value.casefold() in (e.get('excerpt','')+e.get('title','')).casefold() for e in evidence): return False,"identifier_not_in_context"
        return True,""
    def valid_email(self,value,evidence,input_value):
        if not EMAIL_RE.fullmatch(value): return False,"invalid_email"
        if not any(input_value.casefold() in (e.get('excerpt','')+e.get('title','')).casefold() for e in evidence): return False,"no_context_link"
        return True,""
class EntityResolver:
    def resolve(self, inp, runs):
        evidence=[e for r in runs for e in r.get('evidence',[])]; rejected=[]; claims=[]; filt=CandidateFilter(); input_value=inp['normalized']
        phone_claim=EntityClaim('phone' if inp['type']=='phone' else inp['type'], inp['normalized'], inp['normalized'], 90 if inp.get('valid') else 40, 'Подтверждено' if inp.get('valid') else 'Гипотеза',1,1,[e['id'] for e in evidence[:1]],extraction_method='input_normalizer',reasoning_summary='Исходный идентификатор нормализован.')
        entities=[Entity('entity_input', 'phone' if inp['type']=='phone' else inp['type'], [phone_claim])]
        # Conservative: only parse emails from evidence; names require strict context + independent trusted source
        by_email={}
        for ev in evidence:
            for em in EMAIL_RE.findall(ev.get('excerpt','')): by_email.setdefault(em.casefold(), {"value":em,"evidence":[]})['evidence'].append(ev)
            for nm in PERSON_RE.findall(ev.get('excerpt','')):
                ok,reason=filt.valid_person(nm,[ev],input_value)
                if not ok: rejected.append(asdict(RejectedCandidate(nm,'person',reason,ev.get('source_url',''),ev.get('excerpt','')[:250])))
        for item in by_email.values():
            ok,reason=filt.valid_email(item['value'],item['evidence'],input_value)
            if not ok: rejected.append(asdict(RejectedCandidate(item['value'],'email',reason,item['evidence'][0].get('source_url',''),item['evidence'][0].get('excerpt','')[:250]))); continue
            ents=item['evidence']; inds=len({independent_key(e) for e in ents}); score=ConfidenceScorer().score(True, sum(e.get('reliability',.5) for e in ents)/len(ents), inds, .8, [])
            entities.append(Entity('email_'+hashlib.sha1(item['value'].encode()).hexdigest()[:8], 'email', [EntityClaim('email',item['value'],item['value'].casefold(),score['final_score'],'Вероятно' if score['final_score']>=60 else 'Гипотеза',len(ents),inds,[e['id'] for e in ents],extraction_method='content_context',reasoning_summary='Email найден в контексте исходного идентификатора.',confidence_breakdown=score)]))
        return [asdict(e) for e in entities], evidence, rejected
class ConfidenceScorer:
    def score(self, exact, reliability, independent, context, penalties):
        d={"base_score":35 if exact else 15,"source_reliability":round(reliability*25),"independent_confirmation":min(20, max(0,independent-1)*10),"context_strength":round(context*15),"recency":5,"penalties":penalties}; d['final_score']=max(1,min(95,d['base_score']+d['source_reliability']+d['independent_confirmation']+d['context_strength']+d['recency']-sum(penalties or []))); return d
class SummaryGenerator:
    def build(self,inp,entities,runs,rejected):
        has_email=any(e['type']=='email' for e in entities); has_person=any(e['type']=='person' for e in entities)
        return {"headline":"Проверка завершена: подтверждённые связи показаны ниже; неподтверждённые шаблонные совпадения отброшены.","fio":"не подтверждено" if not has_person else "см. подтвержденные сущности","email":"не подтвержден" if not has_email else "см. подтвержденные сущности","connector_statuses":[{"id":r['connector_id'],"status":r['status'],"warnings":r.get('warnings',[])} for r in runs],"rejected_count":len(rejected)}
async def run_pipeline(raw:str, case_id:str='case')->SearchCase:
    it=InputClassifier().classify(raw); inp=InputNormalizer().normalize(raw,it); cfg=load_cfg(); conns=SearchPlanner(cfg).connectors_for(it); runs=await ConnectorOrchestrator(conns,cfg.get('concurrency',6)).run(inp); entities,evidence,rejected=EntityResolver().resolve(inp,runs); summary=SummaryGenerator().build(inp,entities,runs,rejected); return SearchCase(case_id,inp,runs,entities,evidence,rejected,summary)
def run_pipeline_sync(raw:str, case_id:str='case')->dict: return asdict(asyncio.run(run_pipeline(raw,case_id)))
