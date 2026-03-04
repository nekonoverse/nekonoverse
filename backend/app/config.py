from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://nekonoverse:changeme@localhost:5432/nekonoverse"
    valkey_url: str = "valkey://localhost:6379/0"
    domain: str = "localhost"
    secret_key: str = "change-this-to-a-random-secret-key"
    debug: bool = True
    registration_open: bool = False
    frontend_url: str = "http://localhost:3000"

    @property
    def server_url(self) -> str:
        scheme = "http" if self.debug else "https"
        return f"{scheme}://{self.domain}"

    model_config = {"env_file": ".env"}


settings = Settings()
