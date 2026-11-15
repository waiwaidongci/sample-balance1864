"""三向合并引擎的纯逻辑测试：不依赖数据库与Web框架。"""
import unittest
from src.services.merge_engine import normalize,normalize_row,compute_changes,detect_conflicts,merge_rows

BASE={'S1':{'code':'S1','zone':'中心','age_band':'青年','mode':'小汽车','trip_minutes':25.0,'base_weight':1.0},
      'S2':{'code':'S2','zone':'东区','age_band':'中年','mode':'公交','trip_minutes':40.0,'base_weight':1.5}}

def row(code,**over):
    base=dict(BASE.get(code,{'code':code,'zone':'中心','age_band':'青年','mode':'公交','trip_minutes':20.0,'base_weight':1.0}))
    base.update(over);return base

class NormalizeTest(unittest.TestCase):
    def test_numeric_and_text(self):
        self.assertEqual(normalize('trip_minutes','33.5'),33.5)
        self.assertEqual(normalize('zone',' 东区 '), '东区')
    def test_rejects_out_of_range(self):
        for field,value in [('trip_minutes','501'),('trip_minutes','-1'),('base_weight','0'),('base_weight','101'),('zone','')]:
            with self.assertRaises(ValueError):normalize(field,value)
    def test_row_requires_all_fields(self):
        with self.assertRaises(ValueError):normalize_row({'code':'S1','zone':'中心'})
    def test_row_rejects_none_code_from_short_csv_row(self):
        with self.assertRaises(ValueError):normalize_row({'code':None,'zone':'中心','age_band':'青年','mode':'公交','trip_minutes':20,'base_weight':1})

class ComputeChangesTest(unittest.TestCase):
    def test_diff_against_base(self):
        changes,error=compute_changes(BASE,[row('S1',zone='西区'),row('S2')],{'S1','S2'})
        self.assertIsNone(error)
        self.assertEqual(changes,{'S1':{'zone':'西区'}})  # 与基线一致的行/字段不进入改动集
    def test_unknown_code_fails_whole_package(self):
        changes,error=compute_changes(BASE,[row('S1',zone='西区'),row('S9',zone='西区')],{'S1','S2'})
        self.assertIsNone(changes)
        self.assertIn('S9',error)

class DetectConflictsTest(unittest.TestCase):
    def test_clean_apply_when_current_equals_base(self):
        final,conflicts=detect_conflicts({'S1':{'zone':'西区'}},BASE,BASE,{})
        self.assertEqual(conflicts,[])
        self.assertEqual(final['S1']['zone'],'西区')
    def test_convergent_same_new_value_is_not_conflict(self):
        current=dict(BASE);current['S1']=row('S1',zone='西区')
        _,conflicts=detect_conflicts({'S1':{'zone':'西区'}},BASE,current,{})
        self.assertEqual(conflicts,[])
    def test_divergent_same_field_is_conflict(self):
        current=dict(BASE);current['S1']=row('S1',zone='东区')
        _,conflicts=detect_conflicts({'S1':{'zone':'西区'}},BASE,current,{})
        self.assertEqual(len(conflicts),1)
        c=conflicts[0]
        self.assertEqual((c['sample_code'],c['field'],c['base'],c['current'],c['incoming']),('S1','zone','中心','东区','西区'))
    def test_independent_fields_merge(self):
        current=dict(BASE);current['S1']=row('S1',mode='轨道')  # 另一个包改了mode
        final,conflicts=detect_conflicts({'S1':{'zone':'西区'}},BASE,current,{})
        self.assertEqual(conflicts,[])  # 本包只动zone，互不影响
        merged=merge_rows(current,final)
        self.assertEqual(merged['S1']['mode'],'轨道')  # 前包的独立改动保留
        self.assertEqual(merged['S1']['zone'],'西区')  # 本包改动并入
    def test_resolved_value_forced_and_skipped(self):
        current=dict(BASE);current['S1']=row('S1',zone='东区')
        final,conflicts=detect_conflicts({'S1':{'zone':'西区'}},BASE,current,{('S1','zone'):'南区'})
        self.assertEqual(conflicts,[])
        self.assertEqual(final['S1']['zone'],'南区')

if __name__=='__main__':unittest.main()
