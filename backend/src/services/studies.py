from fastapi import HTTPException
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from src.models.study import Study
from src.models.observation import Observation
from src.models.sample_key import SampleKey
from src.services.domain_validation import validate_values
from src.services.audits import log
from src.utils.serializers import record,now

def list_studies(db):
    data=[]
    for s in db.scalars(select(Study).order_by(Study.id)):
        x=record(s);x['row_count']=db.scalar(select(func.count()).select_from(Observation).where(Observation.study_id==s.id));data.append(x)
    return data

def create(db,data,user):
    if db.scalar(select(Study).where(Study.name==data.name)): raise HTTPException(409,'批次名称已存在')
    s=Study(**data.model_dump());db.add(s);log(db,user,'study.create',data.name);db.commit();return record(s)

def require(db,id):
    s=db.get(Study,id)
    if not s: raise HTTPException(404,'业务批次不存在')
    return s

def observations(db,id):
    require(db,id);return [record(x) for x in db.scalars(select(Observation).where(Observation.study_id==id).order_by(Observation.id))]

def backfill_provenance(db):
    # Observations recorded before provenance tracking existed still count as
    # explored, so they can never be re-registered as holdout samples.
    keys={(k.study_id,k.source_key) for k in db.scalars(select(SampleKey))}
    added=0
    for row in db.scalars(select(Observation)):
        if (row.study_id,row.source_key) in keys: continue
        db.add(SampleKey(study_id=row.study_id,source_key=row.source_key,kind='exploration',created_at=now()));added+=1
    if added: db.commit()
    return added

def save_observation(db,id,data,user,row_id=None):
    require(db,id)
    try: values=validate_values(data.values)
    except (ValueError,TypeError) as e: raise HTTPException(422,str(e))
    other=db.scalar(select(Observation).where(Observation.study_id==id,Observation.source_key==data.source_key))
    if other and other.id!=row_id: raise HTTPException(409,'源记录编号重复')
    # A key registered as holdout is quarantined from exploration from registration
    # onward, including a direct edit that tries to re-point an explored row at it.
    prior=db.scalar(select(SampleKey).where(SampleKey.study_id==id,SampleKey.source_key==data.source_key))
    if prior and prior.kind=='holdout': raise HTTPException(409,'该编号已登记为留验纸样，不能用于探索分析')
    if row_id:
        row=db.get(Observation,row_id)
        if not row or row.study_id!=id: raise HTTPException(404,'记录不存在')
    else:
        if len(observations(db,id))>=5000: raise HTTPException(422,'小型研究最多5000行')
        row=Observation(study_id=id,source_key=data.source_key,values=values);db.add(row)
    if prior and prior.kind!='exploration': raise HTTPException(409,'该编号已作其他用途')
    if not prior:
        db.add(SampleKey(study_id=id,source_key=data.source_key,kind='exploration',created_at=now()))
    row.source_key=data.source_key;row.values=values
    log(db,user,'observation.save',f'{id}/{data.source_key}')
    try: db.commit()
    except IntegrityError:
        # A concurrent holdout registration for the same key won; keep it isolated.
        db.rollback();raise HTTPException(409,'该编号已被留验登记占用，不能用于探索分析')
    return record(row)
