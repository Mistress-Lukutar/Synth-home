"""Tests for the node registry router."""


def test_list_registry(client):
    response = client.get("/api/nodes/registry")
    assert response.status_code == 200
    data = response.json()
    # Should be grouped by category
    assert isinstance(data, dict)
    # Check known categories exist
    assert "primitive" in data
    assert "device" in data
    assert "panel" in data
    # Check a known node type
    primitives = data["primitive"]
    assert any(p["type"] == "const_bool" for p in primitives)
    assert any(p["type"] == "const_color" for p in primitives)
    # Check structure
    node = primitives[0]
    assert "type" in node
    assert "label" in node
    assert "inputs" in node
    assert "outputs" in node
    assert "config_fields" in node


def test_registry_includes_device_nodes(client):
    response = client.get("/api/nodes/registry")
    data = response.json()
    device_nodes = data.get("device", [])
    assert any(n["type"] == "device_picker" for n in device_nodes)
    assert any(n["type"] == "device_set_on_off" for n in device_nodes)


def test_registry_includes_panel_nodes(client):
    response = client.get("/api/nodes/registry")
    data = response.json()
    panel_nodes = data.get("panel", [])
    assert any(n["type"] == "panel_switch_input" for n in panel_nodes)
    assert any(n["type"] == "panel_int_output" for n in panel_nodes)
