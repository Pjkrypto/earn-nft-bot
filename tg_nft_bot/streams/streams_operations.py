import traceback
from typing import Union, Optional
import requests
from web3 import Web3

from tg_nft_bot.utils.addresses import get_hex_address
from tg_nft_bot.utils.credentials import (
    ENV,
    QUICKNODE_API_KEY,
    URL,
    ALCHEMY_NOTIFY_TOKEN,
)
from tg_nft_bot.streams.streams_utils import get_filter
from tg_nft_bot.config import local, staging, production

config = {"local": local, "staging": staging, "production": production}[ENV]

# ----------------------------
# Alchemy configuration
# ----------------------------
alchemy_headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Alchemy-Token": ALCHEMY_NOTIFY_TOKEN,
}

ALCHEMY_CREATE = "https://dashboard.alchemy.com/api/create-webhook"
ALCHEMY_LIST = "https://dashboard.alchemy.com/api/team-webhooks"
ALCHEMY_DELETE = "https://dashboard.alchemy.com/api/delete-webhook"
ALCHEMY_UPDATE = "https://dashboard.alchemy.com/api/update-webhook"

# ----------------------------
# QuickNode configuration
# kept only for legacy / non-Alchemy fallback if needed later
# ----------------------------
qn_headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "x-api-key": QUICKNODE_API_KEY,
}
qn_stream_url = "https://api.quicknode.com/streams/rest/v1/streams"


# ----------------------------
# Network helpers
# ----------------------------
def normalize_network(net: str) -> str:
    if not net:
        return net

    aliases = {
        "MATIC": "polygon-mainnet",
        "POLYGON": "polygon-mainnet",
        "POLYGON-MAINNET": "polygon-mainnet",
        "ETH": "ethereum-mainnet",
        "ETHEREUM": "ethereum-mainnet",
        "ETHEREUM-MAINNET": "ethereum-mainnet",
        "ARB": "arbitrum-mainnet",
        "ARBITRUM": "arbitrum-mainnet",
        "ARBITRUM-MAINNET": "arbitrum-mainnet",
        "BASE": "base-mainnet",
        "BASE-MAINNET": "base-mainnet",
        "BNB": "bnbchain-mainnet",
        "BSC": "bnbchain-mainnet",
        "BNBCHAIN": "bnbchain-mainnet",
        "BNBCHAIN-MAINNET": "bnbchain-mainnet",
        "TRON": "tron-mainnet",
        "TRON-MAINNET": "tron-mainnet",
    }

    return aliases.get(str(net).strip().upper(), str(net).strip())


def alchemy_network(network: str) -> str:
    mapping = {
        "ethereum-mainnet": "ETH_MAINNET",
        "polygon-mainnet": "POLYGON_MAINNET",
        "arbitrum-mainnet": "ARB_MAINNET",
        "base-mainnet": "BASE_MAINNET",
    }

    network = normalize_network(network)

    if network not in mapping:
        raise Exception(f"Unsupported Alchemy network: {network}")

    return mapping[network]


# ----------------------------
# Alchemy helpers
# ----------------------------
def log_response(prefix: str, response: requests.Response) -> None:
    print(f"{prefix} status: {response.status_code}")
    try:
        print(f"{prefix} body: {response.text}")
    except Exception:
        print(f"{prefix} body: <unavailable>")


def get_alchemy_webhooks() -> list[dict]:
    response = requests.get(ALCHEMY_LIST, headers=alchemy_headers, timeout=30)
    log_response("Alchemy list webhooks", response)

    if response.status_code != 200:
        raise Exception(
            f"Failed to list Alchemy webhooks. Status={response.status_code}, Body={response.text}"
        )

    data = response.json()

    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        return data["data"]

    if isinstance(data, list):
        return data

    return []


