"""Tests for the panels and graphs routers."""

import pytest


@pytest.fixture
def sample_panel(client):
    """Create a sample panel and return its id."""
    payload = {
        "name": "Test Panel",
        "is_enabled": True,
        "sort_order": 0,
        "layout": {"x": 0, "y": 0, "w": 1, "h": 1},
    }
    response = client.post("/api/panels", json=payload)
    assert response.status_code == 200
    data = response.json()
    return data["id"]


def test_create_panel(client):
    payload = {
        "name": "Living Room",
        "is_enabled": True,
        "sort_order": 1,
    }
    response = client.post("/api/panels", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Living Room"
    assert data["is_enabled"] is True
    assert "id" in data
    assert "created_at" in data


def test_list_panels(client, sample_panel):
    response = client.get("/api/panels")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(p["id"] == sample_panel for p in data)


def test_update_panel(client, sample_panel):
    response = client.patch(
        f"/api/panels/{sample_panel}",
        json={"name": "Updated Panel Name"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Panel Name"


def test_update_panel_not_found(client):
    response = client.patch(
        "/api/panels/99999",
        json={"name": "Updated Name"},
    )
    assert response.status_code == 404


def test_delete_panel(client, sample_panel):
    response = client.delete(f"/api/panels/{sample_panel}")
    assert response.status_code == 200
    response = client.get("/api/panels")
    data = response.json()
    assert not any(p["id"] == sample_panel for p in data)


def test_reorder_panels(client):
    r1 = client.post("/api/panels", json={"name": "First Panel", "sort_order": 0})
    first_id = r1.json()["id"]
    r2 = client.post("/api/panels", json={"name": "Second Panel", "sort_order": 1})
    second_id = r2.json()["id"]

    response = client.patch(
        "/api/panels/reorder",
        json=[
            {"id": first_id, "sort_order": 5},
            {"id": second_id, "sort_order": 2},
        ],
    )
    assert response.status_code == 200

    response = client.get("/api/panels")
    data = response.json()
    panel_map = {p["id"]: p["sort_order"] for p in data}
    assert panel_map[first_id] == 5
    assert panel_map[second_id] == 2


def test_get_graph_for_new_panel(client, sample_panel):
    """A newly created panel should have an empty graph."""
    response = client.get(f"/api/graphs/{sample_panel}")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "connections" in data
    assert data["nodes"] == []
    assert data["connections"] == []


def test_save_and_load_graph(client, sample_panel):
    graph = {
        "nodes": [
            {"id": "n1", "type": "panel_switch_input", "pos": {"x": 10, "y": 20}, "data": {"label": "Light"}},
            {"id": "n2", "type": "device_picker", "pos": {"x": 100, "y": 50}, "data": {"ieee": "0xabc"}},
        ],
        "connections": [
            {"id": "c1", "from": {"node": "n1", "output": "value"}, "to": {"node": "n2", "input": "device"}},
        ],
    }
    response = client.put(f"/api/graphs/{sample_panel}", json=graph)
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 2
    assert len(data["connections"]) == 1
    assert data["version"] == 2  # incremented from 1

    # Reload and verify
    response = client.get(f"/api/graphs/{sample_panel}")
    data = response.json()
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["id"] == "n1"
    assert data["nodes"][0]["pos"]["x"] == 10


def test_validate_graph_detects_cycle(client, sample_panel):
    graph = {
        "nodes": [
            {"id": "a", "type": "const_bool", "pos": {"x": 0, "y": 0}, "data": {}},
            {"id": "b", "type": "const_bool", "pos": {"x": 0, "y": 0}, "data": {}},
        ],
        "connections": [
            {"id": "c1", "from": {"node": "a", "output": "x"}, "to": {"node": "b", "input": "x"}},
            {"id": "c2", "from": {"node": "b", "output": "x"}, "to": {"node": "a", "input": "x"}},
        ],
    }
    response = client.post(f"/api/graphs/{sample_panel}/validate", json=graph)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert any("cycle" in e.lower() for e in data["errors"])


def test_validate_graph_valid(client, sample_panel):
    graph = {
        "nodes": [
            {"id": "n1", "type": "const_bool", "pos": {"x": 0, "y": 0}, "data": {}},
            {"id": "n2", "type": "device_picker", "pos": {"x": 0, "y": 0}, "data": {}},
        ],
        "connections": [
            {"id": "c1", "from": {"node": "n1", "output": "val"}, "to": {"node": "n2", "input": "dev"}},
        ],
    }
    response = client.post(f"/api/graphs/{sample_panel}/validate", json=graph)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["errors"] == []


def test_export_panel(client, sample_panel):
    response = client.get(f"/api/panels/{sample_panel}/export")
    assert response.status_code == 200
    data = response.json()
    assert data["_format"] == "zigbeehub_panel"
    assert "panel" in data
    assert data["panel"]["name"] == "Test Panel"
