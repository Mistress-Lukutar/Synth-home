"""Tests for the graph execution engine and panel runtime API."""

import pytest


@pytest.fixture
def sample_panel_with_graph(client):
    """Create a panel with a simple graph: switch -> device_on."""
    # Create panel
    r = client.post("/api/panels", json={"name": "Test Exec Panel"})
    panel_id = r.json()["id"]
    # Save graph
    graph = {
        "nodes": [
            {"id": "sw1", "type": "panel_switch_input", "pos": {"x": 0, "y": 0}, "data": {"label": "Light Switch"}},
            {"id": "dev1", "type": "device_picker", "pos": {"x": 200, "y": 0}, "data": {"ieee": "0x0011223344556677", "_device_name": "Test Bulb"}},
            {"id": "cmd1", "type": "device_set_on_off", "pos": {"x": 400, "y": 0}, "data": {}},
        ],
        "connections": [
            {"id": "c1", "from": {"node": "sw1", "output": "value"}, "to": {"node": "cmd1", "input": "state"}},
            {"id": "c2", "from": {"node": "dev1", "output": "device"}, "to": {"node": "cmd1", "input": "device"}},
        ],
    }
    client.put(f"/api/graphs/{panel_id}", json=graph)
    return panel_id


def test_panel_input_runs_graph(client, sample_panel_with_graph):
    """Setting a panel input should execute the graph and return execution result."""
    panel_id = sample_panel_with_graph
    response = client.post(
        f"/api/panels/{panel_id}/input",
        json={"node_id": "sw1", "value": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "execution" in data
    # Should have executed 3 nodes (switch, device_picker, device_set_on_off)
    assert data["execution"]["executed_nodes"] == 3


def test_panel_state_reflects_input(client, sample_panel_with_graph):
    """Panel state should store the input value after it is set."""
    panel_id = sample_panel_with_graph
    client.post(f"/api/panels/{panel_id}/input", json={"node_id": "sw1", "value": True})
    response = client.get(f"/api/panels/{panel_id}/state")
    assert response.status_code == 200
    data = response.json()
    assert data["inputs"]["sw1"] is True


def test_primitive_const_bool_execution(client):
    """A graph with only primitive nodes should execute correctly."""
    r = client.post("/api/panels", json={"name": "Primitive Test"})
    panel_id = r.json()["id"]
    graph = {
        "nodes": [
            {"id": "b1", "type": "const_bool", "pos": {"x": 0, "y": 0}, "data": {"value": True}},
            {"id": "b2", "type": "const_bool", "pos": {"x": 0, "y": 0}, "data": {"value": False}},
        ],
        "connections": [],
    }
    client.put(f"/api/graphs/{panel_id}", json=graph)
    response = client.post(f"/api/panels/{panel_id}/input", json={"node_id": "b1", "value": True})
    assert response.status_code == 200
    assert response.json()["execution"]["executed_nodes"] == 2


def test_unknown_node_type_skipped_gracefully(client):
    """Unknown node types should be skipped without crashing the graph."""
    r = client.post("/api/panels", json={"name": "Unknown Node Test"})
    panel_id = r.json()["id"]
    graph = {
        "nodes": [
            {"id": "known", "type": "const_int", "pos": {"x": 0, "y": 0}, "data": {"value": 42}},
            {"id": "unknown", "type": "custom_xyz", "pos": {"x": 0, "y": 0}, "data": {}},
        ],
        "connections": [],
    }
    client.put(f"/api/graphs/{panel_id}", json=graph)
    response = client.post(f"/api/panels/{panel_id}/input", json={"node_id": "known", "value": 0})
    assert response.status_code == 200
    # Only const_int executed, custom_xyz skipped
    assert response.json()["execution"]["executed_nodes"] == 1


def test_panel_input_not_found(client):
    response = client.post("/api/panels/99999/input", json={"node_id": "x", "value": 1})
    assert response.status_code == 404
