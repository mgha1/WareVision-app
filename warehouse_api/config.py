import os


class Settings(object):
    """Runtime configuration loaded from environment variables."""

    def __init__(self):
        self.oracle_user = os.getenv("ORACLE_USER", "HKTR1G4")
        self.oracle_password = os.getenv("ORACLE_PASSWORD", "Hk1_ySVtqYZp-Dayk_zl")
        self.oracle_dsn = os.getenv("ORACLE_DSN", "hkt202602_high")
        self.oracle_config_dir = os.getenv(
            "ORACLE_CONFIG_DIR",
            "/home/opc/wallet",
        )
        self.oracle_wallet_dir = os.getenv(
            "ORACLE_WALLET_DIR",
            self.oracle_config_dir,
        )

        self.oracle_pool_min = int(os.getenv("ORACLE_POOL_MIN", "1"))
        self.oracle_pool_max = int(
            os.getenv("ORACLE_POOL_MAX", os.getenv("SQLCL_POOL_SIZE", "5"))
        )
        self.app_username = os.getenv("APP_USERNAME", "admin")
        self.app_password = os.getenv("APP_PASSWORD", "warehouse123")
        self.session_secret = os.getenv(
            "SESSION_SECRET",
            "warehouse-demo-session-secret",
        )
        self.slotting_interval_seconds = int(
            os.getenv("SLOTTING_INTERVAL_SECONDS", "60")
        )
        self.enable_slotting_scheduler = (
            os.getenv("ENABLE_SLOTTING_SCHEDULER", "true").lower() == "true"
        )

        cors_value = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        self.cors_origins = [
            origin.strip() for origin in cors_value.split(",") if origin.strip()
        ]
