from datetime import datetime
from sqlalchemy import String,Integer,JSON,DateTime,ForeignKey,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base

class RegisterVersion(Base):
    """底册版本快照：每次底册变更(CSV导入/更正包合并)后记录完整状态，可下载。"""
    __tablename__='register_versions'
    __table_args__=(UniqueConstraint('batch_id','version',name='uq_batch_version'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('sample_batches.id'))
    version:Mapped[int]=mapped_column(Integer)
    source:Mapped[str]=mapped_column(String(120))
    package_code:Mapped[str|None]=mapped_column(String(60),nullable=True)
    sample_count:Mapped[int]=mapped_column(Integer,default=0)
    snapshot:Mapped[list]=mapped_column(JSON,default=list)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)

class CorrectionPackage(Base):
    """更正包：按基线版本diff的样本字段改动；包内全部成功才合并进底册。"""
    __tablename__='correction_packages'
    __table_args__=(UniqueConstraint('batch_id','code',name='uq_batch_package'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('sample_batches.id'))
    code:Mapped[str]=mapped_column(String(60))
    depends_on:Mapped[str|None]=mapped_column(String(60),nullable=True)
    base_version:Mapped[int]=mapped_column(Integer)
    status:Mapped[str]=mapped_column(String(20),default='pending')
    payload:Mapped[list]=mapped_column(JSON,default=list)
    payload_hash:Mapped[str]=mapped_column(String(64))
    error:Mapped[str|None]=mapped_column(String(500),nullable=True)
    applied_version:Mapped[int|None]=mapped_column(Integer,nullable=True)
    created_by:Mapped[int]=mapped_column(ForeignKey('users.id'))
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    applied_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)

class CorrectionConflict(Base):
    """字段级冲突：同一样本同一字段被改成不同新值时列出，人工解决后强制写入。"""
    __tablename__='correction_conflicts'
    id:Mapped[int]=mapped_column(primary_key=True)
    package_id:Mapped[int]=mapped_column(ForeignKey('correction_packages.id'))
    sample_code:Mapped[str]=mapped_column(String(60))
    field:Mapped[str]=mapped_column(String(20))
    base_value:Mapped[str]=mapped_column(String(60))
    current_value:Mapped[str]=mapped_column(String(60))
    incoming_value:Mapped[str]=mapped_column(String(60))
    status:Mapped[str]=mapped_column(String(20),default='open')
    resolution:Mapped[str|None]=mapped_column(String(60),nullable=True)
    resolved_by:Mapped[str|None]=mapped_column(String(100),nullable=True)
    resolved_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
