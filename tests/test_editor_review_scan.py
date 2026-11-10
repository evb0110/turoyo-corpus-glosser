"""Project-wide review passes must not re-parse every saved document.

On the hosted shelf (58 documents, 369 MB of session JSON) every "проверено"
click re-read the whole shelf twice to recompute `totals`, taking ~15 s and
most of the server's memory. These tests pin the observable cost: which
session files a request parses.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from maalula_glosser.editor import store as store_module
from maalula_glosser.editor.app import REVIEW_RATE_RUB_PER_WORD, create_app


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("GLOSSER_PROFILE", "flex")
    monkeypatch.setenv("MAALULA_STATE_DIR", str(tmp_path / "state"))
    return TestClient(create_app(Path("."), warm=False))


def _create(client: TestClient, title: str, text: str) -> tuple[str, str]:
    created = client.post("/api/documents",
                          json={"title": title, "text": text, "translation": ""})
    assert created.status_code == 200
    did = created.json()["document_id"]
    sentence_id = client.get(f"/api/documents/{did}").json()["sentences"][0]["sentence_id"]
    return did, sentence_id


def _claim(client: TestClient, did: str, client_id: str) -> None:
    claimed = client.post(f"/api/documents/{did}/lock/claim",
                          json={"client_id": client_id, "name": "test"})
    assert claimed.status_code == 200


def _review(client: TestClient, did: str, sentence_id: str, client_id: str,
            reviewed: bool, name: str = "Reviewer") -> dict:
    response = client.post(
        f"/api/documents/{did}/sentences/{sentence_id}/review",
        json={"reviewed": reviewed, "name": name},
        headers={"x-editor-client": client_id},
    )
    assert response.status_code == 200
    return response.json()


def _count_session_reads(monkeypatch) -> list[str]:
    reads: list[str] = []
    original = store_module.read_json

    def counting(path, default=None):
        reads.append(Path(path).stem)
        return original(path, default)

    monkeypatch.setattr(store_module, "read_json", counting)
    return reads


def test_review_click_parses_only_the_changed_document(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    edited, edited_sentence = _create(client, "Edited", "latwa latwa")
    untouched, untouched_sentence = _create(client, "Untouched", "latwa")
    _claim(client, edited, "a")
    _claim(client, untouched, "b")

    # the state volume is seeded with the checkout's bundled sessions, whose
    # existing reviews are part of the totals
    first = _review(client, untouched, untouched_sentence, "b", True, "Other")
    baseline = first["totals"]
    assert baseline["Other"] == 1 * REVIEW_RATE_RUB_PER_WORD
    assert "Reviewer" not in baseline

    reads = _count_session_reads(monkeypatch)
    second = _review(client, edited, edited_sentence, "a", True)
    assert set(reads) == {edited}
    assert second["totals"] == {**baseline, "Reviewer": 2 * REVIEW_RATE_RUB_PER_WORD}

    cleared = _review(client, edited, edited_sentence, "a", False)
    assert cleared["totals"] == baseline


def test_document_list_and_statistics_follow_saves(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    did, sentence_id = _create(client, "Text", "latwa latwa")
    _claim(client, did, "a")
    assert client.get("/").status_code == 200
    assert client.get("/stats").status_code == 200

    reads = _count_session_reads(monkeypatch)
    assert client.get("/").status_code == 200
    assert client.get("/stats").status_code == 200
    assert reads == []

    _review(client, did, sentence_id, "a", True, "Проверяющая")
    page = client.get("/stats")
    assert page.status_code == 200
    assert "Проверяющая" in page.text


def test_lock_poll_does_not_parse_the_document(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    did, _sentence_id = _create(client, "Text", "latwa")

    reads = _count_session_reads(monkeypatch)
    polled = client.get(f"/api/documents/{did}/lock", params={"client_id": "x"})
    assert polled.status_code == 200
    assert reads == []

    missing = client.get("/api/documents/edoc_missing/lock", params={"client_id": "x"})
    assert missing.status_code == 404
