from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://nekonoverse:changeme@localhost:5432/nekonoverse"
    valkey_url: str = "valkey://localhost:6379/0"
    domain: str = "localhost"
    secret_key: str = "change-this-to-a-random-secret-key"
    debug: bool = True
    registration_open: bool = False
    frontend_url: str = "http://localhost:3000"
    s3_endpoint_url: str = "http://nekono3s:8080"
    s3_access_key_id: str = "nekonoverse"
    s3_secret_access_key: str = "changeme-s3"
    s3_bucket: str = "nekonoverse"
    s3_region: str = "us-east-1"
    skip_ssl_verify: bool = False

    @property
    def server_url(self) -> str:
        # Derive scheme from frontend_url (which reflects the actual public URL)
        scheme = "https" if self.frontend_url.startswith("https") else "http"
        return f"{scheme}://{self.domain}"

    @property
    def media_url(self) -> str:
        return f"{self.server_url}/media"

    model_config = {"env_file": ".env"}


settings = Settings()
