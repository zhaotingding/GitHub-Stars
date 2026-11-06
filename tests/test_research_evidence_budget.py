"""Budgeted evidence retains citable prefixes and recovers only the sent sources."""
import json

import httpx
import pytest
from test_research import (
    action,
    answer,
    configure,
    get_body,
    install_transport,
    model_input,
    put_repository,
    reply,
    start,
)
from test_research import research_service as _research_service

research_service = _research_service


def small_budget(service):
    configure(service, max_calls=2, max_tools=1, max_input_chars=6000)
    # Escapes and non-ASCII text exercise the serialized JSON limit rather than raw text length.
    put_repository(service, text='# Robot perception\n' + '机器人 vision "quoted" \\path\tinputs\n' * 600)


def test_read_source_keeps_a_citable_prefix_within_the_actual_json_budget(research_service):
    service = research_service
    small_budget(service)

    def handler(request):
        value = action('read_source', 'R1') if len(requests) == 1 else answer(agent=True)
        return httpx.Response(200, json=reply(value, identity=f'resp_budget_{len(requests)}'))

    requests, _ = install_transport(service, handler)
    job = start(service, mode='agent', repo_ids=[1])
    assert job['state'] == 'done' and job['calls'] == 2
    assert service.store.research_job(job['id'])['tools'] == 1
    assert all(len(get_body(request)['input']) <= 6000 for request in requests)
    actions = [get_body(request)['text']['format']['schema']['properties']['action']['enum'] for request in requests]
    assert 'read_source' in actions[0] and actions[1] == ['answer']
    assert '仅允许answer' in get_body(requests[1])['instructions']
    evidence = model_input(requests[1])['evidence']
    assert len(evidence) == 1
    sent = evidence[0]
    scope = service.store.research_job(job['id'])['scope']
    frozen = next(source for source in scope['records'] if source['label'] == 'R1')
    assert 2400 < len(sent['text']) < 8000 and frozen['body'].startswith(sent['text'])
    for key in ('label', 'url', 'sha', 'captured'):
        assert sent[key] == frozen[key]
    assert sent['truncated'] and '输入字符预算' in sent['truncation_note']
    packed = model_input(requests[1])
    assert packed['scope_truncated'] and packed['organization']['truncated']
    assert '未发送' in packed['evidence_note']
    assert job['sources'] == evidence
    assert {label for claim in job['result']['claims'] for label in claim['sources']} <= {sent['label']}
    trace = next(entry for entry in job['trace'] if entry['action'] == '证据预算')
    assert '已发送来源：R1' in trace['detail'] and '截短1条，省略0条' in trace['detail']
    assert frozen['body'] != sent['text']  # The original frozen scope remains available to tools.


def test_local_recovery_uses_original_prepared_evidence_and_rejects_unsent_labels(research_service):
    service = research_service
    for citation, expected in (('R1', 'done'), ('R999', 'failed')):
        small_budget(service)
        service.store.execute("CREATE TRIGGER block_budget_result BEFORE UPDATE OF result ON research_jobs "
                              "BEGIN SELECT RAISE(ABORT, 'isolated apply failure'); END")

        def handler(request):
            value = action('read_source', 'R1') if len(requests) == 1 else answer(citation, agent=True)
            return httpx.Response(200, json=reply(value, identity=f'resp_recover_{citation}_{len(requests)}'))

        requests, _ = install_transport(service, handler)
        job = start(service, mode='agent', repo_ids=[1])
        assert job['state'] == ('paused' if citation == 'R1' else 'failed')
        assert len(requests) == 2
        steps = service.store.research_steps(job['id'])
        prepared = steps[-1]['prepared']
        assert steps[-1]['response'] and not steps[-1]['applied']
        assert 'evidence' not in prepared  # Old persisted steps need no new top-level field.
        sent = json.loads(prepared['input'])['evidence']
        original_scope = service.store.research_job(job['id'])['scope']
        service.store.execute('DROP TRIGGER block_budget_result')
        service.store.research_update(job['id'], sources=[dict(sent[0], label='R999', text='UNSENT EVIDENCE')])
        config = service.paths.load()
        config['research'].update(model='different-model', max_input_chars=4000)
        service.paths.save(config)
        service.research_client_factory = lambda _: pytest.fail('accepted-response recovery must be local')

        recovered = service.run('research_resume', job_id=job['id'])['research_job']
        assert recovered['state'] == expected and len(requests) == 2
        assert service.store.research_steps(job['id'])[-1]['prepared'] == prepared
        assert service.store.research_job(job['id'])['scope'] == original_scope
        if citation == 'R1':
            assert recovered['sources'] == sent and recovered['result'] == answer()
        else:
            assert not recovered['result'] and '引用不属于本次已提供证据' in recovered['error']


