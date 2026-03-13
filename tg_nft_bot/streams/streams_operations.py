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
    ALCHEMY_NOTIFY_TOKEN,  # add this to credentials/env
)
from tg_nft_bot.streams.streams_utils import get_filter

from tg_nft_bot.config import local, staging, production

config = {"local": local, "staging": staging, "production": production}[ENV]

# ----------------------------
# QuickNode config (kept only for Tron fallback / legacy use)
# ----------------------------
qn_headers = {
    "Content-Type": "application/json",
    "accept": "application/json",
    "x-api-key": QUICKNODE_API_KEY,
}
qn_stream_url = "https://api.quicknode.com/streams/rest/v1/streams"

# ----------------------------
# Alchemy Webhooks config
# Docs:
# - Create webhook: POST https://dashboard.alchemy.com/api/create-webhook
# - Get all webhooks: GET https://dashboard.alchemy.com/api/team-webhooks
# - Delete webhook: DELETE https://dashboard.alchemy.com/api/delete-webhook?webhook_id=...
# - Update webhook: PUT https://dashboard.alchemy.com/api/update-webhook
# ----------------------------
alchemy_headers = {
    "Content-Type": "application/json",
    "accept": "application/json",
    "X-Alchemy-Token": ALCHEMY_NOTIFY_TOKEN,
}
alchemy_create_url = "https://dashboard.alchemy.com/api/create-webhook"
alchemy_team_webhooks_url = "https://dashboard.alchemy.com/api/team-webhooks"
alchemy_delete_url = "https://dashboard.alchemy.com/api/delete-webhook"
alchemy_update_url = "https://dashboard.alchemy.com/api/update-webhook"


# ----------------------------
# Network normalization
# ----------------------------
def normalize_network(net: str) -> str:
    if not net:
        return net

    raw = net.strip()
    upper = raw.upper()

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
    return aliases.get(upper, raw)


def is_tron_network(network: str) -> bool:
    return normalize_network(network) == "tron-mainnet"


def alchemy_network(network: str) -> str:
    """
    Maps app network keys to Alchemy webhook network enums.
    """
    net = normalize_network(network)
    mapping = {
        "ethereum-mainnet": "ETH_MAINNET",
        "polygon-mainnet": "POLYGON_MAINNET",
        "arbitrum-mainnet": "ARB_MAINNET",
        "base-mainnet": "BASE_MAINNET",
        # BNB and Tron are not handled here
    }

    if net not in mapping:
        raise ValueError(f"Alchemy webhook network not supported for '{network}'")
    return mapping[net]


# ----------------------------
# Alchemy HTTP helpers
# ----------------------------
def alchemy_post(url: str, payload: dict) -> requests.Response:
    return requests.post(url, headers=alchemy_headers, json=payload)


def alchemy_get(url: str) -> requests.Response:
    return requests.get(url, headers=alchemy_headers)


def alchemy_put(url: str, payload: dict) -> requests.Response:
    return requests.put(url, headers=alchemy_headers, json=payload)


def alchemy_delete(url: str) -> requests.Response:
    return requests.delete(url, headers=alchemy_headers)


# ----------------------------
# Alchemy webhook operations
# ----------------------------
def get_alchemy_webhooks() -> list[dict]:
    response = alchemy_get(alchemy_team_webhooks_url)
    if response.status_code != 200:
        raise Exception(
            f"Failed to get Alchemy webhooks. Status={response.status_code}, Body={response.text}"
        )

    data_json = response.json()

    # Docs show a list wrapper, but some APIs return {"data": [...]}
    if isinstance(data_json, dict) and "data" in data_json:
        return data_json["data"]

    if isinstance(data_json, list):
        rows = []
        for item in data_json:
            if isinstance(item, dict) and "data" in item and isinstance(item["data"], list):
                rows.extend(item["data"])
        if rows:
            return rows

    return []


def get_alchemy_webhook_by_id(webhook_id: str) -> Optional[dict]:
    webhooks = get_alchemy_webhooks()
    for wh in webhooks:
        if wh.get("id") == webhook_id:
            return wh
    return None


def check_if_stream_exists(id: str) -> bool:
    """
    Legacy name kept so rest of the app does not need to change.
    Checks either Alchemy or QuickNode depending on id format / availability.
    """
    if not id:
        return False

    # Alchemy IDs often differ from QuickNode IDs. We just check both approaches safely.
    try:
        wh = get_alchemy_webhook_by_id(id)
        if wh is not None:
            return True
    except Exception:
        pass

    # Legacy QuickNode fallback
    try:
        url = qn_stream_url + "/" + id
        response = requests.request("GET", url, headers=qn_headers, data={})
        return response.status_code == 200
    except Exception:
        return False


