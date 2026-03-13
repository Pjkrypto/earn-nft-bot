import os
from dotenv import load_dotenv

load_dotenv()


def getenv_str(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return "" if value is None else str(value).strip()


def getenv_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return default
    return int(value)


TOKEN = getenv_str("TOKEN")
PORT = getenv_int("PORT", 8000)
URL = getenv_str("URL")

DATABASE_URL = getenv_str("DATABASE_URL")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

TABLE = getenv_str("TABLE")

# Legacy / existing providers
QUICKNODE_API_KEY = getenv_str("QUICKNODE_API_KEY")
QUICKNODE_ENDPOINT_API_KEY = getenv_str("QUICKNODE_ENDPOINT_API_KEY")
OPENSEA_API_KEY = getenv_str("OPENSEA_API_KEY")
RESERVOIR_API_KEY = getenv_str("RESERVOIR_API_KEY")
TRONGRID_API_KEY = getenv_str("TRONGRID_API_KEY")

# Alchemy
# Preferred variable for webhook management token
ALCHEMY_NOTIFY_TOKEN = getenv_str("ALCHEMY_NOTIFY_TOKEN")

# Optional fallbacks if your stack currently uses one of these names instead
if not ALCHEMY_NOTIFY_TOKEN:
    ALCHEMY_NOTIFY_TOKEN = (
        getenv_str("ALCHEMY_WEBHOOK_TOKEN")
        or getenv_str("ALCHEMY_TOKEN")
        or getenv_str("ALCHEMY_API_TOKEN")
        or getenv_str("ALCHEMY_API_KEY")
    )

# Optional RPC key/url helpers if other files need them later
ALCHEMY_API_KEY = getenv_str("ALCHEMY_API_KEY")
ALCHEMY_HTTPS_URL = getenv_str("ALCHEMY_HTTPS_URL")
ALCHEMY_WSS_URL = getenv_str("ALCHEMY_WSS_URL")

ENV = getenv_str("ENV", "local")
TEST_TYPE = getenv_str("TEST_TYPE", "mint")

# Optional debug flag
DEBUG_WEBHOOKS = getenv_str("DEBUG_WEBHOOKS", "false").lower() in ("1", "true", "yes", "y")


def validate_required_credentials() -> None:
    missing = []

    if not TOKEN:
        missing.append("TOKEN")
    if not URL:
        missing.append("URL")
    if not DATABASE_URL:
        missing.append("DATABASE_URL")

    # Only enforce Alchemy token if you are using Alchemy webhook flow
    # and only enforce QuickNode key if you are using QuickNode stream flow.
    # So this function is safe to call manually, but not required at import time.

    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )
