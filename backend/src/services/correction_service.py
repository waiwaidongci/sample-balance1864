"""更正包服务：导入、三向合并、依赖级联、冲突解决、底册版本快照。

事务与并发口径：
- 每个批次一行锁(SELECT ... FOR UPDATE)串行化该批次的所有合并操作；
- 每个更正包的应用是独立事务：包内样本全部成功才写入底册，否则整体不落库；
- 状态机 pending → applied/conflict/failed 单调前进，中断后重跑 process_batch 结果相同；
- 重复投递按(批次,包代码)幂等：内容相同直接返回现状，内容不同仅失败包可替换重投。
"""
import csv,hashlib,io,json,logging
from datetime import datetime
from sqlalchemy import select,func,delete
from fastapi import HTTPException
from src.config.database import SessionLocal
from src.models import SampleBatch,SampleUnit,RegisterVersion,CorrectionPackage,CorrectionConflict
from src.utils.audit import record
from src.utils.serializers import serialize
from .batch_service import get_batch
from .merge_engine import normalize,normalize_row,compute_changes,detect_conflicts

def lock_row(stmt,db):
    """MySQL加行锁；SQLite(测试)无行锁语义，单写入者下直接读取。"""
    return stmt if db.bind.dialect.name=='sqlite' else stmt.with_for_update()

def lock_batch(db,batch_id):
    row=db.scalar(lock_row(select(SampleBatch).where(SampleBatch.id==batch_id),db))
    if not row:raise HTTPException(404,'样本批次不存在')
    return row

def register_rows(db,batch_id):
    return [serialize(u) for u in db.scalars(select(SampleUnit).where(SampleUnit.batch_id==batch_id).order_by(SampleUnit.code))]

def latest_version(db,batch_id):
    return db.scalar(select(func.max(RegisterVersion.version)).where(RegisterVersion.batch_id==batch_id)) or 0

def snapshot_version(db,batch_id,source,package_code=None):
    """在调用方持有批次锁的事务内记录当前底册完整快照，返回新版本号。"""
    rows=register_rows(db,batch_id)
    version=latest_version(db,batch_id)+1
    db.add(RegisterVersion(batch_id=batch_id,version=version,source=source,package_code=package_code,sample_count=len(rows),snapshot=rows))
    db.flush()
    return version

def ensure_initial_version(db,batch_id):
    """历史数据(种子/既有库)没有版本时，把当前底册登记为v1初始底册；幂等。"""
    if latest_version(db,batch_id)==0 and db.scalar(select(func.count()).select_from(SampleUnit).where(SampleUnit.batch_id==batch_id)):
        snapshot_version(db,batch_id,'初始底册')

def parse_payload(csv_text):
    """解析更正包CSV为规范行列表；语法问题直接422(不落成包)。"""
    try:rows=[normalize_row(x) for x in csv.DictReader(io.StringIO(csv_text.lstrip('\ufeff')))]
    except (ValueError,TypeError) as exc:raise HTTPException(422,f'更正包CSV无效：{exc}；需要列 code/zone/age_band/mode/trip_minutes/base_weight')
    if not rows or len(rows)>5000:raise HTTPException(422,'更正包需要1–5000行')
    codes=[r['code'] for r in rows]
    if len(set(codes))!=len(codes):raise HTTPException(422,'更正包内样本编号重复')
    return rows

