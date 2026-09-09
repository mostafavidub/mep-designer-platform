"""Hash-only official manufacturer record registry for engineering selection."""
from __future__ import annotations

from hashlib import sha256
import json
import re


REQUIRED_RECORD_FIELDS={
    'manufacturer','model','equipment_type','capacity','dimensions_mm','weight_kg','connections',
    'electrical','water_flow','gas_consumption','refrigerant','piping_limits','clearances_mm',
    'sound','pressure','pump_curve','fan_curve','official_document',
}


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def ingest_manufacturer_record(record):
    missing=sorted(REQUIRED_RECORD_FIELDS-set(record or {}))
    document=(record or {}).get('official_document') or {}
    required_document={'source_type','official_url','revision','sha256','retrieved_at'}
    missing += [f'official_document.{key}' for key in sorted(required_document-set(document))]
    if missing:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(set(missing)),'record':None}
    errors=[]
    if document['source_type']!='OFFICIAL_MANUFACTURER':errors.append('DOCUMENT_SOURCE_NOT_OFFICIAL_MANUFACTURER')
    if not str(document['official_url']).startswith('https://'):errors.append('OFFICIAL_URL_MUST_USE_HTTPS')
    if not re.fullmatch(r'[0-9a-fA-F]{64}',str(document['sha256'])):errors.append('OFFICIAL_DOCUMENT_SHA256_INVALID')
    for key in ('capacity','dimensions_mm','connections','electrical','piping_limits','clearances_mm'):
        if record[key] in (None,{},[]):errors.append(f'ENGINEERING_FIELD_EMPTY:{key}')
    if errors:return {'status':'FAIL','errors':errors,'record':None}
    normalized=json.loads(_canonical(record))
    catalogue_id='MFR-'+sha256(_canonical(normalized).encode()).hexdigest()[:20].upper()
    normalized['catalogue_id']=catalogue_id
    normalized['document_storage_policy']='HASH_AND_SEMANTIC_FIELDS_ONLY'
    return {'status':'PASS','record':normalized,'catalogue_id':catalogue_id}


def build_manufacturer_database(records):
    if not records:return {'status':'INPUT_REQUIRED','missing_inputs':['OFFICIAL_MANUFACTURER_RECORDS'],'records':[]}
    accepted=[];rejected=[]
    for source in records:
        result=ingest_manufacturer_record(source)
        if result['status']=='PASS':accepted.append(result['record'])
        else:rejected.append({'manufacturer':source.get('manufacturer'),'model':source.get('model'),
                              'status':result['status'],'issues':result.get('errors') or result.get('missing_inputs')})
    keys=[(row['manufacturer'],row['model'],row['equipment_type']) for row in accepted]
    if len(keys)!=len(set(keys)):
        return {'status':'FAIL','errors':['DUPLICATE_MANUFACTURER_MODEL_TYPE'],'records':accepted,'rejected':rejected}
    status='PASS' if accepted and not rejected else ('INPUT_REQUIRED' if not accepted else 'FAIL')
    return {'status':status,'records':sorted(accepted,key=lambda x:(x['equipment_type'],x['manufacturer'],x['model'])),
            'rejected':rejected,'record_count':len(accepted),'private_documents_stored':False,
            'policy':'OFFICIAL_MANUFACTURER_DOCUMENTATION_ONLY'}
