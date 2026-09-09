from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: Literal["development", "test", "production"] = "development"
    dev_auth_enabled: bool = False
    oidc_jwks_url: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""

    @model_validator(mode="after")
    def guard_dev_auth(self):
        if self.app_env == "production" and self.dev_auth_enabled:
            raise ValueError("Development authentication is prohibited in production")
        return self

    database_url: SecretStr
    redis_url: SecretStr
    s3_endpoint_url: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = "solution-copilot"
    s3_region: str = "us-east-1"
    upload_max_bytes: int = Field(25 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    document_max_chars: int = Field(2_000_000, ge=1, le=10_000_000)
    job_lease_seconds: int = Field(300, ge=10, le=3600)
    job_max_attempts: int = Field(3, ge=1, le=10)
    model_provider: str = "deepseek"
    model_base_url: str = "https://api.deepseek.com"
    model_name: str = ""
    model_api_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
