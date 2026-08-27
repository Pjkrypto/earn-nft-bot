from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Optional
import os
import traceback
import time

from flask import Response, request
from werkzeug.routing import Rule
from telegram import (
    LinkPreviewOptions,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CallbackContext,
    ExtBot,
    Application,
)
from web3 import Web3

from tg_nft_bot.db.db_operations import (
    query_collection,
    query_collection_by_webhook,
    query_minter_by_webhook,
)

# helpers
from tg_nft_bot.utils.networks import SCANS
from tg_nft_bot.utils.credentials import TOKEN

from tg_nft_bot.nft.nft_operations import (
    get_log_data,
    get_metadata,
    get_total_supply,
    get_url,
)
from tg_nft_bot.nft.nft_constants import OPENSEA

# app
from tg_nft_bot.bot.bot_config import flask_app


# Metadata can be temporarily incomplete immediately after a mint webhook.
# Keep these configurable without requiring new environment variables.
NFT_METADATA_FETCH_RETRIES = int(os.getenv("NFT_METADATA_FETCH_RETRIES", "10"))
NFT_METADATA_RETRY_SECONDS = float(os.getenv("NFT_METADATA_RETRY_SECONDS", "2"))


# ------------------------------------------------------------
# Network helpers
# ------------------------------------------------------------
def normalize_network(net: Optional[str]) -> Optional[str]:
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


def normalize_scan_network(net: str) -> str:
    return normalize_network(net)


# ------------------------------------------------------------
# context
# ------------------------------------------------------------
class ChatData:
    """Custom class for chat_data. Here we store data per message."""

    def __init__(self) -> None:
        self.webhook: str = None
        self.name: str = None
        self.network: str = None
        self.contract: str = None
        self.minter: str = None
        self.website: str = None
        self.chat: int = None
        self.menu: int = None


class CustomContext(CallbackContext[ExtBot, dict, ChatData, dict]):
    def __init__(
        self,
        application: Application,
        chat_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ):
        super().__init__(application=application, chat_id=chat_id, user_id=user_id)
        self._message_id: Optional[int] = None

    @property
    def webhook(self) -> Optional[str]:
        return self.chat_data.webhook

    @property
    def network(self) -> Optional[str]:
        return self.chat_data.network

    @property
    def contract(self) -> Optional[str]:
        return self.chat_data.contract

    @property
    def minter(self) -> Optional[str]:
        return self.chat_data.minter

    @property
    def website(self) -> Optional[str]:
        return self.chat_data.website

    @property
    def chat(self) -> Optional[int]:
        return self.chat_data.chat

    @property
    def menu(self) -> Optional[int]:
        return self.chat_data.menu

    @webhook.setter
    def webhook(self, value: str) -> None:
        self.chat_data.webhook = value

    @network.setter
    def network(self, value: str) -> None:
        self.chat_data.network = value

    @contract.setter
    def contract(self, value: str) -> None:
        self.chat_data.contract = value

    @minter.setter
    def minter(self, value: str) -> None:
        self.chat_data.minter = value

    @website.setter
    def website(self, value: str) -> None:
        self.chat_data.website = value

    @chat.setter
    def chat(self, value: int) -> None:
        self.chat_data.chat = value

    @menu.setter
    def menu(self, value: int) -> None:
        self.chat_data.menu = value


#################################################################
#######################     WEBHOOK     #########################
#################################################################


@dataclass
class WebhookUpdate:
    data: dict


@dataclass
class ReceiptData:
    totalReceipts: int
    filteredCount: int
    receipts: list[str]
    metadata: str


def create_webhook_route(route: str):
    if route not in [rule.rule for rule in flask_app.url_map.iter_rules()]:
        flask_app.url_map.add(Rule(route, endpoint=route))

        async def nft_updates() -> Response:
            json_data = request.get_json(silent=True) or {}
            print(f"Webhook hit on route={route}")
            print(
                f"Top-level keys={list(json_data.keys()) if isinstance(json_data, dict) else type(json_data)}"
            )
            await update_webhook_queue(json_data)
            return Response(status=HTTPStatus.OK)

        flask_app.view_functions[route] = nft_updates
        print("Webhook route created: " + route)


