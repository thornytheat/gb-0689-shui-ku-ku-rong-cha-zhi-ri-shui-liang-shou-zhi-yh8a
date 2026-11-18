from collections import defaultdict
from decimal import Decimal as D
def integrate(rows,max_gap):
    stations=defaultdict(list)
    for row in rows:stations[row['station']].append(row)
    parts=[];gaps=[]
    for station,items in sorted(stations.items()):
        items=sorted(items,key=lambda r:r['time'])
        for a,b in zip(items,items[1:]):
            seconds=D(str((b['time']-a['time']).total_seconds()))
            if seconds>max_gap*3600:
                gaps.append({'station':station,'start':a['time'],'end':b['time'],'hours':seconds/3600,'code':'GAP','state':'缺测'});continue
            part={'station':station,'start':a['time'],'end':b['time'],'left':a,'right':b,
                  'in_m3':D(0),'out_m3':D(0),'in_obs_hours':D(0),'out_obs_hours':D(0)}
            # 缺测一侧该段不积分，观测覆盖时长单列；不以零或插值冒充观测。
            if a['inflow'] is not None and b['inflow'] is not None:
                part['in_m3']=(a['inflow']+b['inflow'])/2*seconds;part['in_obs_hours']=seconds/3600
            if a['outflow'] is not None and b['outflow'] is not None:
                part['out_m3']=(a['outflow']+b['outflow'])/2*seconds;part['out_obs_hours']=seconds/3600
            parts.append(part)
    return parts,gaps