def payload_hash(rows):
    canonical=json.dumps(rows,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(canonical.encode()).hexdigest()

def get_package(db,batch_id,package_id):
    row=db.get(CorrectionPackage,package_id)
    if not row or row.batch_id!=batch_id:raise HTTPException(404,'更正包不存在')
    return row

def dep_blocker(db,pkg):
    """返回阻塞该包的前序原因；None表示前序已满足，可尝试应用。"""
    if not pkg.depends_on:return None
    dep=db.scalar(select(CorrectionPackage).where(CorrectionPackage.batch_id==pkg.batch_id,CorrectionPackage.code==pkg.depends_on))
    if not dep:return f'等待前序包 {pkg.depends_on} 到达'
    if dep.status=='applied':return None
    return {'pending':f'前序包 {pkg.depends_on} 仍在待处理','conflict':f'前序包 {pkg.depends_on} 存在待解决冲突','failed':f'前序包 {pkg.depends_on} 未通过校验'}[dep.status]

def pending_reason(db,pkg):
    if pkg.status=='pending':return dep_blocker(db,pkg) or '等待合并调度'
    if pkg.status=='conflict':
        open_count=db.scalar(select(func.count()).select_from(CorrectionConflict).where(CorrectionConflict.package_id==pkg.id,CorrectionConflict.status=='open'))
        return f'{open_count} 个字段冲突待解决'
    if pkg.status=='failed':return pkg.error or '校验失败'
    return ''

def package_view(db,pkg,with_conflicts=False):
    data=serialize(pkg)
    data['reason']=pending_reason(db,pkg)
    data['conflict_count']=db.scalar(select(func.count()).select_from(CorrectionConflict).where(CorrectionConflict.package_id==pkg.id,CorrectionConflict.status=='open'))
    if with_conflicts:
        conflicts=db.scalars(select(CorrectionConflict).where(CorrectionConflict.package_id==pkg.id).order_by(CorrectionConflict.status,CorrectionConflict.id))
        data['conflicts']=[serialize(c) for c in conflicts]
    return data

def list_packages(db,batch_id):
    get_batch(db,batch_id)
    return [package_view(db,p) for p in db.scalars(select(CorrectionPackage).where(CorrectionPackage.batch_id==batch_id).order_by(CorrectionPackage.id))]

def package_detail(db,batch_id,package_id):
    get_batch(db,batch_id)
    return package_view(db,get_package(db,batch_id,package_id),with_conflicts=True)

def attempt_apply(db,batch_id,package_id,actor):
    """尝试应用一个包：独立事务，全部成功才写底册；冲突/失败只登记不写入。"""
    db.commit()  # 结束调用方可能遗留的只读事务，保证行锁与读快照从新事务开始
    lock_batch(db,batch_id)
    pkg=db.get(CorrectionPackage,package_id)
    if not pkg:db.commit();return
    db.refresh(pkg)  # expire_on_commit=False，必须在持锁事务内重读最新状态
    if pkg.status!='pending':db.commit();return
    base_row=db.scalar(select(RegisterVersion).where(RegisterVersion.batch_id==batch_id,RegisterVersion.version==pkg.base_version))
    units={u.code:u for u in db.scalars(select(SampleUnit).where(SampleUnit.batch_id==batch_id))}
    error=None
    if not base_row:error=f'基线版本 v{pkg.base_version} 已不存在，更正包未写入'
    else:
        base_map={r['code']:r for r in base_row.snapshot}
        changes,error=compute_changes(base_map,pkg.payload,set(units))
    if error:
        pkg.status='failed';pkg.error=error;record(db,actor,'fail_correction',pkg.code);db.commit();return
    current_map={code:serialize(u) for code,u in units.items()}
    resolved={}
    for c in db.scalars(select(CorrectionConflict).where(CorrectionConflict.package_id==pkg.id,CorrectionConflict.status=='resolved')):
        resolved[(c.sample_code,c.field)]=normalize(c.field,c.resolution)
    final,conflicts=detect_conflicts(changes,base_map,current_map,resolved)
    if conflicts:
        db.execute(delete(CorrectionConflict).where(CorrectionConflict.package_id==pkg.id,CorrectionConflict.status=='open'))
        for c in conflicts:
            db.add(CorrectionConflict(package_id=pkg.id,sample_code=c['sample_code'],field=c['field'],base_value=str(c['base']),current_value=str(c['current']),incoming_value=str(c['incoming'])))
        pkg.status='conflict';pkg.error=None
        record(db,actor,'conflict_correction',f'{pkg.code}:{len(conflicts)}')
        db.commit();return
    for code,fields in final.items():
        unit=units[code]
        for field,value in fields.items():setattr(unit,field,value)
    db.flush()
    version=snapshot_version(db,batch_id,f'更正包 {pkg.code}',package_code=pkg.code)
    pkg.status='applied';pkg.applied_version=version;pkg.applied_at=datetime.utcnow();pkg.error=None
    record(db,actor,'apply_correction',f'{pkg.code}:v{version}')
    db.commit()

def process_batch(db,batch_id,actor):
    """按到达顺序级联处理所有前序已满足的待处理包；冲突/失败只阻塞各自后继。"""
    while True:
        actionable=None
        candidates=list(db.scalars(select(CorrectionPackage).where(CorrectionPackage.batch_id==batch_id,CorrectionPackage.status=='pending').order_by(CorrectionPackage.id)))
        for pkg in candidates:
            if dep_blocker(db,pkg) is None:actionable=pkg;break
        db.commit()  # 释放发现查询的读事务，attempt_apply自行开启持锁事务
        if not actionable:break
        attempt_apply(db,batch_id,actionable.id,actor)

def import_correction(db,batch_id,data,user):
    """导入更正包；同代码同内容幂等返回，失败包允许同代码修正重投。"""
    lock_batch(db,batch_id)
    if data.depends_on==data.code:raise HTTPException(422,'更正包不能依赖自身')
    rows=parse_payload(data.csv_text)
    digest=payload_hash(rows)
    ensure_initial_version(db,batch_id)
    if latest_version(db,batch_id)==0:raise HTTPException(422,'底册为空，请先导入样本再投递更正包')
    base_version=data.base_version or latest_version(db,batch_id)
    if not db.scalar(select(RegisterVersion).where(RegisterVersion.batch_id==batch_id,RegisterVersion.version==base_version)):
        raise HTTPException(422,f'底册版本 v{base_version} 不存在，请先下载最新底册再更正')
    existing=db.scalar(select(CorrectionPackage).where(CorrectionPackage.batch_id==batch_id,CorrectionPackage.code==data.code))
    if existing:
        # 幂等判定：未显式指定基线时按已登记的基线为准(“最新版本”随时间变化，不参与比较)
        same=existing.payload_hash==digest and existing.depends_on==(data.depends_on or None) and (data.base_version is None or existing.base_version==data.base_version)
        if same:
            db.commit()
            return package_view(db,existing,with_conflicts=True)
        if existing.status!='failed':raise HTTPException(409,f'更正包 {data.code} 已存在且内容不同；仅校验失败的包可用同一代码重新投递')
        db.execute(delete(CorrectionConflict).where(CorrectionConflict.package_id==existing.id))
        existing.payload=rows;existing.payload_hash=digest;existing.depends_on=data.depends_on or None
        existing.base_version=base_version;existing.status='pending';existing.error=None
        record(db,user,'reimport_correction',data.code);db.commit()
        process_batch(db,batch_id,user.email)
        return package_view(db,db.get(CorrectionPackage,existing.id),with_conflicts=True)
    pkg=CorrectionPackage(batch_id=batch_id,code=data.code,depends_on=data.depends_on or None,base_version=base_version,payload=rows,payload_hash=digest,created_by=user.id)
    db.add(pkg);db.flush()
    record(db,user,'import_correction',data.code);db.commit()
    process_batch(db,batch_id,user.email)
    return package_view(db,db.get(CorrectionPackage,pkg.id),with_conflicts=True)

def resolve_conflicts(db,batch_id,package_id,data,user):
    """一次性提交全部开放冲突的解决值，随后重入合并流程；已应用的包重复提交幂等。"""
    lock_batch(db,batch_id)
    pkg=get_package(db,batch_id,package_id)
    if pkg.status=='applied':
        db.commit()
        return package_view(db,pkg,with_conflicts=True)
    if pkg.status!='conflict':raise HTTPException(409,'当前状态没有待解决的冲突')
    open_conflicts=list(db.scalars(select(CorrectionConflict).where(CorrectionConflict.package_id==pkg.id,CorrectionConflict.status=='open')))
    by_id={c.id:c for c in open_conflicts}
    if {r.conflict_id for r in data.resolutions}!=set(by_id):raise HTTPException(422,f'需一次性解决全部 {len(open_conflicts)} 个开放冲突')
    for item in data.resolutions:
        conflict=by_id[item.conflict_id]
        if item.choice=='incoming':value=conflict.incoming_value
        elif item.choice=='current':value=conflict.current_value
        else:
            if item.value is None:raise HTTPException(422,f'冲突 {conflict.id} 选择自定义值时必须提供 value')
            value=item.value
        try:value=str(normalize(conflict.field,value))
        except ValueError as exc:raise HTTPException(422,f'冲突 {conflict.id} 的解决值无效：{exc}')
        conflict.status='resolved';conflict.resolution=value;conflict.resolved_by=user.email;conflict.resolved_at=datetime.utcnow()
    pkg.status='pending'
    record(db,user,'resolve_conflicts',f'{pkg.code}:{len(open_conflicts)}')
    db.commit()
    process_batch(db,batch_id,user.email)
    return package_view(db,db.get(CorrectionPackage,pkg.id),with_conflicts=True)

def list_versions(db,batch_id):
    get_batch(db,batch_id)
    rows=db.scalars(select(RegisterVersion).where(RegisterVersion.batch_id==batch_id).order_by(RegisterVersion.version.desc()))
    return [serialize(v) for v in rows]

def version_csv(db,batch_id,version):
    get_batch(db,batch_id)
    row=db.scalar(select(RegisterVersion).where(RegisterVersion.batch_id==batch_id,RegisterVersion.version==version))
    if not row:raise HTTPException(404,'底册版本不存在')
    out=io.StringIO();out.write('\ufeff');writer=csv.writer(out)
    writer.writerow(['code','zone','age_band','mode','trip_minutes','base_weight'])
    for unit in row.snapshot:
        vals=[unit[k] for k in ['code','zone','age_band','mode','trip_minutes','base_weight']]
        vals=["'"+x if isinstance(x,str) and x.startswith(('=','+','-','@')) else x for x in vals]
        writer.writerow(vals)
    return out.getvalue()

def recover_corrections():
    """启动恢复：重跑所有仍有待处理包的批次；与并发合并同一口径，结果一致。"""
    with SessionLocal() as db:
        try:
            ids=list(db.scalars(select(CorrectionPackage.batch_id).where(CorrectionPackage.status=='pending').distinct()))
            db.commit()
            for batch_id in ids:process_batch(db,batch_id,'system')
        except Exception:logging.exception('correction recovery failed; service remains available')
