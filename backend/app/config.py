from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://nekonoverse:changeme@localhost:5432/nekonoverse"
    valkey_url: str = "valkey://localhost:6379/0"
    domain: str = "localhost"
    secret_key: str = "change-this-to-a-random-secret-key"
    # 用途別の派生鍵 (SECRET_KEYから自動導出)
    totp_encryption_key: str = ""
    media_proxy_key: str = ""
    debug: bool = False
    registration_open: bool = False
    frontend_url: str = "http://localhost:3000"
    s3_endpoint_url: str = "http://nekono3s:8080"
    s3_access_key_id: str = "nekonoverse"
    s3_secret_access_key: str = "changeme-s3"
    s3_bucket: str = "nekonoverse"
    s3_region: str = "us-east-1"
    skip_ssl_verify: bool = False
    face_detect_url: str | None = None
    face_detect_uds: str | None = None  # UDS path for face-detect (e.g. /var/run/nekonoverse-face-detect/uvicorn.sock)

    # Forward proxy for outbound federation requests (origin IP concealment)
    http_proxy: str | None = None
    https_proxy: str | None = None
    no_proxy: str = ""

    use_https: bool = True

    def derive_key(self, purpose: str) -> str:
        """Derive a purpose-specific key from secret_key using HMAC."""
        import hashlib
        import hmac

        return hmac.new(
            self.secret_key.encode(), purpose.encode(), hashlib.sha256,
        ).hexdigest()

    @property
    def server_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.domain}"

    @property
    def media_url(self) -> str:
        return f"{self.server_url}/media"

    model_config = {"env_file": ".env"}


settings = Settings()
