from __future__ import annotations
"""Regression checks for missing coverage, stale reads and financial precision."""
import ast
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
import db
import response_cache as cache


def test_marketed_product_survives_missing_approval(tmp_path, monkeypatch):
    import main
    path = tmp_path / 'products.db'
    db.init(path)
    monkeypatch.setattr(db, 'DB_PATH', path)
    conn = db.get_connection(path)
    cid = conn.execute("INSERT INTO companies (ticker,name) VALUES ('ARGX','argenx')").lastrowid
    aid = conn.execute("INSERT INTO assets (owner_company_id,brand_name,is_marketed) VALUES (?, 'Vyvgart',1)", (cid,)).lastrowid
    conn.execute("INSERT INTO assets (owner_company_id,brand_name,is_marketed) VALUES (?, 'Candidate',0)", (cid,))
    conn.commit()
    found = main.company_approvals('ARGX')['approvals']
    assert len(found) == 1
    assert found[0]['asset_id'] == aid
    assert found[0]['approval_date'] is None
    assert found[0]['approval_status'] == 'missing_record'
    conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date) VALUES (?, 'BLA123', '2021-01-01')", (aid,))
    conn.commit()
    conn.close()
    found = main.company_approvals('ARGX')['approvals']
    assert len(found) == 1
    assert found[0]['approval_status'] == 'recorded'


def test_company_read_recomputes_old_snapshot(monkeypatch):
    monkeypatch.setenv('ER_TOOL_RESPONSE_CACHE', '1')
    monkeypatch.setenv('ER_TOOL_RESPONSE_CACHE_DISK', '0')
    monkeypatch.setattr(cache, 'load_from_disk', lambda: None)
    revision = [1]
    monkeypatch.setattr(cache, 'stamp', lambda: tuple(revision))
    cache.clear()
    app = FastAPI()
    app.middleware('http')(cache.handle)
    @app.get('/companies/ARGX/forecast/1/verdict')
    def value():
        return {'close': revision[0]}
    with TestClient(app) as client:
        assert client.get('/companies/ARGX/forecast/1/verdict').json()['close'] == 1
        revision[0] = 2
        response = client.get('/companies/ARGX/forecast/1/verdict')
        assert response.json()['close'] == 2
        assert response.headers['x-cache'] == 'miss'
        assert client.get('/companies/ARGX/forecast/1/verdict').headers['x-cache'] == 'hit'
    cache.clear()


def ui_helpers():
    import sys
    root = Path(__file__).resolve().parents[2] / 'frontend'
    sys.path.insert(0, str(root))
    import theme
    source = ast.parse((root / 'streamlit_app.py').read_text())
    names = {'_scaled','snapshot_strip','statement_table','line_scale','_year_ago_column'}
    nodes = [n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names]
    from html import escape
    env = {'T':theme,'BILLIONS_ABOVE':1e9,'ABSOLUTE':'Absolute','COMMON_SIZE':'Common size',
           'GROWTH':'Growth','html_escape':escape,'metric_tiles':lambda rows,**kwargs:rows}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'helpers','exec'),env)
    return env


def test_small_company_tiles_preserve_amounts_and_missing_values():
    ui = ui_helpers()
    rows = ui['snapshot_strip'](dict(revenue=6_200_000, net_income=-19_800_000,
        revenue_growth=None, net_income_growth=None,eps_diluted=None,rd_intensity=None))
    assert rows[0][1:3] == ('6.2','m')
    assert rows[1][1:3] == ('−19.8','m')
    assert ui['_scaled'](None) == (None,'')
    assert ui['_scaled'](0) == ('0.00','')
    assert ui['_scaled'](12500) == ('12.5','k')


def test_statement_money_scale_does_not_change_eps_or_shares():
    ui = ui_helpers()
    block = {'periods':[{'label':'Q2 26'}], 'lines':[
        {'label':label,'role':'','unit':unit,'cells':[{'value':v,'derived':False}]}
        for label,unit,v in [('Revenue','USD',6_200_000),('EPS','USD/shares',-0.35),('Shares','shares',57_000_000)]]}
    result = ui['statement_table'](block,'USD')
    assert 'USD m' in result and '6.20' in result and '−0.35' in result and '57' in result
