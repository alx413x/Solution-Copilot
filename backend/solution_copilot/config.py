from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
