from sqlalchemy import Column,Integer,String,ForeignKey,UniqueConstraint
from src.config.database import Base
class SampleKey(Base):
    # Durable provenance for every paper-sample identifier. The row survives
    # deletion of the sample itself, so an explored key can never later become
    # a holdout key (and a holdout key never leaks into exploration).
    __tablename__='sample_keys'
    __table_args__=(UniqueConstraint('study_id','source_key'),)
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    source_key=Column(String(100),nullable=False)
    kind=Column(String(10),nullable=False)
    created_at=Column(String(40),nullable=False)
