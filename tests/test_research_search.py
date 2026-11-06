"""Bounded offline evidence retrieval; no network, images or user files are read."""
import json
import struct
import zlib
from datetime import datetime, timedelta, timezone

import pytest

from github_stars.research_search import organize, png_attachment, retrieve, safe_url, snapshot, terms_for
from github_stars.store import Store

NOW = datetime(2026, 11, 6, 10, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "evidence.db")


def put(store, number=1, text="Robot perception and robotics toolkit", **metadata):
    repo = {"id": number, "full_name": f"owner/project{number}", "description": "robotics", "topics": ["robotics"],
            "stargazers_count": 100, "pushed_at": "2010-01-01T00:00:00Z", **metadata}
    store.upsert(repo, "research", NOW)
    store.cache_readme(number, text, f"sha-{number}", f"https://github.com/owner/project{number}/blob/main/README.md", NOW.isoformat())


@pytest.mark.parametrize("scope", [[], (), [True], [0], [-1], [1, 1], list(range(1, 32)), [999]])
def test_scope_ids_are_strict_and_never_fall_back_to_all_repositories(store, scope):
    put(store)
    with pytest.raises(ValueError):
        snapshot(store, NOW, scope)


def test_ignored_scope_is_rejected_and_global_scope_excludes_it(store):
    put(store)
    put(store, 2)
    store.execute("UPDATE repos SET feedback='dismissed' WHERE id=2")
    assert {row["repo_id"] for row in snapshot(store, NOW)["records"]} == {1}
    with pytest.raises(ValueError):
        snapshot(store, NOW, [2])


def test_snapshot_freezes_versions_and_uses_collection_time_not_author_time(store):
    put(store, text="Robot README old evidence")
    yesterday = NOW - timedelta(days=1)
    store.execute("UPDATE repos SET readme_at=?", (yesterday.isoformat(),))
    # Refresh archives the original observed README and a new independent version.
    store.cache_readme(1, "Robot README new evidence", "new", "https://github.com/owner/project1/blob/new/README.md", NOW.isoformat())
    scope = snapshot(store, NOW, [1])
    current = next(row for row in scope["records"] if row["label"] == "R1")
    history = [row for row in scope["records"] if row["kind"] == "readme_version"]
    assert current["sha"] == "new" and current["captured"] == NOW.isoformat()
    assert len(history) == 1 and history[0]["label"].startswith("H")
    # First observation of this SHA remains its original collected time.
    assert history[0]["captured"] == NOW.isoformat()
    assert history[0]["body"] == "Robot README old evidence"
    frozen = json.dumps(scope)
    store.cache_readme(1, "Robot README third evidence", "third", "https://github.com/owner/project1", (NOW + timedelta(hours=1)).isoformat())
    assert json.dumps(scope) == frozen


def test_history_and_star_window_excludes_future_and_ancient_evidence(store):
    put(store)
    for label, offset in [("old", -40), ("retained", -2), ("future", 2)]:
        when = NOW + timedelta(days=offset)
        store.execute("INSERT INTO research_documents(repo_id,sha,text,url,captured) VALUES(1,?,?,?,?)",
                      (label, "Robot version " + label, "https://github.com/owner/project1", when.isoformat()))
        store.execute("INSERT INTO snapshots VALUES(1,?,?)", (when.date().isoformat(), 150))
    scope = snapshot(store, NOW, [1], days=30)
    assert {row["sha"] for row in scope["records"]} == {"sha-1", "retained"}
    assert [row["day"] for row in scope["observations"]] == [(NOW - timedelta(days=2)).date().isoformat(), NOW.date().isoformat()]
    timeline = organize(scope, retrieve(scope, "机器人感知")["sources"])["timeline"]
    assert [row["change_since_previous"] for row in timeline] == [None, -50]


def test_current_content_without_sha_is_not_repeated_as_an_archive(store):
    put(store)
    store.cache_readme(1, "Robot without API SHA", "", "https://github.com/owner/project1", NOW.isoformat())
    records = snapshot(store, NOW, [1])["records"]
    assert sum("Robot without API SHA" in row["body"] for row in records) == 1


def test_snapshot_global_document_and_metadata_caps_are_explicit(store):
    for number in range(1, 21):
        put(store, number, "robot " * 4000, description="robot description " * 5000)
    store.execute("INSERT INTO research_documents(repo_id,sha,text,url,captured) VALUES(1,'old',?,?,?)",
                  ("robot old " * 4000, "https://github.com/owner/project1", (NOW - timedelta(days=1)).isoformat()))
    scope = snapshot(store, NOW)
    assert scope["truncated"] and sum(len(row["body"]) for row in scope["records"]) <= 240000
    assert all(row["truncated"] and row["body"] for row in scope["records"])
    assert len(scope["records"]) < 20
    assert "robot description" in scope["records"][0]["body"]
    assert max(len(row["body"]) for row in scope["records"]) <= 19501


