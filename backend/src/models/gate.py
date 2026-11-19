from sqlalchemy import Column,Integer,String,Float,JSON,Text,ForeignKey
from src.config.database import Base
class ThresholdGate(Base):
    # One confirmatory judgment per study. The unique study_id makes concurrent
    # locks race for a single row; the winner's threshold is the only one kept.
    __tablename__='threshold_gates'
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),unique=True,nullable=False)
    threshold=Column(Float,nullable=False)
    # Frozen holdout readings at lock time. Never serialized to clients.
    sample=Column(JSON,nullable=False)
    sample_size=Column(Integer,nullable=False)
    status=Column(String(20),default='locked',nullable=False)
    result=Column(JSON,nullable=True)
    error=Column(Text,default='',nullable=False)
    locked_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)
    completed_at=Column(String(40),nullable=True)