# ------------------------------------------------------------
# QuickNode parser (legacy)
# ------------------------------------------------------------
def parse_quicknode_tx(json_data: dict):
    if not isinstance(json_data, dict) or len(json_data) == 0:
        return None

    try:
        receipts = json_data["receipts"]
        print("QuickNode receipts found:", len(receipts))
    except Exception:
        return None

    if len(receipts) < 1:
        return None

    try:
        network = normalize_network(json_data["metadata"]["network"])
        webhook_id = json_data["metadata"]["stream_id"]
        logs_list = [log for receipt in receipts for log in receipt["logs"]]
        minter = query_minter_by_webhook(webhook_id)
        logs = get_log_data(network, minter, webhook_id, logs_list)
        return logs
    except Exception:
        traceback.print_exc()
        return None


# ------------------------------------------------------------
# Alchemy parser
# ------------------------------------------------------------
def map_alchemy_network(net: Optional[str]) -> Optional[str]:
    if not net:
        return net

    mapping = {
        "ETH_MAINNET": "ethereum-mainnet",
        "POLYGON_MAINNET": "polygon-mainnet",
        "ARB_MAINNET": "arbitrum-mainnet",
        "BASE_MAINNET": "base-mainnet",
    }
    return mapping.get(net.upper(), normalize_network(net))


def parse_token_id(token_id_value: Any) -> str:
    if token_id_value is None:
        return ""

    token_id = str(token_id_value)

    if token_id.startswith("0x"):
        try:
            return str(int(token_id, 16))
        except Exception:
            return token_id

    return token_id


def parse_alchemy_tx(json_data: dict):
    """
    Parses Alchemy NFT Activity webhook payloads into the internal format used
    by webhook_update/generate_output.

    Mint-only mode:
    - only zero-address mints are kept
    - all other transfers/sales are ignored
    """
    if not isinstance(json_data, dict) or len(json_data) == 0:
        return None

    webhook_id = json_data.get("webhookId") or json_data.get("webhook_id")
    event = json_data.get("event", {})
    event_network = map_alchemy_network(event.get("network"))
    activities = event.get("activity", [])

    if not webhook_id or not isinstance(activities, list) or len(activities) == 0:
        return None

    print(f"Alchemy activities found: {len(activities)} for webhook_id={webhook_id}")

    out = []
    zero_address = "0x0000000000000000000000000000000000000000"

    for activity in activities:
        try:
            contract = activity.get("contractAddress") or activity.get("contract_address")
            owner = activity.get("toAddress") or activity.get("to_address")
            from_address = activity.get("fromAddress") or activity.get("from_address")
            tx_hash = (
                activity.get("hash")
                or activity.get("transactionHash")
                or activity.get("transaction_hash")
            )
            token_id = parse_token_id(
                activity.get("tokenId")
                or activity.get("erc721TokenId")
                or activity.get("erc1155Metadata", [{}])[0].get("tokenId")
            )

            if not contract or not owner or not tx_hash or not token_id:
                continue

            # Mint-only mode: ignore non-mint transfers
            if not from_address or from_address.lower() != zero_address:
                continue

            out.append(
                {
                    "webhook_id": webhook_id,
                    "network": event_network,
                    "contract_lower": contract.lower(),
                    "contract_checksum": Web3.to_checksum_address(contract),
                    "owner": Web3.to_checksum_address(owner),
                    "token_id": token_id,
                    "hash": tx_hash,
                    "info": {
                        "type": "mint",
                        "price": "",
                        "price_usd": "",
                        "currency": "",
                        "marketplace": "alchemy",
                    },
                }
            )

        except Exception:
            traceback.print_exc()
            continue

    return out if len(out) > 0 else None


