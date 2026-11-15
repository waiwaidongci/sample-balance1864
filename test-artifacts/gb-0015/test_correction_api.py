"""更正包API集成测试：合并、冲突、依赖、幂等、恢复、版本下载与历史运行隔离。"""
from conftest import (auth,make_batch,import_csv,post_correction,units,packages,correction_csv,BASE_CSV)

def setup_batch(client):
    headers=auth('admin')
    batch_id=make_batch(client,headers)
    import_csv(client,headers,batch_id,BASE_CSV)
    return headers,batch_id

def test_import_applies_and_versions_downloadable(client):
    headers,batch_id=setup_batch(client)
    r=post_correction(client,headers,batch_id,'FIX-1',correction_csv(('S1','西区','青年','小汽车',25,1)))
    assert r.status_code==201,r.text
    assert r.json()['status']=='applied'
    assert r.json()['applied_version']==2
    assert units(client,headers,batch_id)['S1']['zone']=='西区'
    versions=client.get(f'/batches/{batch_id}/register/versions',headers=headers).json()
    assert [v['version'] for v in versions]==[2,1]
    assert versions[0]['package_code']=='FIX-1' and versions[0]['sample_count']==3
    v1=client.get(f'/batches/{batch_id}/register/versions/1/csv',headers=headers)
    v2=client.get(f'/batches/{batch_id}/register/versions/2/csv',headers=headers)
    assert 'S1,中心' in v1.text and 'S1,西区' not in v1.text
    assert 'S1,西区' in v2.text

def test_independent_field_changes_merge(client):
    headers,batch_id=setup_batch(client)
    post_correction(client,headers,batch_id,'FIX-A',correction_csv(('S1','西区','青年','小汽车',25,1)))
    # 基于同一基线v1，改不同字段
    r=post_correction(client,headers,batch_id,'FIX-B',correction_csv(('S1','中心','青年','轨道',30,1)),base_version=1)
    assert r.json()['status']=='applied'
    s1=units(client,headers,batch_id)['S1']
    assert s1['zone']=='西区' and s1['mode']=='轨道' and s1['trip_minutes']==30

def test_same_field_different_values_conflict_and_resolve(client):
    headers,batch_id=setup_batch(client)
    post_correction(client,headers,batch_id,'FIX-A',correction_csv(('S1','东区','青年','小汽车',25,1)))
    r=post_correction(client,headers,batch_id,'FIX-B',correction_csv(('S1','西区','青年','小汽车',25,1)),base_version=1)
    assert r.json()['status']=='conflict'
    conflicts=r.json()['conflicts']
    assert len(conflicts)==1
    c=conflicts[0]
    assert (c['sample_code'],c['field'],c['base_value'],c['current_value'],c['incoming_value'])==('S1','zone','中心','东区','西区')
    assert units(client,headers,batch_id)['S1']['zone']=='东区'  # 冲突期间底册不动
    pkg=packages(client,headers,batch_id)['FIX-B']
    assert pkg['reason']=='1 个字段冲突待解决'
    # 解决：采用传入值
    r=client.post(f"/batches/{batch_id}/corrections/{pkg['id']}/resolve",json={'resolutions':[{'conflict_id':c['id'],'choice':'incoming'}]},headers=headers)
    assert r.status_code==200,r.text
    assert r.json()['status']=='applied'
    assert units(client,headers,batch_id)['S1']['zone']=='西区'
    # 重复提交解决：幂等返回已应用
    r=client.post(f"/batches/{batch_id}/corrections/{pkg['id']}/resolve",json={'resolutions':[{'conflict_id':c['id'],'choice':'incoming'}]},headers=headers)
    assert r.status_code==200 and r.json()['status']=='applied'
    assert len(client.get(f'/batches/{batch_id}/register/versions',headers=headers).json())==3  # 没有重复版本

def test_resolve_keep_current_and_custom_value(client):
    headers,batch_id=setup_batch(client)
    post_correction(client,headers,batch_id,'FIX-A',correction_csv(('S1','东区','青年','小汽车',25,1),('S2','中心','中年','公交',40,1.5)))
    r=post_correction(client,headers,batch_id,'FIX-B',correction_csv(('S1','西区','青年','小汽车',25,1),('S2','西区','中年','公交',40,1.5)),base_version=1)
    conflicts=r.json()['conflicts']
    resolutions=[{'conflict_id':conflicts[0]['id'],'choice':'current'},  # S1保留当前=东区
                 {'conflict_id':conflicts[1]['id'],'choice':'value','value':'南区'}]  # S2自定义
    pkg_id=packages(client,headers,batch_id)['FIX-B']['id']
    r=client.post(f'/batches/{batch_id}/corrections/{pkg_id}/resolve',json={'resolutions':resolutions},headers=headers)
    assert r.json()['status']=='applied',r.text
    assert units(client,headers,batch_id)['S1']['zone']=='东区'
    assert units(client,headers,batch_id)['S2']['zone']=='南区'

