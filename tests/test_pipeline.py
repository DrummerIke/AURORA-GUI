import asyncio, os
from aurora.pipeline import InputClassifier, InputNormalizer, CandidateFilter, ConfidenceScorer, EntityResolver, mask_sensitive, BaseConnector, ConnectorResult, independent_source_count
from aurora.report_renderer import build_report_view, render_report

def test_classification():
    c=InputClassifier(); assert c.classify('+7 999 123-45-67')=='phone'; assert c.classify('user@example.test')=='email'; assert c.classify('@aurora_test')=='telegram_username'; assert c.classify('example.org')=='domain'; assert c.classify('127.0.0.1')=='ip_address'
def test_normalization():
    n=InputNormalizer().normalize('8 (999) 123-45-67','phone','RU'); assert n['normalized']=='+79991234567'
    assert InputNormalizer().normalize('USER@Example.TEST','email')['normalized']=='user@example.test'
def test_false_person_stoplist():
    f=CandidateFilter(); assert not f.valid_person('Ваше Имя',[{'source_url':'https://example.org','excerpt':'+79991234567 Ваше Имя'}],'+79991234567')[0]
    assert not f.valid_person('Главная Коды',[{'source_url':'https://example.org','excerpt':'+79991234567 Главная Коды'}],'+79991234567')[0]
def test_false_email_context():
    f=CandidateFilter(); assert not f.valid_email('a@example.org',[{'excerpt':'contact us','title':'','source_url':'https://example.org'}],'+79991234567')[0]
def test_confidence_not_fixed_74():
    s=ConfidenceScorer().score(True,.8,2,.9,[])['final_score']; s2=ConfidenceScorer().score(False,.3,1,.2,[20])['final_score']; assert s!=74 and s!=s2
def test_masking():
    text=mask_sensitive('Call +79991234567 or test@example.org'); assert '+79991234567' not in text and 'test@example.org' not in text
def test_dedup_independence_rejected_names():
    runs=[{'evidence':[{'id':'e1','source_url':'https://who-call.me/x','excerpt':'+79991234567 Ваше Имя','title':'Кто звонил','reliability':.2,'content_hash':'a'}]}]
    ent, ev, rej, rel=EntityResolver().resolve({'type':'phone','normalized':'+79991234567','valid':True},runs); assert rej and ent[0]['type']=='phone' and not rel
def test_russian_name_requires_independent_contexts():
    evidence=[
        {'id':'e1','source_url':'https://company-a.example/contact','excerpt':'+79991234567 Иванов Иван Иванович','title':'Контакты','reliability':.6,'content_hash':'a'},
        {'id':'e2','source_url':'https://company-b.example/team','excerpt':'Иванов Иван Иванович +79991234567','title':'Команда','reliability':.7,'content_hash':'b'},
    ]
    entities, _, rejected, relationships=EntityResolver().resolve({'type':'phone','normalized':'+79991234567','valid':True,'claimed_name':'Иванов Иван Иванович'},[{'evidence':evidence}])
    people=[item for item in entities if item['type']=='person']
    assert people and people[0]['claims'][0]['independent_source_count']==2
    assert not [item for item in rejected if item['value']=='Иванов Иван Иванович']
    assert relationships[0]['target_entity_id']==people[0]['id']
def test_organization_is_aggregated_from_independent_contexts():
    evidence=[
        {'id':'o1','source':'web','source_url':'https://a.example/contact','source_type':'search_result','excerpt':'ООО «Синтетика Тест» +79991234567','title':'Контакты','reliability':.6,'content_hash':'oa'},
        {'id':'o2','source':'web','source_url':'https://b.example/card','source_type':'search_result','excerpt':'+7 999 123-45-67 ООО «Синтетика Тест»','title':'Карточка','reliability':.7,'content_hash':'ob'},
    ]
    entities, _, _, relationships=EntityResolver().resolve({'type':'phone','normalized':'+79991234567','valid':True,'claimed_name':''},[{'evidence':evidence}])
    organizations=[item for item in entities if item['type']=='organization']
    assert organizations and organizations[0]['claims'][0]['value']=='ООО «Синтетика Тест»'
    assert any(item['target_entity_id']==organizations[0]['id'] for item in relationships)
def test_template_organization_phrase_is_not_promoted():
    evidence=[{'id':'x','source':'web','source_url':'https://example.test/x','source_type':'search_result','excerpt':'ООО Ромашка телефон +79991234567','title':'Поиск','reliability':.9,'content_hash':'x'}]
    entities, _, _, _=EntityResolver().resolve({'type':'phone','normalized':'+79991234567','valid':True,'claimed_name':''},[{'evidence':evidence}])
    assert not [item for item in entities if item['type']=='organization']
def test_cloned_sources_are_not_independent():
    evidence=[
        {'source_url':'https://clone-a.example/x','content_hash':'same'},
        {'source_url':'https://clone-b.example/y','content_hash':'same'},
    ]
    assert independent_source_count(evidence)==1
def test_phone_route_requires_consent():
    from app import app
    client=app.test_client()
    assert client.post('/run/phone',data={'target':'+79991234567'}).status_code==400
def test_executive_report_prioritizes_conclusions(tmp_path):
    case={'id':'synthetic','input':{'type':'phone','raw':'+79991234567','normalized':'+79991234567','claimed_name':'Иванов Иван Иванович'},'purpose':'employment_due_diligence','consent':True,
          'entities':[{'id':'person1','type':'person','claims':[{'field':'full_name','value':'Иванов Иван Иванович','confidence':82,'verification_status':'Подтверждено','source_count':2,'independent_source_count':2,'evidence_ids':['e1'],'reasoning_summary':'Подтверждено синтетическими источниками.','confidence_breakdown':{}}]}],
          'evidence':[{'id':'e1','source':'synthetic','source_url':'https://example.test/evidence','source_type':'web','title':'Синтетическое доказательство','excerpt':'Тестовый контекст','retrieved_at':'2026-01-01'}],
          'connector_runs':[{'connector_id':'synthetic','status':'OK'}],'rejected_candidates':[],'relationships':[],'summary':{}}
    view=build_report_view(case); assert view['subject']=='Иванов Иван Иванович'
    render_report(case,tmp_path); report=(tmp_path/'report.html').read_text()
    assert report.index('Главные выводы') < report.index('Доказательства выводов')
    assert 'Компании и профессиональные связи' in report and 'Техническое состояние источников' in report
    assert '@media (max-width:680px)' in report and 'grid-template-columns:1fr' in report
class OkConnector(BaseConnector):
    id='ok'; supported_input_types=['phone']
    async def search(self,inp): return ConnectorResult(self.id,'OK','','',0,evidence=[{'id':'e','source':'t'}])
class TimeoutConnector(BaseConnector):
    id='slow'; supported_input_types=['phone']; timeout_seconds=.01
    async def search(self,inp): await asyncio.sleep(.1)
async def run(c): return await c.run({'normalized':'+79991234567'})
def test_connector_success_timeout_missing_key():
    assert asyncio.run(run(OkConnector())).status=='OK'
    assert asyncio.run(run(TimeoutConnector())).status=='TIMEOUT'
    c=OkConnector(); c.api_env_vars=['MISSING_AURORA_KEY']; assert asyncio.run(run(c)).status=='CONFIGURATION_REQUIRED'
def test_partial_success_crash():
    class Bad(BaseConnector):
        id='bad';
        async def search(self,inp): raise RuntimeError('boom +79991234567')
    r=asyncio.run(Bad().run({'normalized':'+79991234567'})); assert r.status=='ERROR' and '+79991234567' not in ''.join(r.errors)
