import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_accepts_project_database_variable_names() -> None:
    settings = Settings(
        _env_file=None,
        MONGODB_URL="mongodb://remote.example/volta",
        POSTGRES_URL="postgresql://remote.example/volta",
        JWT_KEY="secret",
    )

    assert settings.mongodb_url == "mongodb://remote.example/volta"
    assert settings.postgres_url == "postgresql://remote.example/volta"
    assert settings.jwt_key is not None


@pytest.mark.parametrize("environment", ["qa", "prod"])
def test_settings_accepts_deployment_environments(environment: str) -> None:
    assert Settings(_env_file=None, environment=environment).environment == environment


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_settings_rejects_legacy_environments(environment: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment=environment)
