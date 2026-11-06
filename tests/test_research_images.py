"""Per-question image consent, validation, caching and unknown-submit protection."""
import json
import struct
import zlib

import httpx
import pytest
from test_research import answer, configure, get_body, install_transport, model_input, reply, start
from test_research import research_service as _research_service

# Register the shared fixture without shadowing an imported fixture name in test signatures.
research_service = _research_service


def png_bytes(*, animated=False, rgb=b"\x10\x20\x30"):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + (chunk(b"acTL", struct.pack(">II", 1, 0)) if animated else b"")
            + chunk(b"IDAT", zlib.compress(b"\x00" + rgb)) + chunk(b"IEND", b""))


@pytest.fixture
def selected_png(tmp_path):
    path = tmp_path / "user-selected.png"
    path.write_bytes(png_bytes())
    return path


def image_config(service, **settings):
    return configure(service, image_model="vision-model", image_credential_source="autogpu",
                     image_input_cny_per_million=7.0, image_output_cny_per_million=11.0, **settings)


def image_handler(request):
    if isinstance(get_body(request)["input"], list):
        return httpx.Response(200, json=reply({"description": "截图显示三个处理模块及从左到右的箭头，未显示实验指标。"}, identity="resp_image"))
    evidence = model_input(request)["evidence"]
    image = next(source for source in evidence if source["kind"] == "image_interpretation")
    return httpx.Response(200, json=reply(answer(image["label"]), identity="resp_image_answer"))


def test_image_permission_rejects_before_open_or_file_metadata(research_service, monkeypatch, tmp_path):
    def forbidden(_):
        pytest.fail("a nonconsenting question must not inspect an attachment")
    monkeypatch.setattr("github_stars.research.png_attachment", forbidden)
    requests, _ = install_transport(research_service, lambda _: pytest.fail("no API without consent"))
    with pytest.raises(ValueError, match="明确.*允许读图"):
        start(research_service, image_paths=[tmp_path / "private-does-not-exist.png"])
    assert not requests and not research_service.store.rows("SELECT * FROM research_jobs")


def test_png_validation_rejects_corruption_animation_and_symlinks(research_service, tmp_path, selected_png):
    bad = tmp_path / "corrupt.png"
    bad.write_bytes(png_bytes()[:-4] + b"oops")
    animated = tmp_path / "animated.png"
    animated.write_bytes(png_bytes(animated=True))
    linked = tmp_path / "linked.png"
    linked.symlink_to(selected_png)
    requests, _ = install_transport(research_service, lambda _: pytest.fail("invalid images cannot be uploaded"))
    for path in (bad, animated, linked):
        with pytest.raises(ValueError):
            start(research_service, allow_images=True, image_paths=[path])
    assert not requests and not research_service.store.rows("SELECT * FROM research_image_claims")


def test_successful_png_reuses_description_with_independent_model_credential_and_rates(research_service, selected_png):
    service = research_service
    image_config(service)
    requests, settings = install_transport(service, image_handler)
    first = start(service, allow_images=True, image_paths=[selected_png])
    assert first["state"] == "done" and len(requests) == 2
    image_request = get_body(requests[0])
    assert image_request["model"] == "vision-model" and get_body(requests[1])["model"] == "research-model"
    assert settings[0]["credential_source"] == "autogpu" and settings[1]["credential_source"] == "msgx"
    image_content = image_request["input"][0]["content"]
    assert image_content[1]["type"] == "input_image" and image_content[1]["detail"] == "low"
    assert image_content[1]["image_url"].startswith("data:image/png;base64,")
    assert str(selected_png) not in json.dumps(image_request)
    steps = service.store.research_steps(first["id"])
    assert steps[0]["cost"] == pytest.approx(.00172) and steps[1]["cost"] == pytest.approx(.00028)
    assert not service.store.rows("SELECT * FROM research_image_claims")
    second = start(service, allow_images=True, image_paths=[selected_png])
    assert second["state"] == "done" and len(requests) == 3 and second["calls"] == 1
    assert any(row["action"] == "图片缓存" for row in second["trace"])


