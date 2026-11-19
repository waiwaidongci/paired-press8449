from sqlalchemy import Column,Integer,String,JSON,ForeignKey,UniqueConstraint
from src.config.database import Base
class HoldoutSample(Base):
    # Holdout readings live in their own table so ordinary observation queries
    # and analysis snapshots cannot reach them by accident.
    __tablename__='holdout_samples'
    __table_args__=(UniqueConstraint('study_id','source_key'),)
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    source_key=Column(String(100),nullable=False)
    values=Column(JSON,nullable=False)
    created_at=Column(String(40),nullable=False)
