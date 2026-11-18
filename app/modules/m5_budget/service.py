from .rules import day_budget
from app.modules.m4_storage.service import level_to_volume
def execute(ctx):
    rows=day_budget(ctx['flows'],ctx['curve'],level_to_volume);ctx['budgets']=rows
    ctx['stages'].append({'title':'日水量收支','rows':rows,'metrics':{'日账':len(rows),
        '完整日':sum(x['state']=='完整' for x in rows),'补齐日':sum(x['state']=='补齐' for x in rows),
        '缺测日':sum(x['state']=='缺测' for x in rows),
        '推算补量 m³':str(sum((x['in_fill_m3']+x['out_fill_m3'] for x in rows),0)),
        '收支差 m³':str(sum((x['residual'] for x in rows),0))}});return ctx
