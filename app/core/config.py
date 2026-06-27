from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


    APP_NAME: str = "Plataforma Operaciones Unergy"
    ENVIRONMENT: str = "development"
    FRONTEND_URL: str = "http://localhost:5173"

    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/operaciones"

    SECRET_KEY: str = ""
    JWT_EXPIRE_MINUTES: int = 480
    # Token de larga duración para la app móvil (PWA) — default 30 días
    MOBILE_JWT_EXPIRE_MINUTES: int = 43200

    @field_validator("SECRET_KEY", mode="after")
    @classmethod
    def secret_key_warn_if_weak(cls, v: str) -> str:
        if not v or len(v) < 16:
            import warnings
            warnings.warn(
                "[SEGURIDAD] SECRET_KEY no está configurado o es muy corto. "
                "Define la variable de entorno SECRET_KEY en Railway con una clave segura.",
                stacklevel=2,
            )
        return v

    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_PATH: str = "./uploads"
    S3_BUCKET: str = ""
    S3_ENDPOINT: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""

    # Unergy API credentials (used by _legacy bridge)
    UNERGY_API_URL: str = "https://api.unergy.io"
    UNERGY_ACCOUNT_ID: str = ""
    UNERGY_LOGIN: str = ""
    UNERGY_PASSWORD: str = ""

    # Sun Factory — Solenium EPC, cronogramas de construcción (próximos a energizarse).
    # Auth = auth.solenium.co/api/token/ (username/password → JWT access).
    SUNFACTORY_API_URL: str = "https://sunfactory.solenium.co/api"
    SUNFACTORY_AUTH_URL: str = "https://auth.solenium.co/api/token/"
    SUNFACTORY_USERNAME: str = ""
    SUNFACTORY_PASSWORD: str = ""

    # Solenium API (FMO inverter data) — OAuth2 username/password
    SOLENIUM_AUTH_URL: str = "https://auth.solenium.co/api"
    SOLENIUM_DATA_URL: str = "https://data.solenium.co/api"
    SOLENIUM_USER: str = ""
    SOLENIUM_PASS: str = ""

    # Quoia CGM API (fronteras / medidores) — legacy token auth
    QUOIA_API_TOKEN: str = ""
    QUOIA_BASE_URL: str = "https://gaia.quoia.energy/api"

    # Gaia JWT auth (for /api/cgm/v1/border + /api/node measurements)
    GAIA_USER: str = ""
    GAIA_PASS: str = ""
    GAIA_BASE_URL: str = "https://gaia.quoia.energy"

    # MGS Alarms polling
    MGS_ENABLED: bool = True
    MGS_POLL_INTERVAL_MINUTES: int = 15
    TIMEZONE: str = "America/Bogota"

    # EVO Energy API (DailySpot + Clima via Tailscale)
    EVO_API_URL: str = ""
    EVO_API_TOKEN: str = ""

    # External databases (read-only correlation)
    ORIGINA_DATABASE_URL: str = ""
    REQUESTSDB_DATABASE_URL: str = ""

    # SMTP — envío de informes aprobados
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "operaciones@unergy.io"

    @field_validator(
        "UNERGY_API_URL",
        "SUNFACTORY_API_URL",
        "SUNFACTORY_AUTH_URL",
        "SOLENIUM_AUTH_URL",
        "SOLENIUM_DATA_URL",
        "QUOIA_BASE_URL",
        "GAIA_BASE_URL",
        "EVO_API_URL",
        mode="after",
    )
    @classmethod
    def external_url_must_be_https(cls, v: str, info: ValidationInfo) -> str:
        # Las URLs de servicios externos críticos (Unergy, SunFactory, Solenium,
        # Quoia, Gaia, EVO) deben usar HTTPS. Una cadena vacía indica un servicio
        # no configurado y se permite; cualquier valor presente debe ser https://.
        if v and not str(v).startswith("https://"):
            raise ValueError(
                f"URL for {info.field_name} must use HTTPS for security"
            )
        return v

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_db_url(cls, v: str) -> str:
        # Railway entrega postgres:// o postgresql://, psycopg3 necesita postgresql+psycopg://
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+psycopg://", 1)
        if v.startswith("postgresql://") and "+psycopg" not in v:
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v


settings = Settings()
