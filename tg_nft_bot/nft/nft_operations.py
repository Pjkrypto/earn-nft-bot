import json
import traceback
from types import NoneType
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union
from web3 import Web3
from tronpy import Tron
from tronpy.abi import trx_abi
from tronpy.providers import HTTPProvider
from web3.constants import ADDRESS_ZERO

import os
import requests
from PIL import Image
from io import BytesIO
import tempfile
from urllib.request import urlopen

from tg_nft_bot.utils.credentials import (
    RESERVOIR_API_KEY,
    TRONGRID_API_KEY,
)
from tg_nft_bot.nft.nft_constants import (
    RESERVOIR_URL,
)
from tg_nft_bot.utils.networks import RPC


current_dir = os.path.dirname(os.path.abspath(__file__))
abi_json = os.path.join(current_dir, "..", "..", "assets", "NFT.json")

gateways = {
    "ipfs": ["ipfs.io", "dweb.link", "gateway.pinata.cloud", "w3s.link"],
    "btfs": ["gateway.btfs.io"],
}

REQUEST_TIMEOUT_SECONDS = float(os.getenv("NFT_HTTP_TIMEOUT_SECONDS", "15"))
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EarnNFTBot/1.0)",
    "Accept": "*/*",
}


class SaleData(TypedDict):
    type: str
    price: str  # Assuming price can be int or float
    price_usd: str
    currency: str
    marketplace: str


class LogData(TypedDict):
    network: str
    webhook_id: str
    token_id: int
    contract: str
    owner: str
    hash: str
    info: SaleData


