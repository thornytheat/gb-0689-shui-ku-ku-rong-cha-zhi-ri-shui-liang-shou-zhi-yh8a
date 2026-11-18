import os,sqlite3,json
from pathlib import Path
from app.errors import DomainError
def connection():
    path=Path(os.environ.get("DATA_DIR","data"));path.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path/"runs.sqlite",timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,review TEXT NOT NULL DEFAULT '待复核')")
    # 已发布日账：同站同日唯一，重跑靠INSERT OR IGNORE幂等，绝不重复补量。
    db.execute("""CREATE TABLE IF NOT EXISTS ledger (
        station TEXT NOT NULL,date TEXT NOT NULL,run_id TEXT NOT NULL,
        state TEXT NOT NULL,fill_source TEXT NOT NULL,
        in_obs_m3 TEXT NOT NULL,out_obs_m3 TEXT NOT NULL,
        in_fill_m3 TEXT NOT NULL,out_fill_m3 TEXT NOT NULL,
        storage_change TEXT NOT NULL,residual TEXT NOT NULL,payload TEXT NOT NULL,
        confirmed INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(station,date))""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_ledger_run ON ledger(run_id)")
    # 已发布批次的输入与参数，供补齐失败后按run_id从已确认日期续跑。
    db.execute("""CREATE TABLE IF NOT EXISTS ledger_runs (
        run_id TEXT PRIMARY KEY,raw BLOB NOT NULL,params TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    return db
def save(result):
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES(?,?)",(result["manifest"]["run_id"],json.dumps(result,ensure_ascii=False)))
    return fetch(result["manifest"]["run_id"])
def fetch(run_id):
    with connection() as db: row=db.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
    if row is None: raise DomainError("NOT_FOUND","批次不存在",404)
    result=json.loads(row["payload"]);result["version"]=row["version"];result["review"]=row["review"]
    return result
def history():
    with connection() as db: rows=db.execute("SELECT id,version,review FROM runs ORDER BY rowid DESC LIMIT 100").fetchall()
    return [dict(row) for row in rows]
def review(run_id,version,decision):
    if decision not in ("通过","退回"): raise DomainError("REVIEW","请选择通过或退回")
    if not isinstance(version,int): raise DomainError("STALE","版本必须为整数")
    with connection() as db:
        cur=db.execute("UPDATE runs SET review=?,version=version+1 WHERE id=? AND version=?",(decision,run_id,version))
        if cur.rowcount!=1: raise DomainError("STALE","复核版本已更新",409)
    return fetch(run_id)
def confirmed_dates(run_id=None):
    sql="SELECT station,date FROM ledger WHERE confirmed=1";args=()
    if run_id is not None:sql+=" AND run_id=?";args=(run_id,)
    with connection() as db:return {(r["station"],r["date"]) for r in db.execute(sql+" ORDER BY date,station",args)}
def publish_budget(result,failpoint=False,raw=None,params=None):
    """原子发布日账。任一行写入失败则整笔回滚，旧版日账保留；同站同日已存在则跳过不重复补量。"""
    run_id=result["manifest"]["run_id"];rows=result.get("budgets",[])
    db=connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        inserted=0;skipped=0;filled=0
        for row in rows:
            cur=db.execute("""INSERT OR IGNORE INTO ledger
                (station,date,run_id,state,fill_source,in_obs_m3,out_obs_m3,in_fill_m3,out_fill_m3,
                 storage_change,residual,payload,confirmed)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                (row["station"],row["date"],run_id,row["state"],row["fill_source"],
                 str(row["in_obs_m3"]),str(row["out_obs_m3"]),str(row["in_fill_m3"]),str(row["out_fill_m3"]),
                 str(row["storage_change"]),str(row["residual"]),json.dumps(row,ensure_ascii=False)))
            if cur.rowcount==1:inserted+=1
            else:skipped+=1
            if row["state"]=="补齐":filled+=1
        if raw is not None:
            db.execute("INSERT OR IGNORE INTO ledger_runs(run_id,raw,params) VALUES(?,?,?)",
                       (run_id,raw,json.dumps(params or {},ensure_ascii=False)))
        if failpoint:raise RuntimeError("模拟发布失败，验证整笔回滚")
        db.commit()
    except Exception:
        db.rollback();db.close();raise
    db.close()
    return {"run_id":run_id,"published":inserted,"skipped_existing":skipped,
            "filled":filled,"confirmed":sorted(confirmed_dates(run_id))}
def ledger_source(run_id):
    with connection() as db:row=db.execute("SELECT raw,params FROM ledger_runs WHERE run_id=?",(run_id,)).fetchone()
    if row is None:raise DomainError("NOT_FOUND","没有可续跑的已发布批次",404)
    return row["raw"],json.loads(row["params"])
def resume_budget(result,raw=None,params=None):
    """从已确认日期续跑：跳过此前已发布的同站同日，仅发布新增日期。"""
    done=confirmed_dates()
    pending=[r for r in result.get("budgets",[]) if (r["station"],r["date"]) not in done]
    if not pending:
        return {"run_id":result["manifest"]["run_id"],"published":0,"skipped_existing":len(result.get("budgets",[])),
                "filled":0,"confirmed":sorted(done),"resumed":True,"note":"无待发布日期"}
    subset={**result,"budgets":pending}
    report=publish_budget(subset,raw=raw,params=params)
    report["resumed"]=True;report["skipped_existing"]=len(result["budgets"])-len(pending)
    return report
def ledger_rows(run_id=None):
    sql="SELECT * FROM ledger";args=()
    if run_id is not None:sql+=" WHERE run_id=?";args=(run_id,)
    with connection() as db:return [dict(r) for r in db.execute(sql+" ORDER BY date,station",args)]
