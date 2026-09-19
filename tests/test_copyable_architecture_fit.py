import ezdxf

from cad_engine.mechanical_design_core import (
    _copyable_geometry_bounds,
    _fit_transform,
    _plan_fit_bounds,
    _plan_ownership_bounds,
)


def test_render_fit_uses_retained_architecture_not_removed_sheet_furniture():
    doc=ezdxf.new("R2010");msp=doc.modelspace()
    # The print frame is detected during segmentation but is removed before
    # composition.  The retained building is deliberately offset and smaller.
    msp.add_lwpolyline([(0,0),(30,0),(30,20),(0,20)],close=True,dxfattribs={"layer":"frame"})
    building=[]
    for index in range(10):
        building.append(msp.add_line((8+index*.7,6),(8+index*.7,14),dxfattribs={"layer":"wall"}))
    building.extend([
        msp.add_line((8,6),(14.3,6),dxfattribs={"layer":"wall"}),
        msp.add_line((8,14),(14.3,14),dxfattribs={"layer":"wall"}),
    ])
    bounds=_copyable_geometry_bounds(building,(0,0,30,20))
    assert bounds[0]>=8 and bounds[2]<=14.3
    transform,_,_=_fit_transform(bounds,(1,1,19,25))
    mapped=[transform.transform((x,y,0)) for x,y in ((bounds[0],bounds[1]),(bounds[2],bounds[3]))]
    assert min(p.x for p in mapped)>=1
    assert max(p.x for p in mapped)<=19
    assert min(p.y for p in mapped)>=1
    assert max(p.y for p in mapped)<=25


def test_copyable_fit_preserves_one_isolated_remote_geometry_outlier():
    doc=ezdxf.new("R2010");msp=doc.modelspace()
    entities=[msp.add_line((x,0),(x,10),dxfattribs={"layer":"wall"}) for x in range(10)]
    entities.append(msp.add_circle((1000,1000),1,dxfattribs={"layer":"wall"}))
    bounds=_copyable_geometry_bounds(entities,(0,0,1001,1001))
    assert bounds[2]>=1001
    assert bounds[3]>=1001


def test_copyable_fit_keeps_retained_architectural_text_inside_viewport():
    doc=ezdxf.new("R2010");msp=doc.modelspace()
    wall=msp.add_line((8,6),(14,14),dxfattribs={"layer":"wall"})
    note=msp.add_text("ARCH NOTE",dxfattribs={"layer":"construction","height":1})
    note.dxf.insert=(4,2)
    bounds=_copyable_geometry_bounds([wall,note],(0,0,30,20))
    assert bounds[0]<=4
    assert bounds[1]<=2


def test_render_fit_never_mutates_repeated_sheet_ownership():
    plan={
        "bounds":[0,0,30,20],
        "content_bounds":[5,4,20,16],
        # A retained annotation may legitimately expand the transform envelope.
        "render_fit_bounds":[2,2,24,18],
    }
    assert _plan_fit_bounds(plan)==[2,2,24,18]
    assert _plan_ownership_bounds(plan)==[5,4,20,16]
    # Recomputing fit for another system sheet cannot expand entity ownership.
    plan["render_fit_bounds"]=[1,1,26,19]
    assert _plan_ownership_bounds(plan)==[5,4,20,16]
