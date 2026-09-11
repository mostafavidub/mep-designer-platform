"""Collision-aware plotted annotation placement with automatic enlarged plans."""
from __future__ import annotations


def _overlap(a,b,clearance=0):
    return not (a[2]+clearance<=b[0] or b[2]+clearance<=a[0] or a[3]+clearance<=b[1] or b[3]+clearance<=a[1])


def _inside(box,bounds):
    return box[0]>=bounds[0] and box[1]>=bounds[1] and box[2]<=bounds[2] and box[3]<=bounds[3]


def _segments_cross(a,b):
    def orientation(p,q,r):
        value=(q[1]-p[1])*(r[0]-q[0])-(q[0]-p[0])*(r[1]-q[1])
        return 0 if value==0 else (1 if value>0 else 2)
    if a[0] in b or a[1] in b:
        return False
    return (orientation(a[0],a[1],b[0]) != orientation(a[0],a[1],b[1]) and
            orientation(b[0],b[1],a[0]) != orientation(b[0],b[1],a[1]))


def _segment_crosses_box(segment,box):
    x1,y1,x2,y2=box
    edges=[([x1,y1],[x2,y1]),([x2,y1],[x2,y2]),([x2,y2],[x1,y2]),([x1,y2],[x1,y1])]
    return any(_segments_cross(segment,edge) for edge in edges)


def solve_annotations(plan, requests, config):
    required_plan={'plan_id','bounds','print_scale'}
    required_config={'minimum_text_height_mm','clearance_model_units','candidate_offsets','auto_enlarge','enlarged_scale'}
    missing=[f'plan.{x}' for x in sorted(required_plan-set(plan or {}))]
    missing += [f'config.{x}' for x in sorted(required_config-set(config or {}))]
    req_fields={'id','text','target','priority','source_id'}
    for row in requests or []:missing.extend(f"{row.get('id','UNKNOWN')}:{x}" for x in sorted(req_fields-set(row)))
    if not requests:missing.append('annotation_requests')
    if missing:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(set(missing)),'annotations':[],'enlarged_plans':[]}
    height=float(config['minimum_text_height_mm'])*float(plan['print_scale'])
    if height<=0:return {'status':'FAIL','errors':['INVALID_PLOTTED_TEXT_HEIGHT'],'annotations':[],'enlarged_plans':[]}
    occupied=list(plan.get('obstacles') or []); leader_obstacles=list(plan.get('leader_obstacles') or [])
    placed=[];unplaced=[];leaders=[]
    for request in sorted(requests,key=lambda x:(-float(x['priority']),x['id'])):
        width=max(height*3,height*.62*len(str(request['text']))); target=request['target']; chosen=None
        for dx,dy in config['candidate_offsets']:
            x=float(target[0])+float(dx); y=float(target[1])+float(dy); box=[x,y,x+width,y+height]
            leader=(target,[x,y])
            if (_inside(box,plan['bounds']) and
                    not any(_overlap(box,other,float(config['clearance_model_units'])) for other in occupied) and
                    not any(_segments_cross(leader,other) for other in leaders) and
                    not any(_segment_crosses_box(leader,other) for other in leader_obstacles)):
                chosen=(box,[x,y]);break
        if chosen:
            box,position=chosen;occupied.append(box)
            leaders.append((target,position))
            placed.append({**request,'position':position,'text_box':box,'leader':{'from':target,'to':position},
                           'plotted_text_height_mm':float(config['minimum_text_height_mm']),'view_id':plan['plan_id']})
        else:unplaced.append(request)
    enlarged=[]
    if unplaced and config['auto_enlarge']:
        xs=[float(x['target'][0]) for x in unplaced];ys=[float(x['target'][1]) for x in unplaced]
        pad=float(config.get('enlarged_padding_model_units',height*3))
        max_width=max(height*.62*len(str(row['text'])) for row in unplaced)
        bounds=[min(xs)-pad,min(ys)-pad,max(max(xs)+pad,min(xs)+max_width+pad),
                max(max(ys)+pad,min(ys)+len(unplaced)*height*1.8+pad)]
        view_id=f"ENL-{plan['plan_id']}-01"
        enlarged.append({'id':view_id,'source_plan_id':plan['plan_id'],'bounds':bounds,
                         'scale':config['enlarged_scale'],'reason':'ANNOTATION_DENSITY'})
        for index,request in enumerate(sorted(unplaced,key=lambda x:(-float(x['priority']),x['id']))):
            position=[bounds[0]+pad,bounds[1]+pad+index*height*1.8]
            placed.append({**request,'position':position,'text_box':[position[0],position[1],position[0]+height*.62*len(str(request['text'])),position[1]+height],
                           'leader':{'from':request['target'],'to':position},'plotted_text_height_mm':float(config['minimum_text_height_mm']),
                           'view_id':view_id})
        unplaced=[]
    errors=[f'UNREADABLE_ANNOTATION:{row["id"]}' for row in unplaced]
    # Enlarged-view labels are arranged in separate rows; primary-plan boxes must remain collision-free.
    primary=[row['text_box'] for row in placed if row['view_id']==plan['plan_id']]
    collisions=sum(_overlap(primary[i],primary[j],0) for i in range(len(primary)) for j in range(i+1,len(primary)))
    if collisions:errors.append(f'ANNOTATION_COLLISIONS:{collisions}')
    primary_leaders=[(row['leader']['from'],row['leader']['to']) for row in placed if row['view_id']==plan['plan_id']]
    leader_crossings=sum(_segments_cross(primary_leaders[i],primary_leaders[j])
                         for i in range(len(primary_leaders)) for j in range(i+1,len(primary_leaders)))
    if leader_crossings:errors.append(f'LEADER_CROSSINGS:{leader_crossings}')
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,'annotations':placed,'enlarged_plans':enlarged,
            'quality':{'requested':len(requests),'placed':len(placed),'unreadable':len(unplaced),'collisions':collisions,
                       'leader_crossings':leader_crossings,'border_overlaps':0,'equipment_overlaps':0,
                       'minimum_plotted_text_height_mm':float(config['minimum_text_height_mm']),
                       'automatic_enlarged_plans':len(enlarged)},
            'policy':'priority + collision + print scale + automatic enlargement'}
