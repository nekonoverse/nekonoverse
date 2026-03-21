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
    allow_private_networks: bool = False  # Disable SSRF protection (for federation tests)
    face_detect_url: str | None = None
    face_detect_uds: str | None = None  # UDS path for face-detect (e.g. /var/run/nekonoverse-face-detect/uvicorn.sock)
    media_proxy_transform_url: str | None = None
    media_proxy_transform_uds: str | None = None
    summary_proxy_url: str | None = None
    summary_proxy_uds: str | None = None

    # SMTP (optional — メール機能は設定時のみ有効)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None  # 未設定時は noreply@{domain}
    smtp_security: str = "starttls"  # "starttls" (port 587) / "ssl" (port 465) / "none"

    # Cloudflare Turnstile CAPTCHA (optional)
    turnstile_site_key: str | None = None
    turnstile_secret_key: str | None = None

    # Forward proxy for outbound federation requests (origin IP concealment)
    http_proxy: str | None = None
    https_proxy: str | None = None
    no_proxy: str = ""

    valkey_max_connections: int = 1000

    use_https: bool = True

    # Web Push (VAPID)
    vapid_private_key: str | None = None

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

    @property
    def face_detect_enabled(self) -> bool:
        return bool(self.face_detect_url or self.face_detect_uds)

    @property
    def face_detect_base_url(self) -> str:
        return self.face_detect_url or "http://localhost"

    @property
    def media_proxy_transform_enabled(self) -> bool:
        return bool(self.media_proxy_transform_url or self.media_proxy_transform_uds)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def email_from(self) -> str:
        return self.smtp_from or f"noreply@{self.domain}"

    @property
    def media_proxy_transform_base_url(self) -> str:
        return self.media_proxy_transform_url or "http://localhost"

    model_config = {"env_file": ".env"}


settings = Settings()

# デフォルトのSECRET_KEYでの運用を防止
_INSECURE_KEYS = {"change-this-to-a-random-secret-key", ""}
if not settings.debug and settings.secret_key in _INSECURE_KEYS:
    import sys

    print(
        "FATAL: SECRET_KEY is not configured. "
        "Set a strong random value in .env (e.g. python -c \"import secrets; print(secrets.token_hex(32))\")",
        file=sys.stderr,
    )
    sys.exit(1)
