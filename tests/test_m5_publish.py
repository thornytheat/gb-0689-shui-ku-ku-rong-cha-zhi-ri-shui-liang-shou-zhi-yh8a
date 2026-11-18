import pytest
from app import store
from app.pipeline import run
HEADER="id,station,time,level,inflow,outflow,flow_unit,version"
def one_side_csv(days=2,missing_day='2026-11-16',missing_hour=4):
    # 入库1.6/出库1.5，净蓄0.1 m3/s，水位每小时+0.024m（曲线首段斜率15000 m3/m），末日午夜闭合。
    lines=[HEADER];idx=0;base=100.5
    def lvl(n):return f"{base+n*0.024:.3f}"
    dates=('2026-11-16','2026-11-17')[:days]
    for di,d in enumerate(dates):
        for h in range(24):
            idx+=1
            qin="" if (d==missing_day and h==missing_hour) else "1.6"
            lines.append(f"{idx},青岚库,{d}T{h:02d}:00:00+08:00,{lvl(di*24+h)},{qin},1.5,m3/s,1")
    close_d='2026-11-18' if days==2 else '2026-11-17'
    idx+=1;lines.append(f"{idx},青岚库,{close_d}T00:00:00+08:00,{lvl(days*24)},1.6,1.5,m3/s,1")
    return "\n".join(lines)+"\n"
def test_publish_persists_ledger(client):
    text=one_side_csv()
    rep=client.post('/api/m5/publish',json={"text":text}).json
    assert rep['filled']==1  # 仅11-16单侧缺流被补齐
    ledger=client.get('/api/m5/ledger').json
    assert any(x['state']=='补齐' for x in ledger)
    assert all(x['station']=='青岚库' for x in ledger)
def test_rerun_same_day_no_duplicate_fill(client):
    text=one_side_csv()
    first=client.post('/api/m5/publish',json={"text":text}).json
    n=len(client.get('/api/m5/ledger').json)
    second=client.post('/api/m5/publish',json={"text":text}).json
    assert second['published']==0 and second['skipped_existing']==n
    ledger=client.get('/api/m5/ledger').json
    assert len(ledger)==n  # 重跑同一天不得重复补量
    fills=[x for x in ledger if x['state']=='补齐']
    assert len(fills)==1 and first['run_id']==second['run_id']
def test_publish_failure_rolls_back_and_keeps_old_ledger(client):
    text=one_side_csv()
    client.post('/api/m5/publish',json={"text":text})  # 旧版日账
    before=client.get('/api/m5/ledger').json
    failed=client.post('/api/m5/publish',json={"text":text,"simulate_publish_failure":True})
    assert failed.status_code==500 and failed.json['code']=='PUBLISH_FAILED'
    after=client.get('/api/m5/ledger').json
    assert before==after  # 整笔回滚，旧版保留
def test_resume_by_run_id_skips_confirmed(client):
    text=one_side_csv()
    rid=client.post('/api/m5/publish',json={"text":text}).json['run_id']
    rep=client.post('/api/m5/resume',json={"run_id":rid}).json
    assert rep['resumed'] is True and rep['published']==0 and rep['note']=='无待发布日期'
def test_resume_publishes_only_new_dates(client):
    first=client.post('/api/m5/publish',json={"text":one_side_csv(days=1)}).json
    before={ (x['station'],x['date']) for x in client.get('/api/m5/ledger').json}
    rep=client.post('/api/m5/resume',json={"text":one_side_csv(days=2)}).json
    assert rep['resumed'] is True and rep['skipped_existing']==len(before)
    after=client.get('/api/m5/ledger').json
    # 已确认的同站同日一条都不重复，新增日期被发布。
    assert len(after)==len(before)+rep['published'] and rep['published']>=1
    assert before <= {(x['station'],x['date']) for x in after}
def test_resume_unknown_run_404(client):
    r=client.post('/api/m5/resume',json={"run_id":"does-not-exist"})
    assert r.status_code==404 and r.json['code']=='NOT_FOUND'
def test_resumed_run_is_itself_resumable_by_new_run_id(client):
    # 先发布1天，再带新内容续跑（产生新run_id）；新run_id留存原文，可再被续跑。
    client.post('/api/m5/publish',json={"text":one_side_csv(days=1)})
    second=client.post('/api/m5/resume',json={"text":one_side_csv(days=2)}).json
    new_id=second['run_id']
    again=client.post('/api/m5/resume',json={"run_id":new_id})
    assert again.status_code==200 and again.json['published']==0
    # 新run_id确实已登记可续跑来源。
    assert client.post('/api/m5/resume',json={"run_id":"missing"}).status_code==404
def test_ledger_fill_never_masquerades_as_observed(client):
    client.post('/api/m5/publish',json={"text":one_side_csv()})
    filled=[x for x in client.get('/api/m5/ledger').json if x['state']=='补齐'][0]
    assert float(filled['in_obs_m3'])>0 and float(filled['in_fill_m3'])>0
    assert filled['fill_source'].startswith('库容变化约束')
def test_get_m5_remains_unsaved(client):
    client.get('/api/m5')
    assert client.get('/api/m5/ledger').json==[]
def test_store_resume_after_failure(isolate):
    # 规则层：发布失败后续跑，已确认日期不重复补量。
    text=one_side_csv(days=1);result=run(text.encode(),stop=5,persist=False)
    store.publish_budget(result,raw=text.encode(),params=None)
    n=len(store.ledger_rows())
    with pytest.raises(RuntimeError):
        store.publish_budget(result,failpoint=True,raw=text.encode(),params=None)
    again=store.resume_budget(result)
    assert again['published']==0 and again['skipped_existing']==n
    assert len(store.ledger_rows())==n
