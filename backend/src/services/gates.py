import math,statistics
from scipy import stats
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.gate import ThresholdGate
from src.models.holdout import HoldoutSample
from src.models.observation import Observation
from src.models.sample_key import SampleKey
from src.services import studies
from src.services.audits import log
from src.services.domain_validation import validate_values
from src.utils.serializers import now

# Holdout readings never leave this module except as an aggregate judgment.
def _gate(db,study_id):
    return db.scalar(select(ThresholdGate).where(ThresholdGate.study_id==study_id))

def _threshold(value):
    try: value=float(value)
    except (TypeError,ValueError): raise HTTPException(422,'门槛必须是数值')
    if isinstance(value,bool) or not math.isfinite(value) or abs(value)>1e9:
        raise HTTPException(422,'门槛必须是有限数值')
    return value

def judge(sample,threshold):
    if not sample: raise ValueError('留验纸样为空')
    improved=n=0
    for row in sample:
        values=row['values']
        before=float(values['before']);after=float(values['after'])
        if not (math.isfinite(before) and math.isfinite(after)): raise ValueError('留验读数必须为有限数值')
        n+=1
        if before-after>=threshold: improved+=1
    p=float(stats.binomtest(improved,n,p=0.5,alternative='greater').pvalue)
    rate=improved/n
    conclusion=f'留验 {n} 张的单侧精确二项检验 p={p:.6g}（零假设达标率至多一半）；门槛 {threshold:.3f} ΔE。'
    return {'threshold':threshold,'sample_size':n,'improved_count':improved,'success_rate':rate,'p_value':p,
            'test':'单侧精确二项检验','null_hypothesis':'达标率 ≤ 0.5','alternative':'达标率 > 0.5',
            'conclusion':conclusion,
            'caveat':'留验样本在锁定时一次性冻结；补录不入样。p 值只反映与“至多一半”的相容程度，不代替业务决策。'}

# The judgment deliverable is threshold, sample size and p-value only. Raw
# improved counts/rates stay inside the service and are never serialized.
PUBLIC_RESULT_KEYS=('threshold','sample_size','p_value','test','null_hypothesis','alternative','conclusion','caveat')
def _public_result(result):
    return {k:result[k] for k in PUBLIC_RESULT_KEYS if k in result} if result else None

def public(gate):
    # Deliberately omits the frozen readings.
    return {'id':gate.id,'study_id':gate.study_id,'threshold':gate.threshold,'sample_size':gate.sample_size,
            'status':gate.status,'result':_public_result(gate.result),'error':gate.error,'locked_by':gate.locked_by,
            'created_at':gate.created_at,'completed_at':gate.completed_at}

def _resume(db,gate):
    # Only the single frozen judgment row is ever computed. Retrying an interrupted
    # or failed attempt resumes this row; it never adds a second judgment.
    if gate.result is None:
        try:
            gate.result=judge(gate.sample,gate.threshold);gate.status='completed';gate.error='';gate.completed_at=now()
        except Exception as e:
            gate.status='failed';gate.error=str(e)
        db.commit()
    return public(gate)

def resume(db,gate):
    # Idempotent: recomputes only a frozen gate that never got a result.
    return _resume(db,gate)

def list_holdout(db,study_id):
    studies.require(db,study_id)
    rows=[{'source_key':r.source_key,'created_at':r.created_at} for r in db.scalars(select(HoldoutSample).where(HoldoutSample.study_id==study_id).order_by(HoldoutSample.id))]
    return {'registered_count':len(rows),'samples':rows,'locked':_gate(db,study_id) is not None}

def register_holdout(db,study_id,data,user):
    studies.require(db,study_id)
    if _gate(db,study_id): raise HTTPException(409,'判定已锁定，留验纸样不可再补录')
    try: values=validate_values(data.values)
    except (ValueError,TypeError) as e: raise HTTPException(422,str(e))
    key=data.source_key
    prior=db.scalar(select(SampleKey).where(SampleKey.study_id==study_id,SampleKey.source_key==key))
    if prior: raise HTTPException(409,'该编号已使用过（探索或留验），不能重复登记为留验')
    if db.scalar(select(Observation.id).where(Observation.study_id==study_id,Observation.source_key==key)):
        raise HTTPException(409,'该编号已在探索分析中使用，不能转入留验')
    stamp=now()
    db.add(HoldoutSample(study_id=study_id,source_key=key,values=values,created_at=stamp))
    db.add(SampleKey(study_id=study_id,source_key=key,kind='holdout',created_at=stamp))
    try: db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'该编号已登记，不能重复')
    log(db,user,'holdout.register',f'{study_id}/{key}')
    db.commit()
    return {'source_key':key,'created_at':stamp,'registered_count':db.scalar(select(func.count()).select_from(HoldoutSample).where(HoldoutSample.study_id==study_id))}

def lock(db,study_id,data,user):
    studies.require(db,study_id)
    existing=_gate(db,study_id)
    if existing: return _resume(db,existing),False
    threshold=_threshold(data.threshold)
    rows=list(db.scalars(select(HoldoutSample).where(HoldoutSample.study_id==study_id).order_by(HoldoutSample.id)))
    if not rows: raise HTTPException(422,'请先登记至少一张留验纸样')
    sample=[{'source_key':r.source_key,'values':r.values} for r in rows]
    stamp=now()
    # Freeze first, judge second. If the process dies between the two, the same
    # frozen gateway is resumed on retry instead of creating another judgment.
    gate=ThresholdGate(study_id=study_id,threshold=threshold,sample=sample,sample_size=len(sample),status='locked',
                       result=None,error='',locked_by=user.email,created_at=stamp,completed_at=None)
    db.add(gate)
    try: db.flush()
    except IntegrityError:
        # Another lock won the single per-study judgment. Keep its threshold.
        db.rollback()
        winner=_gate(db,study_id)
        if not winner: raise HTTPException(409,'判定锁定冲突，请重试')
        return _resume(db,winner),False
    log(db,user,'gate.lock',f'{study_id} threshold={threshold} n={len(sample)}')
    db.commit()
    return _resume(db,gate),True

def get(db,study_id):
    studies.require(db,study_id)
    gate=_gate(db,study_id)
    return _resume(db,gate) if gate else None

def list_gates(db):
    return [_resume(db,g) for g in db.scalars(select(ThresholdGate).order_by(ThresholdGate.id.desc()))]

def suggestion(db,study_id):
    studies.require(db,study_id)
    improvisations=[]
    for row in db.scalars(select(Observation).where(Observation.study_id==study_id)):
        try: improvisations.append(float(row.values['before'])-float(row.values['after']))
        except (KeyError,TypeError,ValueError): continue
    if not improvisations:
        return {'exploration_size':0,'mean_improvement':None,'median_improvement':None,'min_improvement':None,'max_improvement':None,'suggested_threshold':None}
    median=statistics.median(improvisations)
    return {'exploration_size':len(improvisations),'mean_improvement':statistics.mean(improvisations),
            'median_improvement':median,'min_improvement':min(improvisations),'max_improvement':max(improvisations),
            'suggested_threshold':round(median,3)}
