import pytest
from fastapi.testclient import TestClient
from main import app
from tests.test_phase4_runtime import MockStreamingAdapter


@pytest.fixture
def client():
    with TestClient(app) as c:
        gateway = app.state.llm_gateway
        mock_adapter = MockStreamingAdapter()
        gateway.register_adapter("mock", mock_adapter)
        gateway.register_adapter("gemini", mock_adapter)
        gateway.register_adapter("openai", mock_adapter)
        gateway.register_adapter("anthropic", mock_adapter)
        gateway.register_adapter("openrouter", mock_adapter)
        yield c
