from cad_engine.independent_deliverables import (
    IRAN_MABHAS17_1403_GAS_TABLE, _official_iran_gas_capacity_rows,
)
from cad_engine.mechanical_execution_sizing import design_gas_network


def _appliance(flow):
    return {"id":"G1","pmm_id":"PMM-G1","manufacturer":"SOURCE","model":"PROJECT",
            "thermal_input_kw":flow*10.5,"gas_consumption_m3h":flow,
            "datasheet":{"official_url":"project:input","revision":"1","sha256":"a"*64},
            "appliance_valve":"required","flue":"required","combustion_air":"required"}


def _basis():
    return {"capacity_table":_official_iran_gas_capacity_rows(),"service_pressure_mbar":17.259,
            "allowable_pressure_drop_mbar":1.245,"meter":"project input","regulator":"project input",
            "service_shutoff":"required","riser":"project input","fittings":"project input",
            "sleeves":"required"}


def test_official_table_has_every_printed_length_and_diameter_cell():
    table=IRAN_MABHAS17_1403_GAS_TABLE
    assert len(table["rows"])==30
    assert all(set(row)=={15,20,25,32,40,50,65,80,100} for row in table["rows"].values())
    assert len(_official_iran_gas_capacity_rows())==270
    assert table["rows"][2][100]==801.6
    assert table["rows"][10][100]==329.7
    assert table["rows"][300][65]==14.6
    assert table["rows"][300][100]==53.2


def test_every_diameter_capacity_decreases_with_printed_length():
    rows=IRAN_MABHAS17_1403_GAS_TABLE["rows"]
    for dn in (15,20,25,32,40,50,65,80,100):
        values=[rows[length][dn] for length in sorted(rows)]
        assert all(left>=right for left,right in zip(values,values[1:]))


def test_new_dn65_column_is_consumed_by_canonical_gas_sizer():
    result=design_gas_network(
        [{"id":"E1","downstream_appliance_ids":["G1"],"equivalent_length_m":10}],
        [_appliance(60)],_basis())
    assert result["status"]=="PASS",result
    assert result["segments"][0]["selected_dn_mm"]==65


def test_exact_table_17_4_11_density_factor_changes_capacity_before_sizing():
    rows=_official_iran_gas_capacity_rows(0.70)
    cell=next(row for row in rows if row["max_equivalent_length_m"]==10 and row["dn_mm"]==50)
    assert cell=={"max_equivalent_length_m":10,"dn_mm":50,"max_flow_m3h":54.624,
                  "relative_density":0.70,"density_correction_factor":0.96}
    result=design_gas_network(
        [{"id":"E1","downstream_appliance_ids":["G1"],"equivalent_length_m":10}],
        [_appliance(55)],dict(_basis(),capacity_table=rows))
    assert result["status"]=="PASS"
    assert result["segments"][0]["selected_dn_mm"]==65


def test_unprinted_density_is_input_error_not_interpolated():
    try:
        _official_iran_gas_capacity_rows(0.67)
    except ValueError as error:
        assert "unsupported M17 Table 17-4-11" in str(error)
    else:
        raise AssertionError("unprinted density must not be interpolated")


def test_flow_above_largest_printed_capacity_fails_without_extrapolation():
    result=design_gas_network(
        [{"id":"E1","downstream_appliance_ids":["G1"],"equivalent_length_m":2}],
        [_appliance(801.61)],_basis())
    assert result["status"]=="FAIL"
    assert result["segments"][0]["selected_dn_mm"] is None
