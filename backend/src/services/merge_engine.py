"""更正包三向合并的纯函数核心：不依赖数据库，便于独立测试与复算。

合并口径：
- 更正包按基线版本(base_version)快照逐字段 diff 得到改动集；
- 应用时与当前底册三向比较：当前值==基线值 → 干净应用；当前值==新值 → 幂等收敛；
- 其余情况(同字段出现不同新值) → 冲突，由人工解决后强制写入解决值。
"""
TEXT_FIELDS=('zone','age_band','mode')
NUM_FIELDS=('trip_minutes','base_weight')
FIELDS=TEXT_FIELDS+NUM_FIELDS
LIMITS={'zone':(1,30),'age_band':(1,30),'mode':(1,30)}

def normalize(field,value):
    """把CSV/JSON中的原始值规范为可比较的类型值；非法值抛ValueError。"""
    if field in NUM_FIELDS:
        try:number=float(value)
        except (TypeError,ValueError):raise ValueError(f'{field} 需要数值')
        if number!=number or number in (float('inf'),float('-inf')):raise ValueError(f'{field} 需要有限数值')
        if field=='trip_minutes' and not 0<=number<=500:raise ValueError('trip_minutes 需在 0–500 之间')
        if field=='base_weight' and not 0<number<=100:raise ValueError('base_weight 需在 (0,100] 之间')
        return number
    text=str(value).strip()
    lo,hi=LIMITS[field]
    if not lo<=len(text)<=hi:raise ValueError(f'{field} 需 {lo}–{hi} 个字符')
    return text

def normalize_row(row):
    """校验并规范一整行{code,zone,age_band,mode,trip_minutes,base_weight}。"""
    code=str(row.get('code') or '').strip()
    if not code or len(code)>60:raise ValueError('code 需 1–60 个字符')
    out={'code':code}
    for field in FIELDS:
        if field not in row or row[field] is None or str(row[field]).strip()=='':raise ValueError(f'样本 {code} 缺少字段 {field}')
        out[field]=normalize(field,row[field])
    return out

def compute_changes(base_map,payload_rows,current_codes):
    """按基线快照diff出改动集。返回(changes,error)；error为None表示全部合法。

    base_map:{code:行};payload_rows:规范后的整行列表;current_codes:当前底册编号集合。
    changes:{code:{field:新值}}，与基线一致的字段不进入改动集。
    """
    changes={}
    for row in payload_rows:
        code=row['code']
        if code not in base_map:return None,f'样本 {code} 不在基线版本中，更正包未写入'
        if code not in current_codes:return None,f'样本 {code} 不在当前底册中，更正包未写入'
        delta={f:row[f] for f in FIELDS if row[f]!=base_map[code][f]}
        if delta:changes[code]=delta
    return changes,None

def detect_conflicts(changes,base_map,current_map,resolved):
    """三向合并检查。resolved:{(code,field):解决值}为人工强制值，跳过冲突检测。

    返回(final_changes,conflicts)。conflicts元素:{sample_code,field,base,current,incoming}。
    """
    final={code:dict(fields) for code,fields in changes.items()}
    for (code,field),value in resolved.items():final.setdefault(code,{})[field]=value
    conflicts=[]
    for code in sorted(final):
        for field in sorted(final[code]):
            if (code,field) in resolved:continue
            new=final[code][field];current=current_map[code][field];base=base_map[code][field]
            if current==base or current==new:continue
            conflicts.append({'sample_code':code,'field':field,'base':base,'current':current,'incoming':new})
    return final,conflicts

def merge_rows(current_map,changes):
    """把改动集应用到{code:行}的副本上，返回新的register映射(纯函数)。"""
    merged={code:dict(row) for code,row in current_map.items()}
    for code,fields in changes.items():
        for field,value in fields.items():merged[code][field]=value
    return merged
