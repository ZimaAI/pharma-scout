#!/usr/bin/env python3
"""Validate this documentation pack, not the not-yet-implemented platform.
Dependencies: Python 3.11+, PyYAML, jsonschema. Does not access the network.
"""
from pathlib import Path
import ast, hashlib, json, re, sys
try:
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:
    raise SystemExit('Install PyYAML and jsonschema before running document checks.') from exc
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ok(message):
    checks.append(message)
    print('PASS:', message)
def load(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))
def walk_refs(value, root):
    if isinstance(value, dict):
        if '$ref' in value and value['$ref'].startswith('#/'):
            node = root
            for part in value['$ref'][2:].split('/'):
                node = node[part.replace('~1','/').replace('~0','~')]
        for child in value.values(): walk_refs(child, root)
    elif isinstance(value, list):
        for child in value: walk_refs(child, root)

for path in ROOT.rglob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
ok('All JSON files parse')
spec = yaml.safe_load((ROOT/'contracts/openapi.yaml').read_text(encoding='utf-8'))
assert spec['openapi'] == '3.1.0'
walk_refs(spec, spec)
ops = []
for path, methods in spec['paths'].items():
    actual_path_params = set(re.findall(r'{([^}]+)}', path))
    for method, operation in methods.items():
        assert method in {'get','post','patch','put','delete'}
        ops.append(operation['operationId'])
        declared = {p['name'] for p in operation.get('parameters',[]) if p['in']=='path'}
        assert actual_path_params == declared, (path, declared)
        assert any(c.startswith('2') for c in operation['responses'])
assert len(ops) == len(set(ops))
ok(f'{len(ops)} OpenAPI operations: refs, unique IDs, path parameters and response presence checked')
# These are subset checks, NOT a full OpenAPI conformance validator.
for path in (ROOT/'contracts').glob('*.schema.json'):
    schema = json.loads(path.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    walk_refs(schema, schema)
ok('Standalone JSON Schemas pass Draft202012 meta-schema and local reference checks')

schemas = spec['components']['schemas']
def check_model(model, instance):
    schema = {'$schema':'https://json-schema.org/draft/2020-12/schema',
              'components':{'schemas':schemas}, '$ref':'#/components/schemas/'+model}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)
for drug in load('fixtures/01-drugs.json'):check_model('Drug',drug)
for snap in load('fixtures/02-trial-snapshots.json'):check_model('SourceSnapshot',snap)
for ob in load('fixtures/03-observations.json'):check_model('Observation',ob)
check_model('Trial',load('fixtures/04-trial-record.json'))
check_model('SourceSnapshot',load('fixtures/05-publication-snapshot.json'))
for ev in load('fixtures/06-evidence.json'):check_model('Evidence',ev)
check_model('ResearchInput',load('fixtures/07-research-request.json'))
check_model('ResearchOutput',load('fixtures/08-research-output.json'))
for event in load('fixtures/09-run-events.json'):check_model('RunEvent',event)
for event in load('fixtures/11-events-and-revisions.json')['events']:check_model('Event',event)
for rev in load('fixtures/11-events-and-revisions.json')['revisions']:check_model('EventRevision',rev)
ok('All typed fixtures validate against the API schemas')

snaps = load('fixtures/02-trial-snapshots.json')+[load('fixtures/05-publication-snapshot.json')]
snapshot_by_id = {x['id']:x for x in snaps}
for snap in snaps:
    payload = json.dumps(snap['raw_payload'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(payload).hexdigest() == snap['content_hash']
for ev in load('fixtures/06-evidence.json'):
    snap = snapshot_by_id[ev['snapshot_id']]
    assert ev['workspace_id'] == snap['workspace_id']
    node = snap
    for key in ev['locator']['path'][1:].split('/'):
        key = key.replace('~1','/').replace('~0','~')
        node = node[int(key)] if isinstance(node,list) else node[key]
    rendered = node if isinstance(node,str) else json.dumps(node,ensure_ascii=False,separators=(',',':'))
    assert rendered == ev['quoted_text']
    assert hashlib.sha256(rendered.encode()).hexdigest() == ev['snippet_hash']
ok('Fixture snapshot hashes, evidence locators, quote hashes and workspace refs are consistent')
obs = load('fixtures/03-observations.json')
assert len(obs)==5 and len(set(x['snapshot_id'] for x in obs))==3
assert obs[0]['snapshot_id']==obs[1]['snapshot_id']==obs[4]['snapshot_id']
assert obs[1]['outcome']=='unchanged' and obs[4]['outcome']=='changed'
ok('Repeated observation and content-reversion fixtures preserve the expected history')

out = load('fixtures/08-research-output.json')
evs = {x['id']:x for x in load('fixtures/06-evidence.json')}
keys = [c['claim_key'] for c in out['claims']]
assert len(keys)==len(set(keys))
for c in out['claims']:
    if c['category']=='fact':assert any(e['relation']=='supports' for e in c['evidence_links'])
    for link in c['evidence_links']:
        e = evs[link['evidence_id']]
        assert snapshot_by_id[e['snapshot_id']]['first_observed_at'] <= out['scope']['knowledge_cutoff']
for sec in out['sections']:assert set(sec['claim_keys']) <= set(keys)
revisions={x['id']:x for x in load('fixtures/11-events-and-revisions.json')['revisions']}
for rid in out['event_revision_ids']:
    assert rid in revisions
    assert revisions[rid]['observed_at'] <= out['scope']['knowledge_cutoff']
ok('Sample report has known evidence/claim/event refs and does not use future evidence')

missing=[]
for md in ROOT.rglob('*.md'):
    text=md.read_text(encoding='utf-8')
    # Ignore source URLs, fragments, and inline code. Check explicit local Markdown links only.
    for target in re.findall(r'\]\(([^)]+)\)',text):
        if re.match(r'^[a-zA-Z]+:',target) or target.startswith('#'):continue
        path=target.split('#')[0]
        if path and not (md.parent/path).exists():missing.append((str(md.relative_to(ROOT)),target))
assert not missing, missing
ok('All explicit local Markdown links resolve')

sql=(ROOT/'database/schema.sql').read_text(encoding='utf-8')
tables=set(re.findall(r'CREATE TABLE\s+(\w+)',sql))
for t in re.findall(r'REFERENCES\s+(\w+)\s*\(',sql):assert t in tables,t
ok(f'{len(tables)} SQL table declarations and textual FK target names are consistent (SQL NOT executed)')
scenarios=len(re.findall(r'^  Scenario:',(ROOT/'acceptance/acceptance.feature').read_text(),flags=re.M))
ok(f'{scenarios} Gherkin scenarios present (step definitions NOT implemented)')
print('\nDocument checks passed. This does not validate PostgreSQL execution, full OpenAPI conformance, APIs, DeerFlow, live data or browser behavior.')
report='# 文档包静态校验结果\n\n生成日期：2026-09-21。以下仅验证文档与样例，不代表平台软件已实现。\n\n'+''.join('- PASS：'+x+'\n' for x in checks)+'\n未执行：PostgreSQL建表/迁移、完整OpenAPI规范验证器、DeerFlow运行、真实来源/模型、浏览器E2E、SMTP投递。\n'
(ROOT/'delivery/CONTEXT_VALIDATION.md').write_text(report,encoding='utf-8')