def test_long_archived_readme_exposes_its_per_source_truncation(store):
    put(store)
    store.execute("INSERT INTO research_documents(repo_id,sha,text,url,captured) VALUES(1,'old',?,?,?)",
                  ("robot " * 4000, "https://github.com/owner/project1", (NOW - timedelta(days=1)).isoformat()))
    scope = snapshot(store, NOW, [1])
    archived = next(row for row in scope["records"] if row["kind"] == "readme_version")
    assert archived["truncated"] and len(archived["body"]) == 16000 and scope["truncated"]


def test_short_retrieval_excerpt_marks_an_otherwise_complete_frozen_readme(store):
    put(store, text="Robot perception and toolkit. " * 150)
    scope = snapshot(store, NOW, [1])
    assert not scope["truncated"]
    found = retrieve(scope, "机器人感知")
    assert found["truncated"] and found["sources"][0]["truncated"]
    assert len(found["sources"][0]["text"]) == 2400


def test_preferences_feedback_and_short_english_terms_never_create_irrelevant_matches(store):
    put(store, text="A world atlas with no relevant topic", description="world atlas", topics=["cartography"])
    scope = snapshot(store, NOW)
    assert not retrieve(scope, "rl")["sources"]
    assert "强化学习" not in terms_for("world atlas")
    assert not retrieve(scope, "量子纠错拓扑编码", preferences={"interests": ["world"]}, weights={"world": 100000})["sources"]
    assert not organize(scope, [{"label": "R1", "repo_id": 1, "name": "atlas", "text": "world atlas"}])["topics"]


def test_related_keywords_match_and_duplicate_detection_preserves_numbers(store):
    put(store)
    scope = snapshot(store, NOW, [1])
    assert retrieve(scope, "机器人感知")["sources"][0]["label"] == "R1"
    text = "Robot inference requires 16 GB memory. " * 4
    sources = [{"label": label, "repo_id": 1, "name": "owner/project1", "text": body}
               for label, body in [("R1", text), ("H2", text.upper()), ("H3", text.replace("16", "24"))]]
    assert organize(scope, sources)["duplicates"] == [["R1", "H2"]]


@pytest.mark.parametrize("value", ["javascript:alert(1)", "http://github.com/a/b", "https://github.com.evil/a/b",
                                   "https://evil@github.com/a/b", "https://github.com:443/a/b", "https://github.com/a/b\\@evil",
                                   "https://github.com/a/b\n", "https://github.com/login?return_to=evil", "https://github.com/a/..", None])
def test_source_urls_allow_only_unambiguous_github_repository_links(value):
    assert not safe_url(value)


def test_source_url_retains_readme_version_path():
    value = "https://github.com/owner/repo/blob/main/README.md#installation"
    assert safe_url(value) == value


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)


def png_parts(*, width=1, height=1, pixels=b"\x00\x10\x20\x30", depth=8, color=2, interlace=0):
    return [b"\x89PNG\r\n\x1a\n", chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace)),
            chunk(b"IDAT", zlib.compress(pixels)), chunk(b"IEND", b"")]


def test_static_png_fingerprint_labels_and_minimal_payload(tmp_path):
    selected = tmp_path / "selected.png"
    selected.write_bytes(b"".join(png_parts()))
    attachment = png_attachment(selected)
    assert attachment["label"] == "I" + attachment["fingerprint"][:16]
    assert attachment["data_url"].startswith("data:image/png;base64,")
    assert str(tmp_path) not in json.dumps(attachment)


@pytest.mark.parametrize("invalid", [
    lambda p: p[:2] + [chunk(b"ABCD", b"")] + p[2:],
    lambda p: p[:2] + [p[1]] + p[2:],
    lambda p: p[:-1],
    lambda p: p + [b"trailing"],
    lambda p: p[:2] + [chunk(b"fcTL", b"animation")] + p[2:],
    lambda p: p[:2] + [chunk(b"IDAT", zlib.compress(b"\x00\x10")), chunk(b"tEXt", b"key\x00value"), chunk(b"IDAT", b"")] + p[-1:],
    lambda p: p[:2] + [chunk(b"IDAT", zlib.compress(b"\x00" * 1000000))] + p[-1:],
    lambda p: p[:2] + [chunk(b"IDAT", zlib.compress(b"\x05\x10\x20\x30"))] + p[-1:],
    lambda p: p[:2] + [chunk(b"IDAT", zlib.compress(b"\x00\x10\x20\x30") + b"trailing")] + p[-1:],
])
def test_png_rejects_invalid_structure_or_bounded_decompression(tmp_path, invalid):
    selected = tmp_path / "invalid.png"
    selected.write_bytes(b"".join(invalid(png_parts())))
    with pytest.raises(ValueError):
        png_attachment(selected)


@pytest.mark.parametrize("settings", [{"width": 4097}, {"width": 4096, "height": 4096}, {"color": 3}, {"depth": 16}, {"interlace": 1}])
def test_png_rejects_unsupported_dimensions_and_encodings_before_decompression(tmp_path, settings):
    selected = tmp_path / "unsupported.png"
    selected.write_bytes(b"".join(png_parts(**settings)))
    with pytest.raises(ValueError):
        png_attachment(selected)
