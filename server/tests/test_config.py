import pytest
from pydantic import ValidationError

from app.config import DEFAULT_SECRET, Settings


def test_default_secret_allowed_in_development():
    settings = Settings(environment="development", secret_key=DEFAULT_SECRET)
    assert settings.secret_key == DEFAULT_SECRET


def test_default_secret_rejected_outside_development():
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key=DEFAULT_SECRET)


def test_real_secret_accepted_in_production():
    settings = Settings(environment="production", secret_key="a-real-generated-secret-value")
    assert settings.secret_key == "a-real-generated-secret-value"
