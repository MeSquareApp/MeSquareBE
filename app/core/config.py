import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

class Settings(BaseSettings):
    database_url: str
    llama_cloud_api_key: str
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    AUTH0_DOMAIN: str = os.getenv("AUTH0_DOMAIN", "dev-tk23yhyc2e62i1a5.us.auth0.com")
    AUTH0_AUDIENCE: str = os.getenv("AUTH0_AUDIENCE", "https://mesquared-api-endpoint")
    AUTH0_ALGORITHMS: list = ["RS256"]
settings = Settings()