def is_valid_url(url: str, is_image=False) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False

    try:
        response = requests.get(
            url.strip(),
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code != 200 or not response.content:
            return False

        if is_image:
            image = Image.open(BytesIO(response.content))
            image.verify()

        return True

    except Exception as e:
        print(f"URL validation failed for {url[:180]}: {type(e).__name__}: {e}")
        return False


def get_url(link: str, is_image=False) -> str:
    """
    Resolve normal HTTP(S), IPFS, and BTFS links to a reachable URL.

    The old implementation could throw on malformed/unknown protocols and had
    no request timeouts. This version fails cleanly so callers can retry.
    """
    if not isinstance(link, str):
        return ""

    link = link.strip()
    if not link:
        return ""

    if link.startswith("https://") or link.startswith("http://"):
        candidates = [link]

        # Preserve the old HTTPS -> HTTP fallback behavior.
        if link.startswith("https://"):
            candidates.append("http://" + link[len("https://"):])

        for url in candidates:
            if is_valid_url(url, is_image):
                return url
        return ""

    if "://" not in link:
        return ""

    protocol, suburl = link.split("://", 1)
    protocol = protocol.lower().strip()
    suburl = suburl.lstrip("/")

    protocol_gateways = gateways.get(protocol)
    if not protocol_gateways or not suburl:
        print(f"Unsupported or malformed media protocol: {protocol!r}")
        return ""

    for gateway in protocol_gateways:
        https_url = f"https://{gateway}/{protocol}/{suburl}"
        if is_valid_url(https_url, is_image):
            return https_url

        http_url = f"http://{gateway}/{protocol}/{suburl}"
        if is_valid_url(http_url, is_image):
            return http_url

    return ""


def is_transfer(topics: List[str]) -> bool:
    return (
        len(topics) == 4
        and topics[0]
        == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    )


def is_mint(addr_from: str, minter: str) -> bool:
    print("address from: ", addr_from)
    print("minter: ", minter)
    return addr_from == minter


def get_log_data(
    network: str, minter: str, webhook_id: str, logs: List[Dict[str, Any]]
) -> Union[List[LogData], NoneType]:

    data: List[LogData] = []
    for log in logs:

        if is_transfer(log["topics"]):

            # check if mint or purchase
            info = get_sale_info(network, minter, log)
            if info is None:
                return None

            data.append(
                LogData(
                    network=network,
                    webhook_id=webhook_id,
                    token_id=int(log["topics"][3], 16),
                    contract=Web3.to_checksum_address(log["address"]),
                    owner=Web3.to_checksum_address("0x" + log["topics"][2][-40:]),
                    hash=log["transactionHash"],
                    info=info,
                )
            )

    return data


def get_sale_info(network: str, minter: str, log) -> Union[SaleData, NoneType]:

    addr_from = Web3.to_checksum_address("0x" + log["topics"][1][-40:])
    if is_mint(addr_from, minter):
        return {
            "type": "mint",
            "price": "N/A",
            "price_usd": "N/A",
            "currency": "N/A",
            "marketplace": "N/A",
        }
    elif network == "tron-mainnet":
        w3 = Web3(Web3.HTTPProvider(RPC[network]))
        tx = w3.eth.get_transaction_receipt(log["transactionHash"])
        for log in tx["logs"]:
            hex_str = log["data"].hex()
            if len(hex_str) == 192:
                price = float(int(hex_str[128:], 16)) / 1e6

                return {
                    "type": "sale",
                    "price": "%.2f" % price,
                    "price_usd": "N/A",
                    "currency": "TRX",
                    "marketplace": "ApeNFT.io",
                }
    else:
        contract = Web3.to_checksum_address(log["address"])
        token_id = int(log["topics"][3], 16)
        url = f"{RESERVOIR_URL[network]}tokens/{contract}%3A{token_id}/activity/v5?limit=1&sortBy=eventTimestamp&types=sale"
        headers = {"accept": "*/*", "x-api-key": RESERVOIR_API_KEY}

        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        data_json = response.json()

        events = data_json["activities"]
        if len(events) > 0:
            price_native = events[0]["price"]["amount"]["decimal"]
            price_usd = events[0]["price"]["amount"]["usd"]
            currency = events[0]["price"]["currency"]["symbol"]
            marketplace = events[0]["fillSource"]["name"]

            return {
                "type": events[0]["type"],
                "price": f"{price_native:.3f}",
                "price_usd": f"{price_usd:.3f}",
                "currency": currency,
                "marketplace": marketplace,
            }

    return None


def get_collection_info(network, contract):

    name = None

    try:
        if network == "tron-mainnet":
            try:
                client = Tron(HTTPProvider(api_key=TRONGRID_API_KEY))
                contract_instance = client.get_contract(contract)
                with open(abi_json, "r") as f:
                    contract_instance.abi = json.load(f)
                    name = contract_instance.functions.name()
            except Exception as e:
                print(f"TRON: {e}")
                raise e

        else:
            try:
                w3 = Web3(Web3.HTTPProvider(RPC[network]))
                with open(abi_json, "r") as f:
                    abi = json.load(f)
                    contract_instance = w3.eth.contract(address=contract, abi=abi)
                    name: str = contract_instance.functions.name.call()

            except Exception as e:
                print(f"EVM: {e}")
                raise e

    except Exception as e:
        print(f"Reading contract failed: {e}")

    finally:

        if name is not None:
            collection = name.replace(" ", "-")
            collection = collection.lower()
        else:
            collection = None

        return [name, collection]


def get_total_supply(network, contract, minter):

    total_supply = None

    try:
        if network == "tron-mainnet":
            try:
                client = Tron(HTTPProvider(api_key=TRONGRID_API_KEY))
                contract_instance = client.get_contract(contract)
                with open(abi_json, "r") as f:
                    contract_instance.abi = json.load(f)
                    contract_instance.abi.append(trx_abi)
                    if minter != ADDRESS_ZERO:
                        total_supply = (
                            contract_instance.functions.totalSupply()
                            - contract_instance.functions.balanceOf(minter)
                        )
                    else:
                        total_supply = contract_instance.functions.totalSupply()
            except Exception as e:
                print(f"TRON: {e}")
                raise e

        else:
            try:
                w3 = Web3(Web3.HTTPProvider(RPC[network]))
                with open(abi_json, "r") as f:
                    abi = json.load(f)
                    contract_instance = w3.eth.contract(address=contract, abi=abi)
                    if minter != ADDRESS_ZERO:
                        total_supply = (
                            contract_instance.functions.totalSupply().call()
                            - contract_instance.functions.balanceOf(minter).call()
                        )
                    else:
                        total_supply = contract_instance.functions.totalSupply().call()

            except Exception as e:
                print(f"EVM: {e}")
                raise e

    except Exception as e:
        print(f"Reading contract failed: {e}")

    finally:
        return total_supply


def get_metadata_json(metadataLink: str):
    url = get_url(metadataLink)

    if not url:
        print(f"Could not resolve metadata URL: {metadataLink}")
        return None

    try:
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code != 200:
            print(f"Metadata request returned status {response.status_code}: {url}")
            return None

        try:
            json_data = response.json()
        except Exception as e:
            print(f"Invalid metadata JSON from {url}: {e}")
            return None

        if not isinstance(json_data, dict):
            print(f"Metadata JSON was not an object: {url}")
            return None

        return json_data

    except Exception as e:
        print(f"Request metadata failed for {url}: {type(e).__name__}: {e}")
        return None


def get_metadata(network: str, contract: str, token_id: str):

    metadata_url = None
    if network == "tron-mainnet":
        try:
            client = Tron(HTTPProvider(api_key=TRONGRID_API_KEY))
            base58_address = Tron.to_base58check_address(Tron.to_hex_address(contract))
            contract_instance = client.get_contract(base58_address)
            with open(abi_json, "r") as f:
                contract_instance.abi = json.load(f)
                metadata_url = contract_instance.functions.tokenURI(int(token_id))
        except Exception as e:
            print(f"Fetching metadata url failed (TRON): {e}")

    else:
        try:
            w3 = Web3(Web3.HTTPProvider(RPC[network]))
            with open(abi_json, "r") as f:
                abi = json.load(f)
                contract_instance = w3.eth.contract(address=contract, abi=abi)
                metadata_url = contract_instance.functions.tokenURI(
                    Web3.to_int(int(token_id))
                ).call()
        except Exception as e:
            print(f"Fetching metadata url failed (EVM): {e}")

    if metadata_url is not None:
        data_json = get_metadata_json(metadata_url)
    else:
        data_json = None

    return data_json