def parse_tx(json_data: dict):
    """
    Unified parser:
    - QuickNode Streams payloads
    - Alchemy NFT Activity webhook payloads
    """
    if not isinstance(json_data, dict):
        return None

    if "receipts" in json_data or (
        "metadata" in json_data
        and isinstance(json_data.get("metadata"), dict)
        and "stream_id" in json_data["metadata"]
    ):
        return parse_quicknode_tx(json_data)

    if "webhookId" in json_data or (
        "type" in json_data
        and "event" in json_data
        and isinstance(json_data.get("event"), dict)
    ):
        return parse_alchemy_tx(json_data)

    print("Unsupported webhook payload format.")
    print(json_data)
    return None


async def webhook_update(
    update: WebhookUpdate, context: ContextTypes.DEFAULT_TYPE
) -> None:
    data_list = parse_tx(update.data)
    if data_list is None or len(data_list) == 0:
        print("No parsable events found in webhook payload.")
        return

    for data in data_list:
        try:
            collection = query_collection_by_webhook(data["webhook_id"])
            if collection is None:
                print(f"No collection found for webhook_id={data['webhook_id']}")
                continue

            network = normalize_network(collection["network"])

            img, text = generate_output(
                network=network,
                contract_lower=data["contract_lower"],
                contract_checksum=data["contract_checksum"],
                owner=data["owner"],
                token_id=data["token_id"],
                hash=data["hash"],
                info=data["info"],
            )

            chats: list[str] = collection["chats"]
            for chat_id in chats:
                sent = False
                for attempt in range(2):
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            link_preview_options=LinkPreviewOptions(
                                url=img, show_above_text=True
                            ),
                            parse_mode="HTML",
                        )
                        print(f"Sent webhook event to chat_id={chat_id}")
                        sent = True
                        break
                    except Exception:
                        print(f"Sending message failed on attempt {attempt + 1}:")
                        traceback.print_exc()
                        time.sleep(2)

                if not sent:
                    print(f"Giving up sending to chat_id={chat_id}")

        except Exception:
            print("webhook_update processing failed:")
            traceback.print_exc()


async def update_queue(new_data):
    await application.update_queue.put(
        Update.de_json(data=new_data, bot=application.bot)
    )


async def update_webhook_queue(new_data):
    await application.update_queue.put(WebhookUpdate(data=new_data))


# create bot
context_types = ContextTypes(context=CustomContext, chat_data=ChatData)
application = (
    ApplicationBuilder()
    .token(TOKEN)
    .updater(None)
    .context_types(context_types)
    .concurrent_updates(True)
    .build()
)


def _collection_requires_traits(collection_name: str) -> bool:
    """
    NeanderBros and NeanderGals are expected to have trait metadata.
    Other collections supported by this bot may legitimately omit attributes,
    so traits are only mandatory for the Neander collections.
    """
    normalized = "".join(
        ch for ch in str(collection_name or "").casefold() if ch.isalnum()
    )
    return normalized in {"neanderbros", "neandergals"}


