from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    spring_ws_url: str = ""
    pi_serial_code: str = ""
    usb_by_id_dir: str = "/dev/serial/by-id"
    usb_poll_seconds: float = 1.0
    artifact_max_bytes: int = 100 * 1024 * 1024


def get_settings() -> Settings:
    return Settings()
