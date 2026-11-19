import math, threading, pytest
from fastapi.testclient import TestClient
from src.main import app
from src.config.database import Session, engine, Base
from src.models import user,study,observation,run,review,audit,holdout,sample_key,gate
from src.services import gates
from src.utils.security import hash_password

Base.metadata.create_all(engine)
with Session() as db:
    for role in ('admin','analyst','viewer'):
        db.add(user.User(email=role+'@x',role=role,password_hash=hash_password('pw')))
    s=study.Study(name='S1',source_filename='f.csv',description='')
    db.add(s);db.commit();sid=s.id
    for i in range(6):
        db.add(observation.Observation(study_id=sid,source_key=f'E{i}',values={'before':5.0,'after':4.0}))
    db.commit()

client=TestClient(app)
def login(email):
    r=client.post('/auth/login',json={'email':email,'password':'pw'});assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}
W=login('analyst@x'); V=login('viewer@x'); A=login('admin@x')

def test_judge_math():
    sample=[{'source_key':f'h{i}','values':{'before':5.0,'after':4.0}} for i in range(5)]
    r=gates.judge(sample,0.5)
    assert r['improved_count']==5 and r['sample_size']==5
    assert abs(r['p_value']-1/32)<1e-12
    r2=gates.judge(sample,10)
    assert r2['improved_count']==0 and abs(r2['p_value']-1.0)<1e-12
    # exact one-sided: 3/5 successes p = (1+5+10)/32
    sample3=[{'source_key':str(i),'values':{'before':5.0,'after':4.0 if i<3 else 7.0}} for i in range(5)]
    assert abs(gates.judge(sample3,0.5)['p_value']-(1+5+10)/32)<1e-12

def test_quarantine_and_single_gate():
    # explored key cannot become holdout
    assert client.post(f'/studies/{sid}/holdout',json={'source_key':'E0','values':{'before':1,'after':0.5}},headers=W).status_code==409
    # register holdout
    for i in range(4):
        r=client.post(f'/studies/{sid}/holdout',json={'source_key':f'H{i}','values':{'before':5.0,'after':4.2}},headers=W)
        assert r.status_code==200,r.text
    # duplicate holdout key rejected
    assert client.post(f'/studies/{sid}/holdout',json={'source_key':'H0','values':{'before':1,'after':0}},headers=W).status_code==409
    # holdout key cannot enter exploration
    assert client.post(f'/studies/{sid}/observations',json={'source_key':'H1','values':{'before':1,'after':0}},headers=W).status_code==409
    # canceling/edit an existing explored row onto a holdout key also rejected
    rows=client.get(f'/studies/{sid}/observations',headers=W).json()
    r=client.put(f'/studies/{sid}/observations/{rows[0]["id"]}',json={'source_key':'H2','values':{'before':1,'after':0}},headers=W)
    assert r.status_code==409,r.text
    # holdout readings never in ordinary data/analysis/export
    data=client.get(f'/studies/{sid}/observations',headers=W).json()
    assert all(x['source_key'].startswith('E') for x in data)
    held=client.get(f'/studies/{sid}/holdout',headers=W).json()
    assert held['registered_count']==4
    assert all('values' not in x for x in held['samples'])
    # exploration run sees only exploration rows
    rr=client.post('/runs',json={'study_id':sid,'name':'explore','parameters':{'resamples':1000}},headers=W)
    assert rr.status_code==200,rr.text
    assert all(x['source_key'].startswith('E') for x in rr.json()['snapshot'])

def test_lock_concurrency_keeps_first():
    results=[]
    def attempt(t):
        c=TestClient(app)
        results.append(c.post(f'/studies/{sid}/gate',json={'threshold':t},headers=W))
    ts=[0.5,2.0]
    threads=[threading.Thread(target=attempt,args=(t,)) for t in ts]
    [x.start() for x in threads];[x.join() for x in threads]
    assert all(r.status_code==200 for r in results), [r.text for r in results]
    g=client.get(f'/studies/{sid}/gate',headers=W).json()
    assert g is not None and g['sample_size']==4 and g['status']=='completed'
    assert g['threshold'] in ts
    assert sum(1 for r in results if r.json()['created'])==1
    # all created responses agree with persisted threshold
    created=[r.json()['gate'] for r in results if r.json()['created']][0]
    assert created['threshold']==g['threshold']
    # no addition after lock
    assert client.post(f'/studies/{sid}/holdout',json={'source_key':'LATE','values':{'before':1,'after':0}},headers=W).status_code==409
    # registered keys still excluded; no holdout values leaked
    assert 'sample' not in g and 'values' not in str(g)
    # retry returns same judgment
    assert client.post(f'/studies/{sid}/gate',json={'threshold':99},headers=W).json()['created'] is False
    assert client.get(f'/studies/{sid}/gate',headers=W).json()['threshold']==g['threshold']

