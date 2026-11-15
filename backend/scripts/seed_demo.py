import random
from sqlalchemy import select,func
from src.config.database import Base,engine,SessionLocal
from src.models import User,SampleBatch,SampleUnit,MarginTarget,WeightRun,WeightReview,RegisterVersion,CorrectionPackage,CorrectionConflict
from src.utils.security import hash_password
from src.services.run_service import compute

def seed():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for role,name in [('admin','周衡 · 抽样负责人'),('analyst','陈野 · 交通分析师'),('viewer','陆遥 · 研究阅读者')]:
            if not db.scalar(select(User).where(User.email==role+'@balance.demo')):db.add(User(email=role+'@balance.demo',name=name,role=role,password_hash=hash_password('Balance2026!')))
        db.commit()
        for j,(code,name,n,total) in enumerate([('nov-city','11月城区出行样本',800,10000),('oct-pilot','10月试采对照',400,5000),('west-check','西区补采研究',80,1000)]):
            batch=db.scalar(select(SampleBatch).where(SampleBatch.code==code))
            if not batch:batch=SampleBatch(code=code,name=name,source_file='yy-travel-sample.csv',description='匿名合成出行样本；样本结构与目标边际不同。');db.add(batch);db.flush()
            existing=set(db.scalars(select(SampleUnit.code).where(SampleUnit.batch_id==batch.id)));rng=random.Random(73+j)
            for i in range(n):
                c=f'YY{j}-{i+1:04d}';zone=rng.choices(['中心','东区','西区'],[.6,.2,.2])[0];age=rng.choices(['青年','中年','长者'],[.6,.3,.1])[0];mode=rng.choices(['小汽车','公交','轨道'],[.6,.25,.15])[0]
                minutes=round(max(3,18+{'中心':0,'东区':8,'西区':13}[zone]+{'小汽车':0,'公交':12,'轨道':7}[mode]+rng.gauss(0,5)),2)
                if c not in existing:db.add(SampleUnit(batch_id=batch.id,code=c,zone=zone,age_band=age,mode=mode,trip_minutes=minutes,base_weight=1))
            config={'zone':{'中心':.3,'东区':.45,'西区':.25},'age_band':{'青年':.35,'中年':.45,'长者':.2},'mode':{'小汽车':.3,'公交':.35,'轨道':.35}}
            for dim,margin in config.items():
                for cat,share in margin.items():
                    if not db.scalar(select(MarginTarget).where(MarginTarget.batch_id==batch.id,MarginTarget.dimension==dim,MarginTarget.category==cat)):db.add(MarginTarget(batch_id=batch.id,dimension=dim,category=cat,population=total*share))
        db.commit();user=db.scalar(select(User).where(User.role=='admin'))
        name='城区样本代表性 · 初始校准'
        run=db.scalar(select(WeightRun).where(WeightRun.name==name))
        if not run:
            batch=db.scalar(select(SampleBatch).where(SampleBatch.code=='nov-city'))
            run=WeightRun(name=name,batch_id=batch.id,created_by=user.id,tolerance=.00001,max_iterations=500,cap_ratio=12);db.add(run);db.commit();compute(db,run.id)
            if run.result['converged']:db.add(WeightReview(run_id=run.id,decision='approved',note='合成样本演示：边际已收敛，保留有效样本与方法边界。',reviewer_id=user.id));db.commit()
        seed_corrections(db,user)
        counts={name:db.scalar(select(func.count()).select_from(model)) for name,model in [('users',User),('batches',SampleBatch),('units',SampleUnit),('targets',MarginTarget),('runs',WeightRun),('reviews',WeightReview),('versions',RegisterVersion),('packages',CorrectionPackage),('conflicts',CorrectionConflict)]}
        print(counts);return counts

def correction_csv(rows):
    lines=['code,zone,age_band,mode,trip_minutes,base_weight']
    for r in rows:lines.append(','.join(str(r[k]) for k in ['code','zone','age_band','mode','trip_minutes','base_weight']))
    return '\n'.join(lines)

def seed_corrections(db,user):
    """演示更正包：初始底册版本、一个已合并包、一个等待未到达前序的包；按代码幂等。"""
    from src.services.correction_service import ensure_initial_version,import_correction,latest_version
    from src.schemas.correction import CorrectionInput
    batch=db.scalar(select(SampleBatch).where(SampleBatch.code=='nov-city'))
    for b in db.scalars(select(SampleBatch)):
        ensure_initial_version(db,b.id)
    db.commit()
    if db.scalar(select(CorrectionPackage).where(CorrectionPackage.code=='YY-FIX-001')):return
    base=db.scalar(select(RegisterVersion).where(RegisterVersion.batch_id==batch.id,RegisterVersion.version==1))
    rows={r['code']:r for r in base.snapshot}
    other=lambda options,current:next(x for x in options if x!=current)
    changed=[]
    for code,edits in [('YY0-0001',{'zone':other(['中心','东区','西区'],rows['YY0-0001']['zone'])}),('YY0-0002',{'trip_minutes':round(rows['YY0-0002']['trip_minutes']+5,2)}),('YY0-0003',{'mode':other(['小汽车','公交','轨道'],rows['YY0-0003']['mode']),'age_band':other(['青年','中年','长者'],rows['YY0-0003']['age_band'])})]:
        row={k:rows[code][k] for k in ['code','zone','age_band','mode','trip_minutes','base_weight']};row.update(edits);changed.append(row)
    import_correction(db,batch.id,CorrectionInput(code='YY-FIX-001',csv_text=correction_csv(changed)),user)
    row={k:rows['YY0-0004'][k] for k in ['code','zone','age_band','mode','trip_minutes','base_weight']};row['zone']=other(['中心','东区','西区'],row['zone'])
    import_correction(db,batch.id,CorrectionInput(code='YY-FIX-003',depends_on='YY-FIX-002',csv_text=correction_csv([row])),user)
if __name__=='__main__':seed()
