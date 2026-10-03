import unittest
from shapely.geometry import LineString
from cad_engine.architectural_source_roles import annotate_source_roles
from cad_engine.pre_topology_object_classifier import classify_source_record


def extract(records, texts=()):
    lines=[];metas=[]
    for record in records:
        pts=record.get('points') or [record['start'],record['end']]
        for a,b in zip(pts,pts[1:]+([pts[0]] if record.get('closed') else [])):
            lines.append(LineString([a,b]));metas.append({k:v for k,v in record.items() if k not in ('start','end','points')})
    return {'primitives':records,'texts':list(texts),'boundary_lines':lines,'boundary_meta':metas}


def line(handle,a,b,layer='0'):
    return {'handle':handle,'entity_type':'LINE','layer':layer,'start':a,'end':b}


class SourceRolesTests(unittest.TestCase):
    def host(self, layer='0', mate=False):
        corners=[(0,0),(2,0),(2,1),(0,1),(0,0)]
        records=[line(str(i),a,b) for i,(a,b) in enumerate(zip(corners,corners[1:]))]
        records.append(line('chord',(0,0),(2,1),layer))
        if mate: records.append(line('mate',(0,.12),(2,1.12)))
        return extract(records,[{'text':'closet','point':(1,.5)}])

    def test_symbol_chord_excluded_but_perimeter_retained(self):
        e=self.host();annotate_source_roles(e,[],1,.002)
        self.assertEqual(classify_source_record(e['primitives'][-1])['topology_role'],'NON_TOPOLOGICAL')
        self.assertFalse(any(r.get('pre_topology_object_class') for r in e['primitives'][:-1]))

    def test_true_diagonal_with_wall_context_or_mate_retained(self):
        for e in (self.host('wall'),self.host(mate=True)):
            annotate_source_roles(e,[],1,.002)
            self.assertFalse(e['primitives'][4].get('pre_topology_object_class'))

    def test_unlabelled_diagonal_and_short_wall_retained(self):
        e=self.host();e['texts']=[];e['primitives'].append(line('short',(4,0),(4,.03),'wall'))
        annotate_source_roles(e,[],1,.002)
        self.assertFalse(any(r.get('pre_topology_object_class') for r in e['primitives']))

    def test_repeated_chamfered_object_motif(self):
        points=[(.38,.15),(.04,.15),(0,.11),(0,.06),(.03,.03),(.31,.03),(.33,.05),(.33,.07),(.35,.09),(.33,.09)]
        records=[{'handle':str(i),'entity_type':'LWPOLYLINE','layer':'0','points':[(x+i,y) for x,y in points]} for i in range(3)]
        e=extract(records);annotate_source_roles(e,[],1,.002)
        self.assertTrue(all(r.get('pre_topology_object_class')=='GENERIC_NON_ENCLOSURE_OBJECT' for r in records))

    def test_world_occurrence_does_not_leak_by_reused_handle(self):
        e=self.host();e['primitives'].append(line('chord',(10,0),(12,1)));e=extract(e['primitives'],e['texts'])
        annotate_source_roles(e,[],1,.002)
        self.assertTrue(e['boundary_meta'][4].get('pre_topology_object_class'))
        self.assertFalse(e['boundary_meta'][5].get('pre_topology_object_class'))

    def test_repeated_column_outline_before_void(self):
        records=[{'handle':str(i),'entity_type':'LWPOLYLINE','closed':True,'points':[(i,0),(i+.4,0),(i+.4,.4),(i,.4)]} for i in range(3)]
        e=extract(records);annotate_source_roles(e,[],1,.002)
        self.assertTrue(all(classify_source_record(r)['object_class']=='COLUMN' for r in records))

    def test_detail_island_excluded_without_removing_separate_plan(self):
        records=[line('plan-a',(0,0),(3,0),'wall'),line('plan-b',(3,0),(3,4),'wall'),line('plan-c',(3,4),(0,4),'wall'),line('plan-d',(0,4),(0,0),'wall')]
        records += [line('detail-'+str(i),(8,i*.5),(9,i*.5),'construction') for i in range(4)]
        records += [line('detail-edge',(8,0),(8,1.5),'construction')]
        texts=[{'text':str(i+1)+' Cm','layer':'construction','point':(9.2,i*.5)} for i in range(3)]
        e=extract(records,texts);annotate_source_roles(e,[{'bounds':[-1,-1,12,8]}],1,.002)
        self.assertFalse(any(r.get('pre_topology_object_class') for r in records[:4]))
        self.assertTrue(all(r.get('pre_topology_role')=='REFERENCE_ONLY' for r in records[4:]))

    def test_dimension_callouts_alone_do_not_exclude_plan(self):
        e=self.host();e['texts']=[{'text':str(i+1)+' Cm','layer':'dimension','point':(1,i*.2)} for i in range(3)]
        annotate_source_roles(e,[{'bounds':[-1,-1,12,8]}],1,.002)
        self.assertFalse(any(r.get('pre_topology_object_class') for r in e['primitives']))

    def test_small_closed_polygons_are_not_furniture(self):
        records=[{'handle':str(i),'entity_type':'LWPOLYLINE','closed':True,'points':[(i*3,0),(i*3+2,0),(i*3+2,1),(i*3,1)]} for i in range(3)]
        e=extract(records);annotate_source_roles(e,[],1,.002)
        self.assertFalse(any(r.get('pre_topology_object_class') for r in records))

    def test_symbol_translation_rotation_and_unit_scale(self):
        e=self.host()
        for r in e['primitives']:
            for key in ('start','end'):
                x,y=r[key];r[key]=(10000-y*1000,20000+x*1000)
        e['texts'][0]['point']=(9500,21000)
        e=extract(e['primitives'],e['texts']);annotate_source_roles(e,[],.001,2)
        self.assertEqual(e['primitives'][-1]['pre_topology_object_class'],'GENERIC_NON_ENCLOSURE_OBJECT')

    def test_repeated_explicit_duct_footprints_remain_void_compatible(self):
        records=[{'handle':str(i),'entity_type':'LWPOLYLINE','layer':'DUCT','closed':True,'points':[(i,0),(i+.4,0),(i+.4,.4),(i,.4)]} for i in range(3)]
        e=extract(records);annotate_source_roles(e,[],1,.002)
        self.assertFalse(any(r.get('pre_topology_object_class') for r in records))
        self.assertFalse(any(r.get('pre_topology_object_class') for r in e['boundary_meta']))

    def test_unrelated_parallel_extension_does_not_inhibit_symbol_role(self):
        e=self.host();e['primitives'].append(line('unrelated',(2.1,1.05),(4.1,2.05)))
        e=extract(e['primitives'],e['texts']);annotate_source_roles(e,[],1,.002)
        self.assertEqual(e['primitives'][4]['pre_topology_object_class'],'GENERIC_NON_ENCLOSURE_OBJECT')
        self.assertFalse(e['primitives'][5].get('pre_topology_object_class'))
