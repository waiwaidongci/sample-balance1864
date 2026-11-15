from sqlalchemy import String,Float,ForeignKey,UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base
# 数值列用DOUBLE：单精度FLOAT回读会产生25.170000076293945式噪声，
# 更正包按值三向合并要求CSV→库→快照→CSV往返完全一致。
class SampleUnit(Base):
    __tablename__='sample_units'
    __table_args__=(UniqueConstraint('batch_id','code',name='uq_batch_code'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('sample_batches.id'))
    code:Mapped[str]=mapped_column(String(60))
    zone:Mapped[str]=mapped_column(String(30))
    age_band:Mapped[str]=mapped_column(String(30))
    mode:Mapped[str]=mapped_column(String(30))
    trip_minutes:Mapped[float]=mapped_column(Float().with_variant(mysql.DOUBLE(),'mysql'))
    base_weight:Mapped[float]=mapped_column(Float().with_variant(mysql.DOUBLE(),'mysql'),default=1)
