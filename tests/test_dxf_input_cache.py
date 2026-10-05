from concurrent.futures import ThreadPoolExecutor

from app import dxf_input


def test_explicit_cache_scope_reads_each_resolved_path_once(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        dxf_input, "_read_input_dxf_uncached",
        lambda path: calls.append(str(path.resolve())) or (object(), {"path": path.name}),
    )
    source = tmp_path / "one.dxf"
    token = dxf_input.begin_input_read_cache()
    try:
        first = dxf_input.read_input_dxf(source)
        second = dxf_input.read_input_dxf(source)
    finally:
        dxf_input.end_input_read_cache(token)

    assert first is second
    assert calls == [str(source.resolve())]
    dxf_input.read_input_dxf(source)
    assert calls == [str(source.resolve()), str(source.resolve())]


def test_cache_scopes_are_isolated_between_concurrent_analyses(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        dxf_input, "_read_input_dxf_uncached",
        lambda path: calls.append(path.name) or (object(), {"path": path.name}),
    )

    def analyze(name):
        token = dxf_input.begin_input_read_cache()
        try:
            first = dxf_input.read_input_dxf(tmp_path / name)
            second = dxf_input.read_input_dxf(tmp_path / name)
            return first is second
        finally:
            dxf_input.end_input_read_cache(token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(analyze, ("a.dxf", "b.dxf")))

    assert results == [True, True]
    assert sorted(calls) == ["a.dxf", "b.dxf"]


def test_cache_scope_is_cleaned_after_exception(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        dxf_input, "_read_input_dxf_uncached",
        lambda path: calls.append(path.name) or (object(), {}),
    )
    source = tmp_path / "failure.dxf"
    token = dxf_input.begin_input_read_cache()
    try:
        dxf_input.read_input_dxf(source)
        raise RuntimeError("analysis failed")
    except RuntimeError:
        pass
    finally:
        dxf_input.end_input_read_cache(token)

    dxf_input.read_input_dxf(source)
    assert calls == ["failure.dxf", "failure.dxf"]
