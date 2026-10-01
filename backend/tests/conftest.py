"""Pytest fixtures dùng chung cho toàn bộ test suite backend."""
import pytest
from fastapi.testclient import TestClient
from src.api.main import app


@pytest.fixture
def client():
    """Tạo TestClient cho FastAPI app."""
    with TestClient(app) as c:
        yield c
