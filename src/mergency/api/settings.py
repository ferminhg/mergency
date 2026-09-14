from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MERGENCY_")

    github_app_id: str
    github_private_key: str
    github_webhook_secret: str
    database_url: str