def test_same_new_value_converges_without_conflict(client):
    headers,batch_id=setup_batch(client)
    post_correction(client,headers,batch_id,'FIX-A',correction_csv(('S1','东区','青年','小汽车',25,1)))
    r=post_correction(client,headers,batch_id,'FIX-B',correction_csv(('S1','东区','青年','小汽车',25,1)),base_version=1)
    assert r.json()['status']=='applied'

def test_package_atomicity_unknown_code(client):
    headers,batch_id=setup_batch(client)
    r=post_correction(client,headers,batch_id,'FIX-BAD',correction_csv(('S1','西区','青年','小汽车',25,1),('S9','西区','青年','小汽车',25,1)))
    assert r.json()['status']=='failed'
    assert 'S9' in r.json()['reason']
    assert units(client,headers,batch_id)['S1']['zone']=='中心'  # 整包未写入
    assert len(client.get(f'/batches/{batch_id}/register/versions',headers=headers).json())==1

def test_failed_package_redelivery_with_same_code(client):
    headers,batch_id=setup_batch(client)
    post_correction(client,headers,batch_id,'FIX-X',correction_csv(('S9','西区','青年','小汽车',25,1)))
    assert packages(client,headers,batch_id)['FIX-X']['status']=='failed'
    r=post_correction(client,headers,batch_id,'FIX-X',correction_csv(('S3','中心','长者','轨道',55,2)))
    assert r.json()['status']=='applied',r.text
    assert units(client,headers,batch_id)['S3']['zone']=='中心'

def test_out_of_order_dependency_cascade(client):
    headers,batch_id=setup_batch(client)
    r=post_correction(client,headers,batch_id,'FIX-C',correction_csv(('S2','东区','长者','公交',40,1.5)),depends_on='FIX-B')
    assert r.json()['status']=='pending'
    assert r.json()['reason']=='等待前序包 FIX-B 到达'
    r=post_correction(client,headers,batch_id,'FIX-B',correction_csv(('S1','东区','青年','小汽车',25,1)))
    assert r.json()['status']=='applied'
    pkgs=packages(client,headers,batch_id)
    assert pkgs['FIX-C']['status']=='applied'  # 前序到达后级联合并
    assert units(client,headers,batch_id)['S2']['age_band']=='长者'

def test_conflict_blocks_dependents_but_not_independent(client):
    headers,batch_id=setup_batch(client)
    post_correction(client,headers,batch_id,'FIX-A',correction_csv(('S1','东区','青年','小汽车',25,1)))
    r=post_correction(client,headers,batch_id,'FIX-B',correction_csv(('S1','西区','青年','小汽车',25,1)),base_version=1)
    assert r.json()['status']=='conflict'
    r=post_correction(client,headers,batch_id,'FIX-C',correction_csv(('S2','东区','长者','公交',40,1.5)),depends_on='FIX-B')
    assert r.json()['status']=='pending'
    assert r.json()['reason']=='前序包 FIX-B 存在待解决冲突'
    r=post_correction(client,headers,batch_id,'FIX-D',correction_csv(('S3','中心','长者','轨道',55,2)))
    assert r.json()['status']=='applied'  # 独立包不受阻挡
    # 解决冲突后，后继级联
    pkg_b=packages(client,headers,batch_id)['FIX-B']
    detail=client.get(f"/batches/{batch_id}/corrections/{pkg_b['id']}",headers=headers).json()
    cid=detail['conflicts'][0]['id']
    client.post(f"/batches/{batch_id}/corrections/{pkg_b['id']}/resolve",json={'resolutions':[{'conflict_id':cid,'choice':'incoming'}]},headers=headers)
    pkgs=packages(client,headers,batch_id)
    assert pkgs['FIX-B']['status']=='applied' and pkgs['FIX-C']['status']=='applied'

def test_duplicate_delivery_idempotent(client):
    headers,batch_id=setup_batch(client)
    csv_text=correction_csv(('S1','西区','青年','小汽车',25,1))
    r1=post_correction(client,headers,batch_id,'FIX-1',csv_text)
    r2=post_correction(client,headers,batch_id,'FIX-1',csv_text)
    assert r1.json()['status']=='applied' and r2.json()['status']=='applied'
    assert r1.json()['id']==r2.json()['id']
    assert len(client.get(f'/batches/{batch_id}/register/versions',headers=headers).json())==2  # 不重复写版本
    # 同代码不同内容(已应用)：拒绝
    r=post_correction(client,headers,batch_id,'FIX-1',correction_csv(('S1','东区','青年','小汽车',25,1)))
    assert r.status_code==409