def generate_output(
    network,
    contract_lower,
    contract_checksum,
    owner,
    token_id,
    hash,
    info,
):
    network = normalize_scan_network(network)
    token_id = str(token_id)

    collection = query_collection(network, contract_lower)
    if collection is None:
        collection = query_collection(network, contract_checksum)

    if collection is None:
        raise Exception(
            f"No collection found for network={network}, contract={contract_lower}"
        )

    minter = collection["minter"]
    collection_name = collection["name"]
    website = collection["website"]

    # total supply / metadata should use checksum contract for web3 calls
    try:
        total_supply = get_total_supply(network, contract_checksum, minter)
    except Exception:
        traceback.print_exc()
        total_supply = None

    # A webhook can arrive before the token URI / IPFS metadata / image gateway
    # is fully available. Do not accept merely "truthy" metadata. For every NFT
    # we require a working image; for NeanderBros/Gals we also require traits.
    attempts = max(1, NFT_METADATA_FETCH_RETRIES)
    require_traits = _collection_requires_traits(collection_name)

    nft_data = None
    nft_image = ""
    last_metadata_reason = "metadata unavailable"

    for attempt in range(attempts):
        try:
            candidate = get_metadata(network, contract_checksum, token_id)

            if not isinstance(candidate, dict) or not candidate:
                last_metadata_reason = "metadata missing or not a JSON object"
            else:
                raw_image = candidate.get("image")
                attributes = candidate.get("attributes")
                has_traits = isinstance(attributes, list) and len(attributes) > 0

                if not isinstance(raw_image, str) or not raw_image.strip():
                    last_metadata_reason = "image field missing"
                elif require_traits and not has_traits:
                    last_metadata_reason = "traits not available yet"
                else:
                    resolved_image = get_url(raw_image.strip(), True)
                    if not resolved_image:
                        last_metadata_reason = "image URL not reachable yet"
                    else:
                        nft_data = candidate
                        nft_image = resolved_image
                        break

            print(
                f"Incomplete NFT metadata for {collection_name} tokenId={token_id} "
                f"attempt={attempt + 1}/{attempts}: {last_metadata_reason}"
            )

        except Exception as e:
            last_metadata_reason = f"{type(e).__name__}: {e}"
            print(
                f"NFT metadata fetch failed for {collection_name} tokenId={token_id} "
                f"attempt={attempt + 1}/{attempts}: {last_metadata_reason}"
            )
            traceback.print_exc()

        if attempt + 1 < attempts:
            time.sleep(max(0.0, NFT_METADATA_RETRY_SECONDS))

    if nft_data is None or not nft_image:
        raise RuntimeError(
            f"Giving up on {collection_name} tokenId={token_id} after {attempts} "
            f"metadata attempts: {last_metadata_reason}"
        )

    nft_name = nft_data.get("name") or f"{collection_name} #{token_id}"

    opensea = OPENSEA[network] + contract_checksum + "/" + token_id
    apenft = "https://apenft.io/#/asset/" + contract_checksum + "/" + token_id

    scan = SCANS[network]

    if info["type"] == "mint":
        title = (f"NEW {collection_name} MINT!").upper()
        message = f"\n<b>{title}</b>\n"
    elif info["type"] == "sale":
        title = (f"NEW {collection_name} PURCHASE!").upper()
        message = f"\n<b>{title}</b>\n\n"

        price = info.get("price", "")
        usd = info.get("price_usd", "")
        currency = info.get("currency", "")
        marketplace = info.get("marketplace", "")

        if price or currency or usd:
            message += f"Price: {price} {currency} ({usd} USD)\n"
        if marketplace:
            message += f"Marketplace: {str(marketplace).upper()}\n"
    else:
        title = (f"NEW {collection_name} ACTIVITY!").upper()
        message = f"\n<b>{title}</b>\n"

    message += f"\n<u><b>{nft_name}</b></u>\n"
    message += f"Token ID: {token_id}\n"

    message += '<a href="' + scan + "address/" + owner + '">Owner</a> | '
    message += '<a href="' + scan + "tx/" + hash + '">TX Hash</a> | '
    message += '<a href="' + scan + "token/" + contract_checksum + '#code">Contract</a>\n'

    attributes = nft_data.get("attributes") or []
    if attributes:
        message += "\n<u>Traits:</u>\n"
        for attr in attributes:
            if not isinstance(attr, dict):
                continue
            trait_type = attr.get("trait_type", "")
            value = attr.get("value", "")
            message += f"{trait_type}: {value}\n"

    if total_supply is not None:
        message += f"\nTotal minted: {total_supply}\n"

    message += '<a href="' + website + '">Website</a> | '

    if network == "tron-mainnet":
        message += '<a href="' + apenft + '">ApeNFT.io</a> '
    else:
        message += '<a href="' + opensea + '">Opensea</a>\n'

    message += "\n\nAD: "
    message += '<a href="https://t.me/PJ_Krypto">Book a slot to show your ad here!</a>\n'

    return [nft_image, message]
