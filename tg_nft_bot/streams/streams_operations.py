import traceback
from types import NoneType
from typing import Union, Optional
import requests
from web3 import Web3, HTTPProvider
from tronpy import Tron
from tronpy import providers

from tg_nft_bot.utils.addresses import get_hex_address
from tg_nft_bot.utils.networks import RPC
from tg_nft_bot.utils.credentials import (
    ENV,
    QUICKNODE_API_KEY,
    TEST_TYPE,
    TRONGRID_API_KEY,
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
    "X-Alchemy-Token": ALCHEMY_NOTIFY_TOKEN,
}

ALCHEMY_CREATE = "https://dashboard.alchemy.com/api/create-webhook"
ALCHEMY_LIST = "https://dashboard.alchemy.com/api/team-webhooks"
ALCHEMY_DELETE = "https://dashboard.alchemy.com/api/delete-webhook"
ALCHEMY_UPDATE = "https://dashboard.alchemy.com/api/update-webhook"


# ----------------------------
# Network helpers
# ----------------------------

def normalize_network(net: str) -> str:

    aliases = {
        "MATIC": "polygon-mainnet",
        "POLYGON": "polygon-mainnet",
        "ETH": "ethereum-mainnet",
        "ETHEREUM": "ethereum-mainnet",
        "ARB": "arbitrum-mainnet",
        "ARBITRUM": "arbitrum-mainnet",
        "BASE": "base-mainnet",
        "BNB": "bnbchain-mainnet",
        "BSC": "bnbchain-mainnet",
        "TRON": "tron-mainnet",
    }

    return aliases.get(net.upper(), net)


def alchemy_network(network: str):

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

def alchemy_post(url, payload):

    r = requests.post(url, headers=alchemy_headers, json=payload)

    print("Alchemy response status:", r.status_code)
    print("Alchemy response body:", r.text)

    return r


def get_alchemy_webhooks():

    r = requests.get(ALCHEMY_LIST, headers=alchemy_headers)

    if r.status_code != 200:
        raise Exception("Failed to list Alchemy webhooks")

    data = r.json()

    if "data" in data:
        return data["data"]

    return []


def delete_stream(webhook_id):

    if not webhook_id:
        return

    r = requests.delete(
        f"{ALCHEMY_DELETE}?webhook_id={webhook_id}",
        headers=alchemy_headers,
    )

    print("delete webhook response:", r.status_code, r.text)


def activate_stream(webhook_id):

    payload = {
        "webhook_id": webhook_id,
        "is_active": True
    }

    requests.put(ALCHEMY_UPDATE, headers=alchemy_headers, json=payload)


def pause_stream(webhook_id):

    payload = {
        "webhook_id": webhook_id,
        "is_active": False
    }

    requests.put(ALCHEMY_UPDATE, headers=alchemy_headers, json=payload)


# ----------------------------
# Alchemy webhook creation
# ----------------------------

def create_alchemy_webhook(network, contract, route):

    network = normalize_network(network)

    webhook_url = f"{URL}{route}"

    stream_name = f"{network}-{contract}-{route[1:]}"

    if config.env != "production":
        stream_name += f"-{config.env}"

    contract = Web3.to_checksum_address(contract)

    try:

        existing = get_alchemy_webhooks()

        for wh in existing:

            if (
                wh.get("webhook_url") == webhook_url
                and wh.get("network") == alchemy_network(network)
                and wh.get("name") == stream_name
            ):
                print("Existing webhook found:", wh["id"])
                return wh["id"]

    except Exception:
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
        ]
    }

    r = alchemy_post(ALCHEMY_CREATE, payload)

    if r.status_code != 200:
        raise Exception("Webhook creation failed")

    data = r.json()

    webhook_id = data["data"]["id"]

    print("Webhook created:", webhook_id)

    return webhook_id


# ----------------------------
# QuickNode (only used for Tron)
# ----------------------------

qn_headers = {
    "Content-Type": "application/json",
    "x-api-key": QUICKNODE_API_KEY,
}

qn_stream_url = "https://api.quicknode.com/streams/rest/v1/streams"


def create_qn_stream(network, contract, route):

    print("Creating QuickNode stream (Tron fallback)")

    hex_contract = get_hex_address(contract)

    stream_name = network + "-" + contract + "-" + route[1:]

    stream_url = f"{URL}{route}"

    payload = {
        "name": stream_name,
        "network": network,
        "dataset": "receipts",
        "filter_function": get_filter(hex_contract),
        "destination": "webhook",
        "destination_attributes": {
            "url": stream_url
        }
    }

    r = requests.post(qn_stream_url, headers=qn_headers, json=payload)

    if r.status_code != 201:
        raise Exception("QuickNode webhook creation failed")

    return r.json()["id"]


# ----------------------------
# Main entrypoint
# ----------------------------

def create_stream(network, contract, route):

    network = normalize_network(network)

    if network == "tron-mainnet":

        return create_qn_stream(network, contract, route)

    return create_alchemy_webhook(network, contract, route)