def get_stream_by_id(id: str) -> dict:
    """
    Legacy name kept for compatibility.
    """
    wh = get_alchemy_webhook_by_id(id)
    if wh is not None:
        return wh

    url = qn_stream_url + "/" + id
    response = requests.request("GET", url, headers=qn_headers, data={})
    if response.status_code == 200:
        return response.json()

    raise Exception("Webhook/stream does not exist.")


def delete_stream(id: str):
    """
    Legacy name kept for compatibility.
    Deletes Alchemy webhook first; falls back to QuickNode.
    """
    if not id:
        print("delete_stream skipped: id is empty/None")
        return

    # Try Alchemy
    try:
        response = alchemy_delete(f"{alchemy_delete_url}?webhook_id={id}")
        if response.status_code == 200:
            print("Alchemy webhook deleted successfully.")
            return
    except Exception:
        pass

    # Fallback QuickNode
    url = qn_stream_url + "/" + id
    response = requests.request("DELETE", url, headers=qn_headers, data={})
    if response.status_code == 200:
        print("QuickNode webhook deleted successfully.")
    elif response.status_code == 404:
        raise Exception("Webhook does not exist.")
    else:
        raise Exception(
            f"Deleting webhook failed. Status={response.status_code}, Body={response.text}"
        )


def pause_stream(id: str):
    """
    For Alchemy, inactive = paused.
    """
    if not id:
        print("pause_stream skipped: id is empty/None")
        return

    # Try Alchemy first
    try:
        payload = {"webhook_id": id, "is_active": False}
        response = alchemy_put(alchemy_update_url, payload)
        if response.status_code == 200:
            print("Alchemy webhook paused successfully.")
            return
    except Exception:
        pass

    # Fallback QuickNode
    url = qn_stream_url + "/" + id + "/pause"
    response = requests.post(url, headers=qn_headers, json={})
    print(response.text)


def activate_stream(id: str):
    if not id:
        print("activate_stream skipped: id is empty/None")
        return

    # Try Alchemy first
    try:
        payload = {"webhook_id": id, "is_active": True}
        response = alchemy_put(alchemy_update_url, payload)
        if response.status_code == 200:
            print("Alchemy webhook activated successfully.")
            return
    except Exception:
        pass

    # Fallback QuickNode
    url = qn_stream_url + "/" + id + "/activate"
    response = requests.post(url, headers=qn_headers, json={})
    print(response.text)


def create_alchemy_nft_webhook(
    network: str,
    contract: str,
    route: str,
    status: str = "active",
) -> Union[str, NoneType]:
    """
    Creates an Alchemy NFT Activity webhook filtered by contract.
    Supported by Alchemy for Ethereum, Arbitrum, Optimism, and Polygon NFTs.
    """
    net = normalize_network(network)
    if is_tron_network(net):
        raise ValueError("Alchemy NFT webhooks are not used for Tron.")

    webhook_id = None
    stream_name = f"{net}-{contract}-{route[1:]}"
    if config.env != "production":
        stream_name += f"-{config.env}"

    webhook_url = f"{URL}{route}"
    contract_hex = Web3.to_checksum_address(contract)

    # Reuse existing webhook if same name + URL + network
    try:
        webhooks = get_alchemy_webhooks()
        for wh in webhooks:
            if (
                wh.get("name") == stream_name
                and wh.get("webhook_url") == webhook_url
                and wh.get("network") == alchemy_network(net)
            ):
                webhook_id = wh.get("id")
                print(f"Alchemy webhook already exists for this collection: id={webhook_id}")

                # Ensure desired active state
                desired_active = status == "active"
                if wh.get("is_active") != desired_active:
                    payload = {
                        "webhook_id": webhook_id,
                        "is_active": desired_active,
                        "name": stream_name,
                    }
                    resp = alchemy_put(alchemy_update_url, payload)
                    if resp.status_code != 200:
                        raise Exception(
                            f"Failed to update existing Alchemy webhook. "
                            f"Status={resp.status_code}, Body={resp.text}"
                        )
                return webhook_id
    except Exception:
        traceback.print_exc()

    try:
        payload = {
            "network": alchemy_network(net),
            "webhook_type": "NFT_ACTIVITY",
            "webhook_url": webhook_url,
            "name": stream_name,
            "nft_filters": [
                {
                    "contract_address": contract_hex
                }
            ],
        }

        response = alchemy_post(alchemy_create_url, payload)
        print(f"Alchemy create webhook response status={response.status_code}")
        print(response.text)

        if response.status_code != 200:
            raise Exception(
                f"Failed to create Alchemy webhook. Status={response.status_code}, Body={response.text}"
            )

        data_json = response.json()
        webhook_id = data_json["data"]["id"]

        # If staging/local want inactive-ish behavior, update after create
        if status != "active":
            upd = alchemy_put(
                alchemy_update_url,
                {
                    "webhook_id": webhook_id,
                    "is_active": False,
                    "name": stream_name,
                },
            )
            if upd.status_code != 200:
                raise Exception(
                    f"Alchemy webhook created but failed to deactivate. "
                    f"Status={upd.status_code}, Body={upd.text}"
                )

        print("Alchemy webhook created successfully.")
        return webhook_id

    except Exception as e:
        print("Exception creating Alchemy webhook:", e)
        traceback.print_exc()
        return None


