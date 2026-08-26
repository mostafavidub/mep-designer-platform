"""Evidence-gated gas network engine for mechanical v11."""


def _families(calc):
    return {str(x.get('family') or '') for x in (calc.get('_approved_drawing_manifest') or {}).get('sheets') or []}


def _negative(value):
    text = str(value or '').strip().lower()
    return any(x in text for x in ('خیر','ندارد','بدون','none','no gas','false'))


def _ensure_gas_blocks(doc):
    defs = {
        'ET_M_GAS_METER': ('M', .16),
        'ET_M_GAS_REGULATOR': ('R', .16),
        'ET_M_GAS_VALVE': ('V', .12),
    }
    for name, (tag, radius) in defs.items():
        if name in doc.blocks:
            continue
        block = doc.blocks.new(name=name)
        block.add_circle((0,0), radius)
        block.add_text(tag, dxfattribs={'height': .08}).set_placement((-.04,-.03))


def install(v10_4):
    if getattr(v10_4, '_gas_v11_installed', False):
        return
    original = v10_4._add_shared_distribution_networks

    def with_gas(doc, levels, model, calc):
        report = dict(original(doc, levels, model, calc) or {})
        families = _families(calc)
        if 'gas' not in families or _negative((calc.get('_design_inputs') or {}).get('gas')):
            report['gas_network_status'] = 'NOT_APPLICABLE'
            return report

        required = ('gas_load_kw','gas_flow_m3h','gas_pressure_mbar','gas_main_dn_mm','gas_meter_regulator_defined')
        missing = [k for k in required if model.get(k) in (None,'',False)]
        if missing:
            raise RuntimeError('Gas network QA failed: unresolved gas model: ' + ', '.join(missing))

        _ensure_gas_blocks(doc)
        v10_4._ensure_symbol_blocks(doc)
        msp = doc.modelspace(); seen = set(); terminals_total = 0; proposed = 0
        meter_count = regulator_count = valve_count = 0
        for level in levels:
            if v10_4.v8._is_roof(level):
                continue
            hub = v10_4.v8._find_level_riser(msp, level)
            if not hub:
                continue
            detected = [f['point'] for f in level.get('fixtures', []) if f.get('kind') == 'gas' and f.get('point')]
            terminals = list(detected)
            if not terminals:
                # The resolved appliance schedule proves a gas consumer exists,
                # but exploded architecture may not expose a symbol. Use only an
                # observed kitchen location and mark it Proposed, never Detected.
                kitchens = [r['point'] for r in level.get('rooms', []) if r.get('room') == 'kitchen' and r.get('point')]
                terminals = kitchens
                proposed += len(kitchens)
            if not terminals:
                continue
            row = v10_4._shared_network(
                msp, terminals, hub, 'ENGITOOLS-M-GAS', 'gas', model, seen,
            )
            terminals_total += row['terminals']
            # The service point is explicit on every active gas level.
            msp.add_blockref('ET_M_GAS_METER', hub, dxfattribs={'layer':'ENGITOOLS-M-GAS'}); meter_count += 1
            msp.add_blockref('ET_M_GAS_REGULATOR', (hub[0]+.28, hub[1]), dxfattribs={'layer':'ENGITOOLS-M-GAS'}); regulator_count += 1
            v10_4._plan_text(
                msp,
                f"GAS METER/REGULATOR {model['gas_pressure_mbar']} mbar | MAIN DN{model['gas_main_dn_mm']} [CALCULATED]",
                hub, 'ENGITOOLS-M-GAS', (.35,.35),
            )
            for point in terminals:
                msp.add_blockref('ET_M_GAS_VALVE', point, dxfattribs={'layer':'ENGITOOLS-M-GAS'}); valve_count += 1
                provenance = 'DETECTED' if point in detected else 'RULE-BASED PROPOSED'
                v10_4._plan_text(
                    msp, f"G DN{model['gas_main_dn_mm']} | SHUTOFF [{provenance}]",
                    point, 'ENGITOOLS-M-GAS', (.22,.18),
                )

        line_count = sum(1 for e in msp if e.dxftype() in {'LINE','LWPOLYLINE'} and str(getattr(e.dxf,'layer','')) == 'ENGITOOLS-M-GAS')
        checks = {
            'gas_terminals': terminals_total > 0,
            'gas_connected_network': line_count >= 1,
            'gas_meter': meter_count > 0,
            'gas_regulator': regulator_count > 0,
            'gas_terminal_shutoff': valve_count >= terminals_total > 0,
        }
        failed = [k for k,v in checks.items() if not v]
        report['gas_network'] = {
            'status': 'PASS' if not failed else 'FAIL', 'checks': checks,
            'terminals': terminals_total, 'proposed_terminals': proposed,
            'lines': line_count, 'meters': meter_count, 'regulators': regulator_count, 'valves': valve_count,
        }
        report['gas_network_status'] = report['gas_network']['status']
        if failed:
            raise RuntimeError('Gas network QA failed: ' + ', '.join(failed))
        return report

    v10_4._add_shared_distribution_networks = with_gas
    v10_4._gas_v11_installed = True
