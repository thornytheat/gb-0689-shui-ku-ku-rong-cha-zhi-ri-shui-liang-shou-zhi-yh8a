from flask import Blueprint,request,jsonify
from app.pipeline import run
from app.errors import DomainError
from app import store
bp=Blueprint("m5",__name__)
def _payload():
    payload=request.get_json(silent=True) if request.method=="POST" else {}
    if not isinstance(payload,dict): raise DomainError("BODY","请求必须是对象")
    raw=payload.get("text")
    if raw is not None and not isinstance(raw,str): raise DomainError("TEXT","数据必须为文本")
    return raw,payload.get("params"),payload
@bp.route("/api/m5",methods=["GET","POST"])
def endpoint():
    raw,_,_=_payload()
    return jsonify(run(raw,stop=5,persist=False))
@bp.route("/api/m5/publish",methods=["POST"])
def publish():
    raw,params,payload=_payload()
    source=(raw.encode("utf-8") if isinstance(raw,str) else None)
    result=run(raw,params,stop=5,persist=False)
    try:
        # 仅测试用故障注入：验证发布失败时整笔回滚、旧版日账保留。
        report=store.publish_budget(result,failpoint=bool(payload.get("simulate_publish_failure")),raw=source,params=params)
    except DomainError:raise
    except Exception:
        # store层已ROLLBACK，旧版日账保留；返回结构化错误而非HTML 500。
        raise DomainError("PUBLISH_FAILED","日账发布失败，已保留旧版日账",500)
    report["budgets"]=result["budgets"]
    return jsonify(report)
@bp.route("/api/m5/resume",methods=["POST"])
def resume():
    raw,params,payload=_payload()
    run_id=payload.get("run_id")
    if raw is None:
        if not isinstance(run_id,str): raise DomainError("BODY","续跑需要run_id或文本数据")
        # 从已确认日期续跑：取回发布时留存的原文重算，已确认同站同日自动跳过。
        raw,params=store.ledger_source(run_id)
    source=(raw.encode("utf-8") if isinstance(raw,str) else raw)
    result=run(raw,params,stop=5,persist=False)
    report=store.resume_budget(result,raw=source,params=params)
    report["budgets"]=result["budgets"]
    return jsonify(report)
@bp.route("/api/m5/ledger",methods=["GET"])
def ledger():
    return jsonify(store.ledger_rows(request.args.get("run")))