def test_recovery_matches_normal_processing(client):
    """模拟中断：直接落库待处理包，恢复扫描后与正常级联结果一致。"""
    headers,batch_id=setup_batch(client)
    from src.config.database import SessionLocal
    from src.models import CorrectionPackage
    from src.services.correction_service import parse_payload,payload_hash,recover_corrections
    rows=parse_payload(correction_csv(('S1','西区','青年','小汽车',25,1)))
    with SessionLocal() as db:
        db.add(CorrectionPackage(batch_id=batch_id,code='FIX-R',depends_on=None,base_version=1,status='pending',payload=rows,payload_hash=payload_hash(rows),created_by=1))
        db.commit()
    recover_corrections()
    assert packages(client,headers,batch_id)['FIX-R']['status']=='applied'
    assert units(client,headers,batch_id)['S1']['zone']=='西区'
    recover_corrections()  # 再次恢复：无副作用
    assert len(client.get(f'/batches/{batch_id}/register/versions',headers=headers).json())==2

def test_historical_run_delivers_original_samples(client):
    """更正合并后，旧校准结果仍按原样本交付。"""
    headers,batch_id=setup_batch(client)
    targets=[{'dimension':'zone','category':'中心','population':1000},{'dimension':'zone','category':'东区','population':1000},{'dimension':'zone','category':'西区','population':1000}]
    assert client.put(f'/batches/{batch_id}/targets',json={'targets':targets},headers=headers).status_code==200
    r=client.post('/runs',json={'name':'更正前校准','batch_id':batch_id,'tolerance':0.001,'max_iterations':200,'cap_ratio':8},headers=headers)
    run_id=r.json()['id']
    from src.config.database import SessionLocal
    from src.services.run_service import compute
    with SessionLocal() as db:compute(db,run_id)
    post_correction(client,headers,batch_id,'FIX-1',correction_csv(('S1','西区','青年','小汽车',25,1)))
    assert units(client,headers,batch_id)['S1']['zone']=='西区'  # 底册已更正
    run=client.get(f'/runs/{run_id}',headers=headers).json()
    s1=[a for a in run['result']['assignments'] if a['code']=='S1'][0]
    assert s1['zone']=='中心'  # 历史运行快照仍是原样本
    reviewer=auth('admin','reviewer@test.dev')
    client.post('/reviews',json={'run_id':run_id,'decision':'approved','note':'同意使用该权重口径'},headers=reviewer)
    exported=client.get(f'/runs/{run_id}/export',headers=headers).text
    assert 'S1,中心' in exported and 'S1,西区' not in exported

def test_permissions_and_validation(client):
    headers,batch_id=setup_batch(client)
    viewer=auth('viewer')
    r=post_correction(client,viewer,batch_id,'FIX-V',correction_csv(('S1','西区','青年','小汽车',25,1)))
    assert r.status_code==403
    assert client.get(f'/batches/{batch_id}/corrections',headers=viewer).status_code==200
    assert client.get(f'/batches/{batch_id}/register/versions',headers=viewer).status_code==200
    r=post_correction(client,headers,batch_id,'FIX-SELF',correction_csv(('S1','西区','青年','小汽车',25,1)),depends_on='FIX-SELF')
    assert r.status_code==422
    r=post_correction(client,headers,batch_id,'FIX-NOV',correction_csv(('S1','西区','青年','小汽车',25,1)),base_version=99)
    assert r.status_code==422
    r=client.post(f'/batches/{batch_id}/corrections',json={'code':'FIX-BADCSV','csv_text':'code,zone\nS1,西区'},headers=headers)
    assert r.status_code==422
    # 传统CSV导入遇重复编号仍整批拒收，并提示改用更正包
    r=client.post(f'/batches/{batch_id}/import',json={'csv_text':BASE_CSV},headers=headers)
    assert r.status_code==409 and '更正包' in r.json()['detail']

def test_partial_resolution_rejected(client):
    headers,batch_id=setup_batch(client)
    post_correction(client,headers,batch_id,'FIX-A',correction_csv(('S1','东区','青年','小汽车',30,1),('S2','西区','中年','公交',40,1.5)))
    r=post_correction(client,headers,batch_id,'FIX-B',correction_csv(('S1','西区','青年','小汽车',33,1),('S2','中心','中年','公交',44,1.5)),base_version=1)
    conflicts=r.json()['conflicts']
    assert len(conflicts)==3
    pkg_id=packages(client,headers,batch_id)['FIX-B']['id']
    r=client.post(f'/batches/{batch_id}/corrections/{pkg_id}/resolve',json={'resolutions':[{'conflict_id':conflicts[0]['id'],'choice':'incoming'}]},headers=headers)
    assert r.status_code==422  # 必须一次性解决全部开放冲突
    assert packages(client,headers,batch_id)['FIX-B']['status']=='conflict'