@pytest.mark.parametrize('limits,tools_before_answer', [
    ({'max_calls': 1, 'max_tools': 4}, 0),
    ({'max_calls': 3, 'max_tools': 0}, 0),
    ({'max_calls': 3, 'max_tools': 1}, 1),
])
def test_agent_reserves_closing_decisions_for_answers(research_service, limits, tools_before_answer):
    service = research_service
    configure(service, **limits)

    def handler(request):
        allowed = get_body(request)['text']['format']['schema']['properties']['action']['enum']
        if len(requests) <= tools_before_answer:
            assert 'preferences' in allowed and 'read_source' in allowed
            value = action('preferences')
        else:
            assert allowed == ['answer']
            assert '仅允许answer' in get_body(request)['instructions']
            assert 'limitations' in get_body(request)['instructions']
            assert model_input(request)['evidence']
            value = answer(agent=True)
        return httpx.Response(200, json=reply(value, identity=f'resp_closing_{len(requests)}'))

    requests, _ = install_transport(service, handler)
    job = start(service, mode='agent')
    assert job['state'] == 'done' and job['calls'] == tools_before_answer+1
    assert service.store.research_job(job['id'])['tools'] == tools_before_answer
    assert len(requests) <= limits['max_calls']


@pytest.mark.parametrize('limits', [{'max_calls': 1}, {'max_tools': 0}])
def test_closing_without_citable_evidence_stops_before_a_model_request(research_service, limits):
    service = research_service
    configure(service, **limits)
    requests, _ = install_transport(service, lambda _: pytest.fail('no evidence must not force a fabricated answer'))
    job = service.run('research', question='量子纠错拓扑编码', mode='agent', repo_ids=[1])['research_job']
    assert job['state'] == 'limited' and job['calls'] == 0 and not requests
    assert '没有可引用的已发送证据' in job['error'] and not job['result']


@pytest.mark.parametrize('max_calls,expected,tools', [(1, 'limited', 0), (2, 'continuable', 1)])
def test_resume_enforces_the_original_action_schema_after_configuration_changes(
        research_service, max_calls, expected, tools):
    service = research_service
    configure(service, max_calls=max_calls)

    def handler(request):
        return httpx.Response(200, json=reply(action('preferences'), identity='resp_original_schema',
                                               status='queued' if request.method == 'POST' else 'completed'))

    requests, _ = install_transport(service, handler)
    job = start(service, mode='agent')
    assert job['state'] == 'paused'
    original = service.store.research_steps(job['id'])[0]['prepared']
    config = service.paths.load()
    config['research'].update(max_calls=6 if max_calls == 1 else 1, max_tools=8 if max_calls == 1 else 0)
    service.paths.save(config)
    recovered = service.run('research_resume', job_id=job['id'])['research_job']
    assert recovered['state'] == expected and service.store.research_job(job['id'])['tools'] == tools
    assert [request.method for request in requests] == ['POST', 'GET']
    assert service.store.research_steps(job['id'])[0]['prepared'] == original
    if max_calls == 1:
        assert original['schema']['properties']['action']['enum'] == ['answer']
        assert not recovered['result'] and '未执行额外工具' in recovered['error']
        assert service.run('research_resume', job_id=job['id'])['research_job']['state'] == 'limited'
        assert [request.method for request in requests] == ['POST', 'GET']
    else:
        assert 'preferences' in original['schema']['properties']['action']['enum']