def test_cached_description_bypasses_fresh_image_model_rates_and_credentials(research_service, selected_png):
    service = research_service
    image_config(service)
    requests, settings = install_transport(service, image_handler)
    assert start(service, allow_images=True, image_paths=[selected_png])["state"] == "done"
    config = service.paths.load()
    config["research"].update(image_model="", image_input_cny_per_million=0.0, image_output_cny_per_million=0.0)
    service.paths.save(config)
    second = start(service, allow_images=True, image_paths=[selected_png])
    assert second["state"] == "done" and len(requests) == 3
    assert settings[-1]["credential_source"] == "msgx"
    assert not isinstance(get_body(requests[-1])["input"], list)


def test_unknown_image_is_not_uploaded_again_even_under_another_question(research_service, selected_png):
    service = research_service
    image_config(service)
    def lost(request):
        raise httpx.ReadTimeout("upload accepted but response lost", request=request)
    requests, _ = install_transport(service, lost)
    first = start(service, allow_images=True, image_paths=[selected_png])
    assert first["state"] == "blocked" and len(requests) == 1
    second = service.run("research", question="再分析这张机器人流程图", allow_images=True,
                         image_paths=[selected_png])["research_job"]
    assert second["state"] in {"failed", "blocked"} and len(requests) == 1
    assert "未解决" in second["error"] or "重复上传" in second["error"]
    with pytest.raises(ValueError, match="没有可恢复"):
        service.run("research_resume", job_id=first["id"])
    with pytest.raises(ValueError, match="不能继续"):
        service.run("research_continue", job_id=first["id"])
    assert len(requests) == 1
    claim = service.store.one("SELECT * FROM research_image_claims")
    assert claim["step_id"] == service.store.research_steps(first["id"])[0]["id"]


def test_received_image_local_recovery_needs_neither_original_file_nor_client(research_service, selected_png):
    service = research_service
    image_config(service)
    service.store.execute("CREATE TRIGGER block_image_apply BEFORE UPDATE OF sources ON research_jobs BEGIN SELECT RAISE(ABORT, 'disk simulation'); END")
    requests, _ = install_transport(service, image_handler)
    job = start(service, allow_images=True, image_paths=[selected_png])
    assert job["state"] == "paused" and len(requests) == 1
    step = service.store.research_steps(job["id"])[0]
    assert step["response"] and not step["applied"]
    assert service.store.one("SELECT description FROM research_image_cache")
    selected_png.unlink()
    service.research_client_factory = lambda _: pytest.fail("local accepted response recovery must not instantiate a client")
    service.store.execute("DROP TRIGGER block_image_apply")
    recovered = service.run("research_resume", job_id=job["id"])["research_job"]
    assert recovered["state"] == "continuable" and len(requests) == 1
    assert service.store.research_steps(job["id"])[0]["applied"]
    assert any(source["kind"] == "image_interpretation" for source in recovered["sources"])


def test_image_unknown_rates_prevent_new_upload(research_service, selected_png):
    service = research_service
    image_config(service)
    config = service.paths.load()
    config["research"]["image_input_cny_per_million"] = 0.0
    service.paths.save(config)
    requests, _ = install_transport(service, lambda _: pytest.fail("unknown image cost cannot authorize upload"))
    job = start(service, allow_images=True, image_paths=[selected_png])
    assert job["state"] == "failed" and not requests and "费率" in job["error"]


def test_standard_mode_rejects_two_attachments_before_read_or_post(research_service, selected_png, tmp_path, monkeypatch):
    image_config(research_service, max_images=2, max_calls=3)
    def forbidden(_):
        pytest.fail("standard mode must reject excess attachments before file inspection")
    monkeypatch.setattr("github_stars.research.png_attachment", forbidden)
    requests, _ = install_transport(research_service, lambda _: pytest.fail("standard mode accepts at most one image"))
    with pytest.raises(ValueError, match="标准"):
        start(research_service, allow_images=True, image_paths=[selected_png, tmp_path / "not-inspected.png"])
    assert not requests and not research_service.store.rows("SELECT * FROM research_jobs")


