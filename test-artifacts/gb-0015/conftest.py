import os,sys,tempfile,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'backend'))
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mkstemp(suffix='.db')[1]
os.environ['SEED_DEMO']='false'
os.environ['JWT_SECRET']='test-secret'
import src.config.queue as queue_config

class FakeQueue:
    """内存版队列：测试环境没有Redis，限流与任务入队全部放行。"""
    def __init__(self):self.counts={}
    def incr(self,key):self.counts[key]=self.counts.get(key,0)+1;return self.counts[key]
    def expire(self,key,ttl):return True
    def ping(self):return True
    def rpush(self,*args):return 1
    def blpop(self,*args,**kwargs):return None

queue_config.queue=FakeQueue()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from src.main import app
from src.config.database import Base,engine,SessionLocal
from src.models import User
from src.utils.security import hash_password,token_for

@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:yield c

def auth(role='admin',email=None):
    """get-or-create用户并返回鉴权头。"""
    email=email or role+'@test.dev'
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email==email))
        if not user:
            user=User(email=email,name=email,role=role,password_hash=hash_password('Test2026!'))
            db.add(user);db.commit();db.refresh(user)
        return {'Authorization':'Bearer '+token_for(user)}

def make_batch(client,headers,code='b1'):
    r=client.post('/batches',json={'code':code,'name':'批次'+code,'description':''},headers=headers)
    assert r.status_code==201,r.text
    return r.json()['id']

def import_csv(client,headers,batch_id,csv_text):
    r=client.post(f'/batches/{batch_id}/import',json={'csv_text':csv_text},headers=headers)
    assert r.status_code==201,r.text
    return r

BASE_CSV='''code,zone,age_band,mode,trip_minutes,base_weight
S1,中心,青年,小汽车,25,1
S2,东区,中年,公交,40,1.5
S3,西区,长者,轨道,55,2
'''

def correction_csv(*rows):
    """rows:(code,zone,age_band,mode,trip_minutes,base_weight)"""
    lines=['code,zone,age_band,mode,trip_minutes,base_weight']
    for r in rows:lines.append(','.join(str(x) for x in r))
    return '\n'.join(lines)

def post_correction(client,headers,batch_id,code,csv_text,depends_on=None,base_version=None):
    body={'code':code,'csv_text':csv_text}
    if depends_on:body['depends_on']=depends_on
    if base_version:body['base_version']=base_version
    return client.post(f'/batches/{batch_id}/corrections',json=body,headers=headers)

def units(client,headers,batch_id):
    r=client.get(f'/batches/{batch_id}/units',headers=headers)
    assert r.status_code==200,r.text
    return {u['code']:u for u in r.json()}

def packages(client,headers,batch_id):
    r=client.get(f'/batches/{batch_id}/corrections',headers=headers)
    assert r.status_code==200,r.text
    return {p['code']:p for p in r.json()}
