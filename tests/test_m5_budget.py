import pytest
from decimal import Decimal as D
from app.errors import DomainError
from app.pipeline import run
from app.normalize import instant
from app.modules.m5_budget.rules import day_budget
from app.modules.m4_storage.service import level_to_volume
from app.modules.m3_integrate.rules import integrate
C=[(D(100),D(0)),(D(102),D(30000))]
def p(time,level,qin=D(1),qout=D(0)):return dict(station='S',time=instant(time),inflow=qin,outflow=qout,level=D(level))

def test_midnight_split():
    # TRAP-23
    x=integrate([p('2026-12-31T23:00:00+08:00','100'),p('2027-01-01T01:00:00+08:00','102')],D(2))[0];days=day_budget(x,C,level_to_volume);assert len(days)==2 and [r['in_m3'] for r in days]==[3600,3600]

def test_storage_conservation():
    x=integrate([p('2026-11-16T23:00:00+08:00','100'),p('2026-11-17T01:00:00+08:00','102')],D(2))[0];assert sum(r['storage_change'] for r in day_budget(x,C,level_to_volume))==30000

def test_partial_day_flagged():
    x=integrate([p('2026-11-16T00:00:00Z','101'),p('2026-11-16T01:00:00Z','101')],D(2))[0];assert day_budget(x,C,level_to_volume)[0]['state']=='缺测'

def test_empty():
    assert day_budget([],C,level_to_volume)==[]

def test_real_day_count(raw):
    assert len(run(raw,stop=5,persist=False)['budgets'])>=2

def test_real_missing_day(raw):
    assert any(x['state']=='缺测' for x in run(raw,stop=5,persist=False)['budgets'])

def test_real_daily_integral(raw):
    x=run(raw,stop=5,persist=False);assert abs(sum(D(y['in_obs_m3']) for y in x['budgets'])-sum(D(y['in_m3']) for y in x['flows']))<D('.000000001')

# ---- 单侧缺流：库容变化约束补齐 ----
def test_inflow_missing_full_day_is_filled():
    # 全天入库缺测、出库观测完整：入库推算值=库变+观测出库，残差归零，观测列保持为0。
    rows=[p('2026-11-16T00:00:00+08:00','101',None,D(1)),
          p('2026-11-16T12:00:00+08:00','101.5',None,D(1)),
          p('2026-11-17T00:00:00+08:00','102',None,D(1))]
    b=day_budget(integrate(rows,D(24))[0],C,level_to_volume)[0]
    assert b['state']=='补齐' and b['fill_source']=='库容变化约束·补入库'
    assert b['in_obs_m3']==0 and b['in_fill_m3']==b['storage_change']+b['out_obs_m3']
    assert b['residual']==0 and b['in_m3']==b['in_fill_m3']

def test_outflow_missing_full_day_is_filled():
    rows=[p('2026-11-16T00:00:00+08:00','101',D(2),None),
          p('2026-11-17T00:00:00+08:00','102',D(2),None)]
    b=day_budget(integrate(rows,D(24))[0],C,level_to_volume)[0]
    assert b['state']=='补齐' and b['fill_source']=='库容变化约束·补出库'
    assert b['out_obs_m3']==0 and b['out_fill_m3']==b['in_obs_m3']-b['storage_change']

def test_partial_day_never_filled():
    # 覆盖不足24h，库变约束不成立，绝不推算。
    rows=[p('2026-11-16T00:00:00Z','101',None,D(1)),p('2026-11-16T02:00:00Z','101.4',None,D(1))]
    b=day_budget(integrate(rows,D(2))[0],C,level_to_volume)[0]
    assert b['state']=='缺测' and b['in_fill_m3']==0 and b['fill_source']=='无'

def test_both_sides_missing_not_fillable():
    rows=[p('2026-11-16T00:00:00+08:00','101',None,None),
          p('2026-11-17T00:00:00+08:00','102',None,None)]
    # M2会隔离双侧缺失，这里直接验证规则层不推算。
    b=day_budget(integrate(rows,D(24))[0],C,level_to_volume)[0]
    assert b['state']=='缺测' and b['in_fill_m3']==0 and b['out_fill_m3']==0

def test_negative_inferred_rejected():
    # 推算出库为负（入库小于库变增量），约束被违背，保留缺测不发布推算值。
    rows=[p('2026-11-16T00:00:00+08:00','100',D('0.1'),None),
          p('2026-11-17T00:00:00+08:00','102',D('0.1'),None)]
    b=day_budget(integrate(rows,D(24))[0],C,level_to_volume)[0]
    assert b['state']=='缺测' and b['out_fill_m3']==0

def test_observed_and_fill_kept_separate():
    # 仅两个相邻时段缺入库：观测水量与推算补量分列，合计=观测+推算，补量恰为缺失时段的入库量。
    rows=[]
    for h in range(25):
        day='2026-11-17' if h==24 else '2026-11-16';hh=0 if h==24 else h
        rows.append(dict(station='S',time=instant(f'{day}T{hh:02d}:00:00+08:00'),
                         inflow=None if h==3 else D('1.6'),outflow=D('1.5'),level=D(f'{100.5+h*0.024:.3f}')))
    b=day_budget(integrate(rows,D(2))[0],C,level_to_volume)[0]
    assert b['state']=='补齐' and b['in_obs_m3']>0 and b['in_fill_m3']>0
    assert b['in_m3']==b['in_obs_m3']+b['in_fill_m3']
    assert b['in_fill_m3']==D('11520')  # 两个缺失小时 × 1.6 m³/s × 3600s
    assert b['residual']==0
    assert b['out_fill_m3']==0 and b['out_m3']==b['out_obs_m3']
