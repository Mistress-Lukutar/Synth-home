"""Tests for the scenarios router."""

import pytest


@pytest.fixture
def sample_scenario(client):
    """Create a sample scenario and return its id."""
    payload = {
        "name": "Test Scenario",
        "trigger_type": "manual",
        "action_type": "command",
        "action_config": '{"ieee":"00:11:22:33:44:55:66:77","action":"on","params":{}}',
        "is_enabled": True,
    }
    response = client.post("/api/scenarios", json=payload)
    assert response.status_code == 200
    data = response.json()
    return data["id"]


def test_create_scenario(client):
    payload = {
        "name": "Morning Light",
        "trigger_type": "schedule",
        "schedule_days": "mon,tue,wed,thu,fri",
        "schedule_hour": 7,
        "schedule_minute": 30,
        "action_type": "command",
        "action_config": '{"ieee":"00:11:22:33:44:55:66:77","action":"on","params":{}}',
        "is_enabled": True,
    }
    response = client.post("/api/scenarios", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Morning Light"
    assert data["trigger_type"] == "schedule"
    assert data["is_enabled"] is True


def test_list_scenarios(client, sample_scenario):
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(s["id"] == sample_scenario for s in data)


def test_update_scenario(client, sample_scenario):
    response = client.patch(
        f"/api/scenarios/{sample_scenario}",
        json={"name": "Updated Name"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"


def test_update_scenario_not_found(client):
    response = client.patch(
        "/api/scenarios/99999",
        json={"name": "Updated Name"},
    )
    assert response.status_code == 404


def test_delete_scenario(client, sample_scenario):
    response = client.delete(f"/api/scenarios/{sample_scenario}")
    assert response.status_code == 200
    # Verify deletion
    response = client.get("/api/scenarios")
    data = response.json()
    assert not any(s["id"] == sample_scenario for s in data)


def test_trigger_scenario_not_found(client):
    response = client.post("/api/scenarios/99999/trigger")
    assert response.status_code == 404