def test_resume_interrupted():
    # simulate crash after freeze: status locked, no result
    s2=study.Study(name='S2',source_filename='f.csv',description='')
    with Session() as db:
        db.add(s2);db.commit();sid2=s2.id
        db.add(holdout.HoldoutSample(study_id=sid2,source_key='Q1',values={'before':9,'after':1},created_at='t'))
        db.add(holdout.HoldoutSample(study_id=sid2,source_key='Q2',values={'before':1,'after':9},created_at='t'))
        db.add(gate.ThresholdGate(study_id=sid2,threshold=1.0,sample=[{'source_key':'Q1','values':{'before':9,'after':1}},{'source_key':'Q2','values':{'before':1,'after':9}}],sample_size=2,status='locked',result=None,error='',locked_by='analyst@x',created_at='t',completed_at=None))
        db.commit()
    g=client.get(f'/studies/{sid2}/gate',headers=W).json()
    assert g['status']=='completed' and g['sample_size']==2 and abs(g['result']['p_value']-0.75)<1e-12
    assert set(g['result'])<={'threshold','sample_size','p_value','test','null_hypothesis','alternative','conclusion','caveat'}
    # retry after recovery does not create a second judgment
    from sqlalchemy import select,func
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(gate.ThresholdGate).where(gate.ThresholdGate.study_id==sid2))==1

def test_viewer_can_read_not_register():
    assert client.get(f'/studies/{sid}/gate',headers=V).status_code==200
    assert client.post(f'/studies/{sid}/holdout',json={'source_key':'VV','values':{'before':1,'after':0}},headers=V).status_code==403

def test_no_empty_holdout():
    s3=study.Study(name='S3',source_filename='f.csv',description='')
    with Session() as db: db.add(s3);db.commit();sid3=s3.id
    r=client.post(f'/studies/{sid3}/gate',json={'threshold':1},headers=W)
    assert r.status_code==422

def test_deleted_explored_key_stays_explored():
    s4=study.Study(name='S4',source_filename='f.csv',description='')
    with Session() as db: db.add(s4);db.commit();sid4=s4.id
    r=client.post(f'/studies/{sid4}/observations',json={'source_key':'D1','values':{'before':5,'after':4}},headers=W)
    assert r.status_code==200
    row_id=r.json()['id']
    assert client.delete(f'/studies/{sid4}/observations/{row_id}',headers=W).status_code==200
    # provenance survives deletion
    assert client.post(f'/studies/{sid4}/holdout',json={'source_key':'D1','values':{'before':5,'after':4}},headers=W).status_code==409
    # re-entering exploration is allowed for the same explored key
    assert client.post(f'/studies/{sid4}/observations',json={'source_key':'D1','values':{'before':5,'after':4}},headers=W).status_code==200

def test_viewer_reads_aggregates_only():
    assert client.get(f'/studies/{sid}/holdout',headers=V).json()['registered_count']==4
    assert client.get(f'/studies/{sid}/gate/suggestion',headers=V).status_code==200
    assert client.post(f'/studies/{sid}/gate',json={'threshold':1},headers=V).status_code==403

def test_backfill_marks_legacy_observations_explored():
    from src.services.studies import backfill_provenance
    s5=study.Study(name='S5',source_filename='f.csv',description='')
    with Session() as db:
        db.add(s5);db.commit();sid5=s5.id
        db.add(observation.Observation(study_id=sid5,source_key='LEGACY',values={'before':5,'after':4}))
        db.commit()
        assert backfill_provenance(db)>=1
        assert backfill_provenance(db)==0
    assert client.post(f'/studies/{sid5}/holdout',json={'source_key':'LEGACY','values':{'before':5,'after':4}},headers=W).status_code==409
