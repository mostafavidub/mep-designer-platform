import json
import subprocess
import pytest
from tools.swcis_scope import resolve_request


def setup_history(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()
    git('init', '-q');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
    (tmp_path/'changes').mkdir();(tmp_path/'seed').write_text('base')
    git('add','.');git('commit','-qm','base');base=git('rev-parse','HEAD')
    for n in ['one','two']:
        (tmp_path/f'changes/{n}.yaml').write_text('{}')
        git('add','.');git('commit','-qm',n)
    source=git('rev-parse','HEAD');manifest={'base_sha':base,'source_sha':source,
        'source_tree':git('rev-parse','HEAD^{tree}'),
        'historical_requests':{f'changes/{n}.yaml':git('rev-parse',f'HEAD:changes/{n}.yaml') for n in ['one','two']}}
    def commit(m=manifest):
        (tmp_path/'changes/integration.yaml').write_text(json.dumps({'integration':m}))
        git('add','.');git('commit','-qm','integration')
    return git,base,manifest,commit


def test_sealed_history_selects_one_cumulative_request(tmp_path):
    _,base,manifest,commit=setup_history(tmp_path);commit()
    assert resolve_request(base,root=tmp_path)=='changes/integration.yaml'


@pytest.mark.parametrize('mutation', ['missing','extra','modified','tree','base','ancestry'])
def test_integration_history_tampering_fails_closed(tmp_path,mutation):
    git,base,m,commit=setup_history(tmp_path)
    if mutation=='missing':m['historical_requests'].pop('changes/one.yaml')
    elif mutation=='extra':(tmp_path/'changes/extra.yaml').write_text('{}')
    elif mutation=='modified':(tmp_path/'changes/one.yaml').write_text('{"changed":true}')
    elif mutation=='tree':m['source_tree']='0'*40
    elif mutation=='base':m['base_sha']=m['source_sha']
    else:m['source_sha']=base
    commit()
    with pytest.raises(ValueError):resolve_request(base,root=tmp_path)


def test_unsealed_multiple_requests_still_fail(tmp_path):
    _,base,_,_=setup_history(tmp_path)
    with pytest.raises(ValueError):resolve_request(base,root=tmp_path)


def test_ordinary_single_request_unchanged(tmp_path):
    git,_,_,_=setup_history(tmp_path)
    assert resolve_request(git('rev-parse','HEAD^'),root=tmp_path)=='changes/two.yaml'
