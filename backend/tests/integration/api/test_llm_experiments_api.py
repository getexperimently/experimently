"""
Integration tests for EP-046 LLM Experiment API.

Tests the full HTTP request/response cycle for:
  POST   /api/v1/llm-experiments/
  GET    /api/v1/llm-experiments/
  GET    /api/v1/llm-experiments/{id}
  PUT    /api/v1/llm-experiments/{id}
  POST   /api/v1/llm-experiments/{id}/start
  POST   /api/v1/llm-experiments/{id}/pause
  POST   /api/v1/llm-experiments/{id}/variants
  PUT    /api/v1/llm-experiments/{id}/variants/{variant_id}
  POST   /api/v1/llm-experiments/{id}/complete  (mocked LLM provider)
  POST   /api/v1/llm-experiments/{id}/evaluate
  GET    /api/v1/llm-experiments/{id}/results
  POST   /api/v1/llm-experiments/{id}/judge     (mocked)

All real LLM API calls are mocked to prevent network I/O.

NOTE: Tests that exercise two different roles in one test use `_make_client`
      to construct fresh TestClient instances (rather than the conftest
      fixtures) so that `app.dependency_overrides` is not reset between the
      two role-specific requests.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api import deps
from backend.app.api.deps import CacheControl
from backend.app.main import app


# ---------------------------------------------------------------------------
# Helper: create a TestClient authenticated as a given user
# ---------------------------------------------------------------------------

def _make_client(db_session: Session, user) -> TestClient:
    """Create a TestClient authenticated as *user* without clearing overrides."""
    _engine = db_session.get_bind()
    _SessionFactory = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

    def override_get_db():
        session = _SessionFactory()
        session.execute(text("SET search_path TO test_experimentation"))
        try:
            yield session
        finally:
            try:
                session.close()
            except Exception:
                pass

    async def override_get_current_user():
        return user

    def override_get_current_active_user():
        return user

    def override_get_current_superuser():
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return user

    async def override_get_cache_control():
        return CacheControl(enabled=False, skip=True)

    def override_get_api_key():
        return user

    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user] = override_get_current_user
    app.dependency_overrides[deps.get_current_active_user] = override_get_current_active_user
    app.dependency_overrides[deps.get_current_superuser] = override_get_current_superuser
    app.dependency_overrides[deps.get_cache_control] = override_get_cache_control
    app.dependency_overrides[deps.get_api_key] = override_get_api_key
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test payload helpers
# ---------------------------------------------------------------------------

def _base_payload(name: str = "Test LLM Exp") -> dict:
    return {
        "name": name,
        "description": "Integration test experiment",
        "task_type": "chat_completion",
        "evaluation_metric": "business_metric",
        "variants": [
            {
                "name": "control",
                "is_control": True,
                "traffic_split": 0.5,
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "system_prompt": "You are helpful.",
                "prompt_template": "Answer: {{question}}",
                "temperature": 0.7,
                "max_tokens": 500,
            },
            {
                "name": "treatment",
                "is_control": False,
                "traffic_split": 0.5,
                "provider": "openai",
                "model_name": "gpt-4o",
                "system_prompt": "Be concise.",
                "prompt_template": "Short answer: {{question}}",
                "temperature": 0.3,
                "max_tokens": 200,
            },
        ],
    }


# ---------------------------------------------------------------------------
# CRUD Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_db
class TestCreateLLMExperiment:

    def test_admin_can_create_experiment(self, admin_client: TestClient):
        payload = _base_payload("Admin Creates LLM Exp")
        response = admin_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["name"] == "Admin Creates LLM Exp"
        assert data["status"] == "DRAFT"
        assert data["task_type"] == "chat_completion"
        assert data["evaluation_metric"] == "business_metric"
        assert len(data["variants"]) == 2
        uuid.UUID(data["id"])  # Valid UUID

    def test_developer_can_create_experiment(self, developer_client: TestClient):
        payload = _base_payload("Developer Creates LLM Exp")
        response = developer_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 201, response.text

    def test_viewer_cannot_create_experiment(self, viewer_client: TestClient):
        payload = _base_payload("Viewer Tries to Create")
        response = viewer_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 403

    def test_analyst_cannot_create_experiment(self, analyst_client: TestClient):
        payload = _base_payload("Analyst Tries to Create")
        response = analyst_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 403

    def test_invalid_task_type_returns_422(self, admin_client: TestClient):
        payload = _base_payload()
        payload["task_type"] = "bad_type"
        response = admin_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 422

    def test_missing_control_variant_returns_422(self, admin_client: TestClient):
        payload = _base_payload()
        for v in payload["variants"]:
            v["is_control"] = False
        response = admin_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 422

    def test_traffic_split_not_summing_to_one_returns_422(self, admin_client: TestClient):
        payload = _base_payload()
        payload["variants"][0]["traffic_split"] = 0.3
        payload["variants"][1]["traffic_split"] = 0.3
        response = admin_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 422

    def test_single_variant_returns_422(self, admin_client: TestClient):
        payload = _base_payload()
        payload["variants"] = [payload["variants"][0]]
        payload["variants"][0]["traffic_split"] = 1.0
        response = admin_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 422

    def test_created_experiment_has_id(self, admin_client: TestClient):
        payload = _base_payload("ID Check")
        response = admin_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 201
        assert "id" in response.json()

    def test_created_experiment_has_created_at(self, admin_client: TestClient):
        payload = _base_payload("Timestamps Check")
        response = admin_client.post("/api/v1/llm-experiments/", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert "created_at" in data
        assert "updated_at" in data


@pytest.mark.integration
@pytest.mark.requires_db
class TestGetLLMExperiment:

    def test_get_existing_experiment(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Get Test"))
        assert create_resp.status_code == 201
        exp_id = create_resp.json()["id"]

        get_resp = admin_client.get(f"/api/v1/llm-experiments/{exp_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == exp_id

    def test_get_nonexistent_experiment_returns_404(self, admin_client: TestClient):
        fake_id = str(uuid.uuid4())
        response = admin_client.get(f"/api/v1/llm-experiments/{fake_id}")
        assert response.status_code == 404

    def test_viewer_can_get_experiment(self, db_session, admin_user, viewer_user):
        admin_c = _make_client(db_session, admin_user)
        create_resp = admin_c.post("/api/v1/llm-experiments/", json=_base_payload("Viewer Read"))
        assert create_resp.status_code == 201, create_resp.text
        exp_id = create_resp.json()["id"]

        viewer_c = _make_client(db_session, viewer_user)
        response = viewer_c.get(f"/api/v1/llm-experiments/{exp_id}")
        app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_experiment_includes_variants(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("With Variants"))
        exp_id = create_resp.json()["id"]
        get_resp = admin_client.get(f"/api/v1/llm-experiments/{exp_id}")
        data = get_resp.json()
        assert len(data["variants"]) == 2


@pytest.mark.integration
@pytest.mark.requires_db
class TestListLLMExperiments:

    def test_list_returns_created_experiments(self, admin_client: TestClient):
        for i in range(3):
            admin_client.post("/api/v1/llm-experiments/", json=_base_payload(f"List Test {i}"))
        response = admin_client.get("/api/v1/llm-experiments/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 3

    def test_viewer_can_list(self, db_session, admin_user, viewer_user):
        admin_c = _make_client(db_session, admin_user)
        admin_c.post("/api/v1/llm-experiments/", json=_base_payload("For List"))

        viewer_c = _make_client(db_session, viewer_user)
        response = viewer_c.get("/api/v1/llm-experiments/")
        app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_filter_by_status(self, admin_client: TestClient):
        response = admin_client.get("/api/v1/llm-experiments/?status=DRAFT")
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["status"] == "DRAFT"


@pytest.mark.integration
@pytest.mark.requires_db
class TestUpdateLLMExperiment:

    def test_admin_can_update_name(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Original"))
        exp_id = create_resp.json()["id"]
        update_resp = admin_client.put(
            f"/api/v1/llm-experiments/{exp_id}",
            json={"name": "Updated Name"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Updated Name"

    def test_viewer_cannot_update(self, db_session, admin_user, viewer_user):
        admin_c = _make_client(db_session, admin_user)
        create_resp = admin_c.post("/api/v1/llm-experiments/", json=_base_payload("Viewer Update Test"))
        assert create_resp.status_code == 201, create_resp.text
        exp_id = create_resp.json()["id"]

        viewer_c = _make_client(db_session, viewer_user)
        response = viewer_c.put(f"/api/v1/llm-experiments/{exp_id}", json={"name": "Hacked"})
        app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_update_nonexistent_returns_404(self, admin_client: TestClient):
        response = admin_client.put(
            f"/api/v1/llm-experiments/{uuid.uuid4()}", json={"name": "X"}
        )
        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.requires_db
class TestStartPauseLLMExperiment:

    def test_start_draft_experiment(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Start Test"))
        exp_id = create_resp.json()["id"]
        start_resp = admin_client.post(f"/api/v1/llm-experiments/{exp_id}/start")
        assert start_resp.status_code == 200
        assert start_resp.json()["status"] == "ACTIVE"

    def test_pause_active_experiment(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Pause Test"))
        exp_id = create_resp.json()["id"]
        admin_client.post(f"/api/v1/llm-experiments/{exp_id}/start")
        pause_resp = admin_client.post(f"/api/v1/llm-experiments/{exp_id}/pause")
        assert pause_resp.status_code == 200
        assert pause_resp.json()["status"] == "PAUSED"

    def test_start_nonexistent_returns_404(self, admin_client: TestClient):
        response = admin_client.post(f"/api/v1/llm-experiments/{uuid.uuid4()}/start")
        assert response.status_code == 404

    def test_pause_nonexistent_returns_404(self, admin_client: TestClient):
        response = admin_client.post(f"/api/v1/llm-experiments/{uuid.uuid4()}/pause")
        assert response.status_code == 404

    def test_pause_draft_returns_400(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Pause Draft"))
        exp_id = create_resp.json()["id"]
        response = admin_client.post(f"/api/v1/llm-experiments/{exp_id}/pause")
        assert response.status_code == 400

    def test_viewer_cannot_start(self, db_session, admin_user, viewer_user):
        admin_c = _make_client(db_session, admin_user)
        create_resp = admin_c.post("/api/v1/llm-experiments/", json=_base_payload("Viewer Start"))
        assert create_resp.status_code == 201, create_resp.text
        exp_id = create_resp.json()["id"]

        viewer_c = _make_client(db_session, viewer_user)
        response = viewer_c.post(f"/api/v1/llm-experiments/{exp_id}/start")
        app.dependency_overrides.clear()
        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.requires_db
class TestLLMVariantCRUD:

    def test_add_variant_to_experiment(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Variant Add Test"))
        exp_id = create_resp.json()["id"]
        new_variant = {
            "name": "treatment_2",
            "is_control": False,
            "traffic_split": 0.3,
            "provider": "google",
            "model_name": "gemini-1.5-flash",
            "system_prompt": "",
            "prompt_template": "Brief: {{question}}",
            "temperature": 0.5,
            "max_tokens": 100,
        }
        response = admin_client.post(f"/api/v1/llm-experiments/{exp_id}/variants", json=new_variant)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "treatment_2"
        assert data["provider"] == "google"

    def test_update_variant(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Variant Update Test"))
        exp_id = create_resp.json()["id"]
        variant_id = create_resp.json()["variants"][0]["id"]
        update_resp = admin_client.put(
            f"/api/v1/llm-experiments/{exp_id}/variants/{variant_id}",
            json={"name": "control_v2", "temperature": 0.1},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "control_v2"
        assert update_resp.json()["temperature"] == pytest.approx(0.1)

    def test_update_nonexistent_variant_returns_404(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Variant 404"))
        exp_id = create_resp.json()["id"]
        response = admin_client.put(
            f"/api/v1/llm-experiments/{exp_id}/variants/{uuid.uuid4()}",
            json={"name": "x"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Completion tests (mocked LLM provider)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_db
class TestLLMComplete:

    def _create_active_experiment(self, client: TestClient, name: str) -> str:
        create_resp = client.post("/api/v1/llm-experiments/", json=_base_payload(name))
        exp_id = create_resp.json()["id"]
        client.post(f"/api/v1/llm-experiments/{exp_id}/start")
        return exp_id

    def test_complete_returns_response(self, admin_client: TestClient):
        exp_id = self._create_active_experiment(admin_client, "Complete Test")
        mock_eval = MagicMock()
        mock_eval.id = uuid.uuid4()
        mock_eval.variant_id = uuid.uuid4()
        mock_eval.model_response = "Paris"
        mock_eval.latency_ms = 123
        mock_eval.estimated_cost_usd = 0.001
        mock_eval.input_tokens = 10
        mock_eval.output_tokens = 5

        mock_variant = MagicMock()
        mock_variant.id = mock_eval.variant_id
        mock_variant.name = "control"
        mock_variant.provider = MagicMock()
        mock_variant.provider.value = "anthropic"
        mock_variant.model_name = "claude-3-5-sonnet-20241022"

        with patch(
            "backend.app.api.v1.endpoints.llm_proxy._proxy_service.complete",
            new=AsyncMock(return_value=mock_eval),
        ):
            with patch(
                "backend.app.api.v1.endpoints.llm_proxy._experiment_service.get_variant",
                return_value=mock_variant,
            ):
                response = admin_client.post(
                    f"/api/v1/llm-experiments/{exp_id}/complete",
                    json={"user_id": "user-1", "input_variables": {"question": "What is the capital?"}},
                )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["response"] == "Paris"
        assert data["latency_ms"] == 123
        assert "evaluation_id" in data

    def test_complete_inactive_experiment_returns_400(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Inactive Complete"))
        exp_id = create_resp.json()["id"]
        # Don't start the experiment — it stays DRAFT
        response = admin_client.post(
            f"/api/v1/llm-experiments/{exp_id}/complete",
            json={"user_id": "user-1", "input_variables": {}},
        )
        assert response.status_code == 400

    def test_complete_nonexistent_experiment_returns_404(self, admin_client: TestClient):
        response = admin_client.post(
            f"/api/v1/llm-experiments/{uuid.uuid4()}/complete",
            json={"user_id": "user-1", "input_variables": {}},
        )
        assert response.status_code == 404

    def test_viewer_can_call_complete(self, db_session, admin_user, viewer_user):
        """READ permission allows viewers to submit completions."""
        admin_c = _make_client(db_session, admin_user)
        exp_id = self._create_active_experiment(admin_c, "Viewer Complete")

        mock_eval = MagicMock()
        mock_eval.id = uuid.uuid4()
        mock_eval.variant_id = uuid.uuid4()
        mock_eval.model_response = "Ok"
        mock_eval.latency_ms = 50
        mock_eval.estimated_cost_usd = 0.0
        mock_eval.input_tokens = 5
        mock_eval.output_tokens = 3

        mock_variant = MagicMock()
        mock_variant.id = mock_eval.variant_id
        mock_variant.name = "control"
        mock_variant.provider = MagicMock()
        mock_variant.provider.value = "anthropic"
        mock_variant.model_name = "claude-3-5-sonnet-20241022"

        viewer_c = _make_client(db_session, viewer_user)
        with patch(
            "backend.app.api.v1.endpoints.llm_proxy._proxy_service.complete",
            new=AsyncMock(return_value=mock_eval),
        ):
            with patch(
                "backend.app.api.v1.endpoints.llm_proxy._experiment_service.get_variant",
                return_value=mock_variant,
            ):
                response = viewer_c.post(
                    f"/api/v1/llm-experiments/{exp_id}/complete",
                    json={"user_id": "viewer-user", "input_variables": {}},
                )
        app.dependency_overrides.clear()
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Evaluation / rating tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_db
class TestSubmitEvaluation:

    def test_submit_human_rating(self, admin_client: TestClient, db_session: Session):
        from backend.app.models.llm_experiment import LLMEvaluation

        # Create a real experiment
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Rating Test"))
        exp_id = uuid.UUID(create_resp.json()["id"])
        variant_id = uuid.UUID(create_resp.json()["variants"][0]["id"])

        # Directly insert an evaluation
        ev = LLMEvaluation(
            llm_experiment_id=exp_id,
            variant_id=variant_id,
            user_id="test-user",
            input_variables={},
            rendered_prompt="Hello",
            model_response="Hi",
            latency_ms=100,
            input_tokens=5,
            output_tokens=5,
            estimated_cost_usd=0.001,
        )
        db_session.add(ev)
        db_session.commit()
        db_session.refresh(ev)
        ev_id = str(ev.id)

        response = admin_client.post(
            f"/api/v1/llm-experiments/{exp_id}/evaluate",
            json={"evaluation_id": ev_id, "human_rating": 4.5},
        )
        assert response.status_code == 200, response.text
        assert response.json()["human_rating"] == 4.5

    def test_submit_business_metric(self, admin_client: TestClient, db_session: Session):
        from backend.app.models.llm_experiment import LLMEvaluation

        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("BM Test"))
        exp_id = uuid.UUID(create_resp.json()["id"])
        variant_id = uuid.UUID(create_resp.json()["variants"][0]["id"])

        ev = LLMEvaluation(
            llm_experiment_id=exp_id,
            variant_id=variant_id,
            user_id="bm-user",
            input_variables={},
            rendered_prompt="Q",
            model_response="A",
            latency_ms=50,
            input_tokens=3,
            output_tokens=3,
            estimated_cost_usd=0.0,
        )
        db_session.add(ev)
        db_session.commit()
        db_session.refresh(ev)

        response = admin_client.post(
            f"/api/v1/llm-experiments/{exp_id}/evaluate",
            json={"evaluation_id": str(ev.id), "business_metric_value": 1.0},
        )
        assert response.status_code == 200
        assert response.json()["business_metric_value"] == 1.0

    def test_submit_nonexistent_evaluation_returns_404(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Eval 404"))
        exp_id = create_resp.json()["id"]
        response = admin_client.post(
            f"/api/v1/llm-experiments/{exp_id}/evaluate",
            json={"evaluation_id": str(uuid.uuid4()), "human_rating": 3.0},
        )
        assert response.status_code == 404

    def test_viewer_cannot_submit_evaluation(self, db_session, admin_user, viewer_user):
        from backend.app.models.llm_experiment import LLMEvaluation

        admin_c = _make_client(db_session, admin_user)
        create_resp = admin_c.post("/api/v1/llm-experiments/", json=_base_payload("Viewer Eval"))
        assert create_resp.status_code == 201, create_resp.text
        exp_id = uuid.UUID(create_resp.json()["id"])
        variant_id = uuid.UUID(create_resp.json()["variants"][0]["id"])

        ev = LLMEvaluation(
            llm_experiment_id=exp_id,
            variant_id=variant_id,
            user_id="u",
            input_variables={},
            rendered_prompt="Q",
            model_response="A",
            latency_ms=10,
            input_tokens=1,
            output_tokens=1,
            estimated_cost_usd=0.0,
        )
        db_session.add(ev)
        db_session.commit()
        db_session.refresh(ev)

        viewer_c = _make_client(db_session, viewer_user)
        response = viewer_c.post(
            f"/api/v1/llm-experiments/{exp_id}/evaluate",
            json={"evaluation_id": str(ev.id), "human_rating": 5.0},
        )
        app.dependency_overrides.clear()
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Results tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_db
class TestGetResults:

    def test_results_empty_experiment(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Results Empty"))
        exp_id = create_resp.json()["id"]
        response = admin_client.get(f"/api/v1/llm-experiments/{exp_id}/results")
        assert response.status_code == 200
        data = response.json()
        assert data["total_evaluations"] == 0
        assert len(data["variant_stats"]) == 2

    def test_results_nonexistent_returns_404(self, admin_client: TestClient):
        response = admin_client.get(f"/api/v1/llm-experiments/{uuid.uuid4()}/results")
        assert response.status_code == 404

    def test_viewer_can_get_results(self, db_session, admin_user, viewer_user):
        admin_c = _make_client(db_session, admin_user)
        create_resp = admin_c.post("/api/v1/llm-experiments/", json=_base_payload("Viewer Results"))
        assert create_resp.status_code == 201, create_resp.text
        exp_id = create_resp.json()["id"]

        viewer_c = _make_client(db_session, viewer_user)
        response = viewer_c.get(f"/api/v1/llm-experiments/{exp_id}/results")
        app.dependency_overrides.clear()
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Judge tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_db
class TestJudgeEndpoint:

    def test_judge_endpoint_returns_list(self, admin_client: TestClient):
        create_resp = admin_client.post("/api/v1/llm-experiments/", json=_base_payload("Judge Test"))
        exp_id = create_resp.json()["id"]

        # No evaluations — should return empty list
        with patch(
            "backend.app.services.llm_analytics_service.LLMEvaluationAnalyticsService.run_llm_as_judge",
            new=AsyncMock(return_value=[]),
        ):
            response = admin_client.post(
                f"/api/v1/llm-experiments/{exp_id}/judge",
                json={"criteria": "helpfulness", "judge_model": "claude-3-5-sonnet-20241022"},
            )
        assert response.status_code == 200
        assert response.json() == []

    def test_judge_nonexistent_experiment_returns_404(self, admin_client: TestClient):
        response = admin_client.post(
            f"/api/v1/llm-experiments/{uuid.uuid4()}/judge",
            json={"criteria": "accuracy"},
        )
        assert response.status_code == 404

    def test_viewer_cannot_run_judge(self, db_session, admin_user, viewer_user):
        admin_c = _make_client(db_session, admin_user)
        create_resp = admin_c.post("/api/v1/llm-experiments/", json=_base_payload("Judge Auth"))
        assert create_resp.status_code == 201, create_resp.text
        exp_id = create_resp.json()["id"]

        viewer_c = _make_client(db_session, viewer_user)
        response = viewer_c.post(
            f"/api/v1/llm-experiments/{exp_id}/judge",
            json={"criteria": "helpfulness"},
        )
        app.dependency_overrides.clear()
        assert response.status_code == 403