# ----------------------------
# Legacy QuickNode functions (retained for Tron fallback only)
# ----------------------------
def qn_post(url: str, payload: dict) -> requests.Response:
    return requests.post(url, headers=qn_headers, json=payload)


def qn_get(url: str, data: dict = {}) -> requests.Response:
    return requests.request("GET", url, headers=qn_headers, data=data)


def get_streams() -> Optional[list]:
    response = qn_get(qn_stream_url)
    data_json = response.json()
    if response.status_code == 200:
        return data_json["data"]
    return None


def create_qn_stream(
    network: str,
    contract: str,
    route: str,
    start_block: int = 0,
    stop_block: int = -1,
    status: str = "active",
    url: str = qn_stream_url,
) -> Union[str, NoneType]:
    print("Creating QuickNode stream...")
    print("Network:", network)
    print("Contract:", contract)

    hex_contract = get_hex_address(contract)
    print("Hex Contract:", hex_contract)

    stream_id = None
    stream_name = network + "-" + contract + "-" + route[1:]
    if config.env != "production":
        stream_name += "-" + config.env
    stream_url = f"{URL}{route}"

    if start_block == 0:
        if network == "tron-mainnet":
            client = Tron(providers.HTTPProvider(api_key=TRONGRID_API_KEY))
            start_block = client.get_latest_block_number()
        else:
            w3 = Web3(HTTPProvider(RPC[network]))
            start_block = w3.eth.block_number

    streams = get_streams()
    if streams is not None:
        for stream in streams:
            if (
                stream["name"] == stream_name
                and stream["destination_attributes"]["url"] == stream_url
            ):
                if config.env == "local":
                    delete_stream(stream["id"])
                else:
                    stream_id = stream["id"]
                    print(f"QuickNode webhook already exists for this collection: id={stream_id}")
                    break

    if stream_id is None:
        try:
            filter_fn = get_filter(hex_contract)
            payload = {
                "name": stream_name,
                "network": network,
                "dataset": "receipts",
                "filter_function": filter_fn,
                "region": "usa_east",
                "start_range": start_block,
                "end_range": stop_block,
                "dataset_batch_size": 1,
                "include_stream_metadata": "body",
                "destination": "webhook",
                "fix_block_reorgs": 0,
                "keep_distance_from_tip": 0,
                "destination_attributes": {
                    "url": stream_url,
                    "compression": "none",
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "max_retry": 3,
                    "retry_interval_sec": 1,
                    "post_timeout_sec": 10,
                },
                "status": status,
                "elastic_batch_enabled": False,
            }

            response = qn_post(url=url, payload=payload)
            print(response.status_code)
            print(response.text)

            if response.status_code == 201:
                data_json = response.json()
                stream_id = data_json["id"]
                print("QuickNode webhook created successfully.")
            else:
                raise Exception(
                    f"Failed to create QuickNode stream. Status={response.status_code}, Body={response.text}"
                )

        except Exception as e:
            print("Exception:", e)
            traceback.print_exc()

    return stream_id


def create_stream(network: str, contract: str, route: str) -> Union[str, NoneType]:
    """
    Main entry point used by the app.

    - Uses Alchemy for supported EVM NFT webhooks.
    - Uses QuickNode only for Tron fallback / legacy behavior.
    """
    network = normalize_network(network)

    if is_tron_network(network):
        # leave Tron on QuickNode path
        if config.env == "local":
            test_block = 0
            webhook_id = create_qn_stream(
                network=network,
                contract=contract,
                route=route,
                start_block=test_block + config.START_BLOCK_OFFSET,
                stop_block=test_block + config.STOP_BLOCK_OFFSET,
                status="active",
            )
        elif config.env == "staging":
            webhook_id = create_qn_stream(
                network=network,
                contract=contract,
                route=route,
                status="paused",
            )
        else:
            webhook_id = create_qn_stream(
                network=network,
                contract=contract,
                route=route,
            )
        return webhook_id

    # EVM path -> Alchemy
    if config.env == "staging":
        return create_alchemy_nft_webhook(
            network=network,
            contract=contract,
            route=route,
            status="paused",
        )

    return create_alchemy_nft_webhook(
        network=network,
        contract=contract,
        route=route,
        status="active",
    )
