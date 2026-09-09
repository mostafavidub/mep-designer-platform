from cad_engine.manufacturer_database import ingest_manufacturer_record, build_manufacturer_database


def record(model='X24'):
    return {'manufacturer':'Official HVAC','model':model,'equipment_type':'package','capacity':{'heating_kw':24},
            'dimensions_mm':{'width':400,'height':700,'depth':260},'weight_kg':32,
            'connections':{'gas_mm':20,'water_mm':20},'electrical':{'voltage':230,'power_w':120},
            'water_flow':{'lps':0.3},'gas_consumption':{'m3h':2.73},'refrigerant':{'not_applicable':True},
            'piping_limits':{'max_length_m':30},'clearances_mm':{'front':600},'sound':{'db':45},
            'pressure':{'max_bar':3},'pump_curve':{'points':[[0,5],[1,3]]},
            'fan_curve':{'not_applicable':True},'official_document':{
              'source_type':'OFFICIAL_MANUFACTURER','official_url':'https://official.example/x24.pdf',
              'revision':'2026-01','sha256':'a'*64,'retrieved_at':'2026-09-09'}}


def test_official_complete_record_gets_stable_catalogue_identity_without_binary_storage():
    first=ingest_manufacturer_record(record())
    second=ingest_manufacturer_record(record())
    assert first['status']=='PASS'
    assert first['catalogue_id']==second['catalogue_id']
    assert first['record']['document_storage_policy']=='HASH_AND_SEMANTIC_FIELDS_ONLY'
    database=build_manufacturer_database([record()])
    assert database['status']=='PASS'
    assert database['private_documents_stored'] is False


def test_nonofficial_or_incomplete_record_never_enters_database():
    value=record(); value['official_document']['source_type']='RESELLER'
    assert ingest_manufacturer_record(value)['status']=='FAIL'
    value=record(); del value['weight_kg']
    assert ingest_manufacturer_record(value)['status']=='INPUT_REQUIRED'


def test_duplicate_manufacturer_model_type_is_blocked():
    result=build_manufacturer_database([record(),record()])
    assert result['status']=='FAIL'
    assert 'DUPLICATE_MANUFACTURER_MODEL_TYPE' in result['errors']
