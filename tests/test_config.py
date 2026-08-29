from app.core.config import Settings


def test_settings_accepts_project_database_variable_names() -> None:
    settings = Settings(
        _env_file=None,
        MONGODB_URL="mongodb://remote.example/volta",
        POSTGRES_URL="postgresql://remote.example/volta",
    )

    assert settings.mongodb_url == "mongodb://remote.example/volta"
    assert settings.postgres_url == "postgresql://remote.example/volta"
