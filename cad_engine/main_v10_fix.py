from . import main_v10 as v10
from . import main_v3 as engine

app = v10.app

# 45 is not a legal DXF lineweight and ezdxf normalizes it to 50.
# Use the canonical legal value so the style dictionary and emitted DXF agree.
v10.E_STYLE['ELECTRICAL_RISERS'] = (5, 50, ('CONTINUOUS',))

_base_qa = v10._qa


def qa_normalized(doc, levels, layouts, stats, circuits, unit):
    report = _base_qa(doc, levels, layouts, stats, circuits, unit)
    # DXF block table names are case-insensitive and ezdxf exposes block_names()
    # normalized to lowercase. Validate canonically rather than case-sensitively.
    required = {'et_light','et_sw1','et_socket','et_data','et_sd','et_hd','et_db','et_mdb','et_facp','et_elevator_panel','et_pe'}
    report['checks']['canonical_block_library'] = required.issubset({x.lower() for x in doc.blocks.block_names()})
    # Re-evaluate the legal lineweight/style gate after the correction above.
    report['checks']['layer_dictionary'] = all(
        ('ENGITOOLS-E-' + key) in doc.layers
        and doc.layers.get('ENGITOOLS-E-' + key).dxf.color == style[0]
        and doc.layers.get('ENGITOOLS-E-' + key).dxf.lineweight == style[1]
        for key, style in v10.E_STYLE.items()
    )
    passed = sum(bool(value) for value in report['checks'].values())
    report['passed'] = passed
    report['total'] = len(report['checks'])
    report['score_10'] = round(10.0 * passed / report['total'], 1) if report['total'] else 0.0
    return report


v10._qa = qa_normalized
engine.design_dxf = v10.design_dxf_v10
engine.electrical_calc = v10.electrical_calc_v10


@app.get('/v10-fix-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '1.0.1-electrical-v10',
        'legal_dxf_lineweights': True,
        'case_insensitive_block_qa': True,
        'comprehensive_electrical_rulebook_gate': True,
        'construction_ready': False,
        'professional_verification_required': True,
    }
