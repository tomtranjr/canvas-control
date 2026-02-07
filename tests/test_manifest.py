from __future__ import annotations

from canvasctl.manifest import index_items_by_file_id, load_manifest, write_manifest


def test_write_and_load_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    payload = {"items": [{"file_id": 1, "status": "downloaded"}]}

    write_manifest(path, payload)
    loaded = load_manifest(path)

    assert loaded == payload


def test_index_items_by_file_id():
    payload = {
        "items": [
            {"file_id": 1, "status": "downloaded"},
            {"file_id": None, "status": "unresolved"},
            {"file_id": 2, "status": "failed"},
        ]
    }

    indexed = index_items_by_file_id(payload)

    assert set(indexed.keys()) == {1, 2}
