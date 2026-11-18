from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from collections import defaultdict
# Public pure interpolation is deliberately passed in by the service.
DAY=D(24)
def day_budget(flows,curve,interpolate):
    zone=timezone(timedelta(hours=8))
    buckets=defaultdict(lambda:{'in_obs_m3':D(0),'out_obs_m3':D(0),'in_fill_m3':D(0),'out_fill_m3':D(0),
                                'storage_change':D(0),'storage_hours':D(0),
                                'in_obs_hours':D(0),'out_obs_hours':D(0)})
    for part in flows:
        left,right=part['left'],part['right'];start,end=part['start'],part['end']
        duration=D(str((end-start).total_seconds()));cursor=start
        def at(t,key):return left[key]+(right[key]-left[key])*D(str((t-start).total_seconds()))/duration
        while cursor<end:
            local=cursor.astimezone(zone);midnight=datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),zone)
            stop=min(end,midnight);seconds=D(str((stop-cursor).total_seconds()));hours=seconds/3600
            b=buckets[(part['station'],local.date().isoformat())]
            if left['inflow'] is not None and right['inflow'] is not None:
                b['in_obs_m3']+=(at(cursor,'inflow')+at(stop,'inflow'))/2*seconds;b['in_obs_hours']+=hours
            if left['outflow'] is not None and right['outflow'] is not None:
                b['out_obs_m3']+=(at(cursor,'outflow')+at(stop,'outflow'))/2*seconds;b['out_obs_hours']+=hours
            # 水位始终观测，库容变化是补齐的约束量。
            b['storage_change']+=interpolate(at(stop,'level'),curve)-interpolate(at(cursor,'level'),curve)
            b['storage_hours']+=hours;cursor=stop
    result=[]
    for (station,day),v in sorted(buckets.items()):
        full=v['storage_hours']==DAY
        in_full=v['in_obs_hours']==DAY;out_full=v['out_obs_hours']==DAY
        fill_source='无';state='完整'
        if full and not in_full and out_full:
            # 水量平衡：库变=总入库-总出库；总入库=库变+观测出库，补量=总入库-已观测入库。
            v['in_fill_m3']=v['storage_change']+v['out_obs_m3']-v['in_obs_m3'];fill_source='库容变化约束·补入库';state='补齐'
        elif full and in_full and not out_full:
            # 总出库=观测入库-库变，补量=总出库-已观测出库。
            v['out_fill_m3']=v['in_obs_m3']-v['storage_change']-v['out_obs_m3'];fill_source='库容变化约束·补出库';state='补齐'
        elif not full or not (in_full and out_full):
            # 库变本身不完整，或两侧同时缺观测，约束不成立，保留缺测不推算。
            state='缺测'
        if v['in_fill_m3']<0 or v['out_fill_m3']<0:
            # 推算出负水量说明约束被违背（未含蒸发降雨/渗漏/外部调度），不发布推算值。
            v['in_fill_m3']=D(0);v['out_fill_m3']=D(0);fill_source='无';state='缺测'
        in_m3=v['in_obs_m3']+v['in_fill_m3'];out_m3=v['out_obs_m3']+v['out_fill_m3']
        result.append({'station':station,'date':day,
            'in_obs_m3':v['in_obs_m3'],'out_obs_m3':v['out_obs_m3'],
            'in_fill_m3':v['in_fill_m3'],'out_fill_m3':v['out_fill_m3'],
            'in_m3':in_m3,'out_m3':out_m3,
            'storage_change':v['storage_change'],
            'in_obs_hours':v['in_obs_hours'],'out_obs_hours':v['out_obs_hours'],
            'storage_hours':v['storage_hours'],
            'coverage_hours':v['storage_hours'],
            'residual':v['storage_change']-in_m3+out_m3,'fill_source':fill_source,'state':state})
    return result
