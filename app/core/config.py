from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    llama_cloud_api_key: str
    auth0_domain: str = Field(validation_alias="AUTH0_DOMAIN")
    auth0_audience: str = Field(validation_alias="AUTH0_AUDIENCE")
    auth0_algorithms: list[str] = ["RS256"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("auth0_domain")
    @classmethod
    def validate_auth0_domain(cls, value: str) -> str:
        domain = value.strip().rstrip("/")
        if not domain or domain.lower() in {"null", "none"}:
            raise ValueError("AUTH0_DOMAIN must be set to your Auth0 tenant domain.")
        if "://" in domain:
            raise ValueError("AUTH0_DOMAIN must not include a URL scheme.")
        return domain

    @field_validator("auth0_audience")
    @classmethod
    def validate_auth0_audience(cls, value: str) -> str:
        audience = value.strip()
        if not audience or audience.lower() in {"null", "none"}:
            raise ValueError("AUTH0_AUDIENCE must be set to your Auth0 API identifier.")
        return audience


settings = Settings()