def test_agent_can_interpret_two_selected_images_within_five_calls(research_service, selected_png, tmp_path):
    service = research_service
    image_config(service, max_images=2, max_calls=5, max_tools=2)
    second = tmp_path / "second-selected.png"
    second.write_bytes(png_bytes(rgb=b"\x40\x50\x60"))
    def handler(request):
        if isinstance(get_body(request)["input"], list):
            return httpx.Response(200, json=reply({"description": f"第{len(requests)}张截图有可见流程模块。"}, identity=f"resp_two_image_{len(requests)}"))
        payload = model_input(request)
        interpreted = {source["label"] for source in payload["evidence"] if source["kind"] == "image_interpretation"}
        remaining = [image for image in payload["attachments"] if image["label"] not in interpreted]
        value = ({"action": "image", "source": remaining[0]["label"], "terms": [], "claims": [], "limitations": []}
                 if remaining else answer(sorted(interpreted)[0], agent=True))
        return httpx.Response(200, json=reply(value, identity=f"resp_two_decision_{len(requests)}"))
    requests, _ = install_transport(service, handler)
    job = start(service, mode="agent", allow_images=True, image_paths=[selected_png, second])
    assert job["state"] == "done" and job["calls"] == 5
    assert [step["kind"] for step in service.store.research_steps(job["id"])] == ["decision", "image", "decision", "image", "decision"]
    assert len([source for source in job["sources"] if source["kind"] == "image_interpretation"]) == 2
    assert service.store.research_job(job["id"])["tools"] == 2


def test_agent_can_choose_only_the_consented_question_attachment(research_service, selected_png):
    service = research_service
    image_config(service)
    def handler(request):
        body = get_body(request)
        if isinstance(body["input"], list):
            return httpx.Response(200, json=reply({"description": "截图有三个处理模块。"}, identity="resp_agent_image"))
        payload = model_input(request)
        images = [source for source in payload["evidence"] if source["kind"] == "image_interpretation"]
        value = (answer(images[0]["label"], agent=True) if images else
                 {"action": "image", "source": payload["attachments"][0]["label"], "terms": [], "claims": [], "limitations": []})
        return httpx.Response(200, json=reply(value, identity=f"resp_agent_{len(requests)}"))
    requests, _ = install_transport(service, handler)
    job = start(service, mode="agent", allow_images=True, image_paths=[selected_png])
    assert job["state"] == "done" and len(requests) == 3
    assert service.store.research_job(job["id"])["tools"] == 1
    assert [step["kind"] for step in service.store.research_steps(job["id"])] == ["decision", "image", "decision"]


def test_standard_image_refuses_upload_when_no_call_remains_for_answer(research_service, selected_png):
    image_config(research_service, max_calls=1)
    requests, _ = install_transport(research_service, lambda _: pytest.fail("image cannot consume the only call without an answer"))
    job = start(research_service, allow_images=True, image_paths=[selected_png])
    assert job["state"] == "limited" and job["calls"] == 0 and not requests


def test_default_sdk_client_reads_only_selected_fake_credentials_and_never_persists_keys(research_service, selected_png, monkeypatch):
    from openai import OpenAI

    from github_stars.config import Paths
    service = research_service
    image_config(service)
    requested_keys, options, requests = [], [], []
    def secret(_paths, kind, source=None):
        requested_keys.append((kind, source))
        return f"fake-isolated-{source}-key"
    def transport(request):
        requests.append(request)
        return image_handler(request)
    def constructor(**kwargs):
        options.append(dict(kwargs))
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    monkeypatch.setattr(Paths, "secret", secret)
    monkeypatch.setattr("github_stars.research.OpenAI", constructor)
    job = start(service, allow_images=True, image_paths=[selected_png])
    assert job["state"] == "done" and requested_keys == [("openai", "autogpu"), ("openai", "msgx")]
    assert all(setting["max_retries"] == 0 and 0 < setting["timeout"] <= 180 for setting in options)
    assert [request.headers["authorization"] for request in requests] == ["Bearer fake-isolated-autogpu-key", "Bearer fake-isolated-msgx-key"]
    persisted = json.dumps(service.store.rows("SELECT settings,scope FROM research_jobs")
                           + service.store.rows("SELECT prepared,response FROM research_steps"))
    assert "fake-isolated" not in persisted
