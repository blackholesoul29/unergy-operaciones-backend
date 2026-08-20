from pydantic import field_validator
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
    # CRM comercial: días sin respuesta antes de alertar (configurable por env).
    COMERCIAL_ALERTA_DIAS: int = 5
    # La actualización comercial de julio 2026 se aplica UNA vez y se marca sola
    # (ver app/services/comercial_actualizacion.MARCA_VERSION). Poner esto en
    # true fuerza a reaplicarla, pisando lo que se haya cambiado a mano después.
    COMERCIAL_REAPLICAR_ACTUALIZACION: bool = False

    @field_validator("SECRET_KEY", mode="after")
    @classmethod
    def secret_key_must_be_set(cls, v: str, info) -> str:
        # Los JWT se firman con SECRET_KEY. Con una clave vacía, jose firma con ""
        # y cualquiera puede forjar un token válido para cualquier sub/rol (toma
        # total de cuenta admin). En producción esto debe FALLAR el arranque, no
        # solo advertir. En desarrollo se mantiene la advertencia para no estorbar.
        env = (info.data.get("ENVIRONMENT") or "development").lower()
        if not v:
            if env != "development":
                raise ValueError(
                    "[SEGURIDAD] SECRET_KEY no está configurado en producción. "
                    "Define la variable de entorno SECRET_KEY en Railway con una "
                    "clave aleatoria de 32+ caracteres."
                )
            import warnings
            warnings.warn(
                "[SEGURIDAD] SECRET_KEY no está configurado; usando vacío en "
                "desarrollo. NO desplegar así a producción.",
                stacklevel=2,
            )
        elif len(v) < 32:
            import warnings
            warnings.warn(
                "[SEGURIDAD] SECRET_KEY es más corto que 32 caracteres; usa una "
                "clave aleatoria más larga para firmar JWT de forma segura.",
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

    # API de Liquidaciones (mismo host que UNERGY_API_URL). Requiere una cuenta
    # que pertenezca al grupo `admin` Y tenga is_staff=True: /api/liquidaciones/*
    # exige lo primero y /api/admin/* lo segundo. Si se dejan vacías se usan las
    # credenciales UNERGY_* de arriba.
    LIQUIDACIONES_LOGIN: str = ""
    LIQUIDACIONES_PASSWORD: str = ""
    # Clave de Gemini con la que la API lee los PDF de las facturas de XM para
    # sacarles mes y año. Es OPCIONAL: si se deja vacía, esa API usa la suya.
    # Va aquí y no en un campo de la pantalla porque es un secreto: puesto en el
    # navegador quedaría a la vista de cualquiera que abra la página.
    LIQUIDACIONES_GEMINI_API_KEY: str = ""

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

    # SMTP — envío de informes aprobados
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "operaciones@unergy.io"
    # Copia oculta (BCC) del Reporte CGM -- lista separada por comas.
    CORREO_SEGUIMIENTO: str = ""

    # IMAP — lectura automática de correos entrantes (ej. Excel de terceros
    # que envía Cedillanos vía cgm@erco.energy, ver excel_terceros_email.py).
    # Reusa SMTP_USER/SMTP_PASSWORD -- misma cuenta de Gmail, el mismo App
    # Password sirve para IMAP y SMTP a la vez. Requiere que IMAP esté
    # habilitado en la configuración de esa cuenta de Gmail/Workspace.
    IMAP_HOST: str = "imap.gmail.com"
    IMAP_PORT: int = 993

    # IMAP de mandatos -- buzón adhara@unergy.io, el único en copia de las tres
    # fuentes de correo de mandatos (revisoría y envíos a inversionistas).
    # NO reusa SMTP_USER/SMTP_PASSWORD: esas son de operaciones@, otra cuenta.
    # Requiere App Password propio (verificación en dos pasos activa en la cuenta).
    MANDATOS_IMAP_USER: str = ""
    MANDATOS_IMAP_PASSWORD: str = ""
    # Segundo buzón, opcional. Parte del correo de mandatos no pasa por
    # adhara@: Jessica manda algunos a la revisoría desde su propia cuenta, y
    # esos viven en SU carpeta de Enviados. Sin leerlos, la reconciliación no
    # puede saber que esos mandatos salieron. Si queda vacío, se lee un solo
    # buzón y todo funciona igual, solo con menos cobertura.
    MANDATOS_IMAP_USER_2: str = ""
    MANDATOS_IMAP_PASSWORD_2: str = ""

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