def delete_stream(webhook_id: Optional[str]) -> None:
    if not webhook_id:
        print("delete_stream skipped: empty webhook_id")
        return

    response = requests.delete(
        f"{ALCHEMY_DELETE}?webhook_id={webhook_id}",
        headers=alchemy_headers,
        timeout=30,
    )
    log_response("Alchemy delete webhook", response)


def activate_stream(webhook_id: str) -> None:
    payload = {
        "webhook_id": webhook_id,
        "is_active": True,
    }
    response = requests.put(ALCHEMY_UPDATE, headers=alchemy_headers, json=payload, timeout=30)
    log_response("Alchemy activate webhook", response)


def pause_stream(webhook_id: str) -> None:
    payload = {
        "webhook_id": webhook_id,
        "is_active": False,
    }
    response = requests.put(ALCHEMY_UPDATE, headers=alchemy_headers, json=payload, timeout=30)
    log_response("Alchemy pause webhook", response)


# ----------------------------
# Alchemy webhook creation
# ----------------------------
def create_alchemy_webhook(network: str, contract: str, route: str) -> Optional[str]:
    network = normalize_network(network)
    webhook_url = f"{URL}{route}"
    stream_name = f"{network}-{contract}-{route[1:]}"

    if config.env != "production":
        stream_name += f"-{config.env}"

    contract = Web3.to_checksum_address(contract)

    # Try lookup first, but do not fail creation if lookup is unauthorized/broken
    try:
        existing = get_alchemy_webhooks()
        for wh in existing:
            if (
                wh.get("webhook_url") == webhook_url
                and wh.get("network") == alchemy_network(network)
                and wh.get("name") == stream_name
            ):
                webhook_id = wh.get("id")
                print(f"Existing Alchemy webhook found: {webhook_id}")
                return webhook_id
    except Exception as e:
        print(f"Alchemy webhook lookup skipped due to error: {e}")
        traceback.print_exc()

    payload = {
        "network": alchemy_network(network),
        "webhook_type": "NFT_ACTIVITY",
        "webhook_url": webhook_url,
        "name": stream_name,
        "nft_filters": [
            {
                "contract_address": contract
            }
        ],
    }

    response = requests.post(
        ALCHEMY_CREATE,
        headers=alchemy_headers,
        json=payload,
        timeout=30,
    )
    log_response("Alchemy create webhook", response)

    if response.status_code not in (200, 201):
        raise Exception(
            f"Webhook creation failed. Status={response.status_code}, Body={response.text}"
        )

    data = response.json()

    webhook_id = None
    if isinstance(data, dict):
        webhook_id = (
            data.get("data", {}).get("id")
            or data.get("id")
            or data.get("webhook_id")
        )

    if not webhook_id:
        raise Exception(f"Webhook created but no webhook id returned. Body={response.text}")

    print(f"Webhook created successfully: {webhook_id}")
    return webhook_id


# ----------------------------
# QuickNode fallback helpers
# only kept so imports from elsewhere do not break
# ----------------------------
def check_if_stream_exists(stream_id: str) -> bool:
    if not stream_id:
        return False
    try:
        response = requests.get(
            f"{ALCHEMY_LIST}",
            headers=alchemy_headers,
            timeout=30,
        )
        if response.status_code != 200:
            return False
        data = response.json()
        rows = data.get("data", []) if isinstance(data, dict) else []
        return any(row.get("id") == stream_id for row in rows)
    except Exception:
        return False


def get_stream_by_id(stream_id: str) -> dict:
    rows = get_alchemy_webhooks()
    for row in rows:
        if row.get("id") == stream_id:
            return row
    raise Exception("Webhook does not exist.")


def create_qn_stream(network: str, contract: str, route: str, *args, **kwargs):
    raise Exception("QuickNode stream creation is disabled in this Alchemy version.")


# ----------------------------
# Main entrypoint
# ----------------------------
def create_stream(network: str, contract: str, route: str) -> Optional[str]:
    network = normalize_network(network)
    return create_alchemy_webhook(network, contract, route)
