from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Dict, List, Optional
import traceback

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
from tg_nft_bot.nft.nft_constants import MAGIC_EDEN, OPENSEA, RARIBLE

# app
from tg_nft_bot.bot.bot_config import flask_app


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
    """
    Ensures keys used against SCANS/OPENSEA/etc. are canonical.
    """
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
            print(f"Top-level keys={list(json_data.keys()) if isinstance(json_data, dict) else type(json_data)}")
            await update_webhook_queue(json_data)
            return Response(status=HTTPStatus.OK)

        flask_app.view_functions[route] = nft_updates
        print("Webhook route created: " + route)


# ------------------------------------------------------------
# QuickNode parser (legacy)
# ------------------------------------------------------------
def parse_quicknode_tx(json_data: dict) -> Optional[list]:
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
    """
    Maps Alchemy webhook network enums to app network keys.
    """
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

    # Alchemy may deliver token ids as hex in some payloads.
    if token_id.startswith("0x"):
        try:
            return str(int(token_id, 16))
        except Exception:
            return token_id

    return token_id


def parse_alchemy_tx(json_data: dict) -> Optional[list]:
    """
    Parses Alchemy NFT Activity webhook payloads into the internal format used
    by webhook_update/generate_output.

    Expected high-level shape from Alchemy docs:
    {
      "webhookId": "...",
      "type": "NFT_ACTIVITY",
      "event": {
        "network": "POLYGON_MAINNET",
        "activity": [ ... ]
      }
    }

    We intentionally parse defensively because payloads can vary by activity type.
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

    for activity in activities:
        try:
            contract = activity.get("contractAddress") or activity.get("contract_address")
            owner = activity.get("toAddress") or activity.get("to_address")
            from_address = activity.get("fromAddress") or activity.get("from_address")
            tx_hash = activity.get("hash") or activity.get("transactionHash") or activity.get("transaction_hash")
            token_id = parse_token_id(
                activity.get("tokenId")
                or activity.get("erc721TokenId")
                or activity.get("erc1155Metadata", [{}])[0].get("tokenId")
            )

            if not contract or not owner or not tx_hash or not token_id:
                continue

            # Best-effort mint classification:
            # NFT mints are transfers from zero address.
            event_type = "mint"
            if from_address and from_address.lower() != "0x0000000000000000000000000000000000000000":
                event_type = "sale"

            info = {
                "type": event_type,
                "price": activity.get("value") or activity.get("amount") or "",
                "price_usd": activity.get("valueUsd") or activity.get("value_usd") or "",
                "currency": activity.get("asset") or activity.get("currency") or "",
                "marketplace": activity.get("marketplace") or "alchemy",
            }

            out.append(
                {
                    "webhook_id": webhook_id,
                    "network": event_network,
                    "contract": Web3.to_checksum_address(contract),
                    "owner": Web3.to_checksum_address(owner),
                    "token_id": token_id,
                    "hash": tx_hash,
                    "info": info,
                }
            )

        except Exception:
            traceback.print_exc()
            continue

    return out if len(out) > 0 else None


def parse_tx(json_data: dict) -> Optional[list]:
    """
    Unified parser:
    - QuickNode Streams payloads
    - Alchemy NFT Activity webhook payloads
    """
    if not isinstance(json_data, dict):
        return None

    # QuickNode path
    if "receipts" in json_data or (
        "metadata" in json_data and isinstance(json_data.get("metadata"), dict) and "stream_id" in json_data["metadata"]
    ):
        return parse_quicknode_tx(json_data)

    # Alchemy path
    if "webhookId" in json_data or (
        "type" in json_data and "event" in json_data and isinstance(json_data.get("event"), dict)
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
                network,
                data["contract"],
                data["owner"],
                data["token_id"],
                data["hash"],
                data["info"],
            )

            chats: list[str] = collection["chats"]
            for chat_id in chats:
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
                except Exception:
                    print("Sending message failed:")
                    traceback.print_exc()

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


def generate_output(network, contract, owner, token_id, hash, info):
    network = normalize_scan_network(network)
    token_id = str(token_id)

    collection = query_collection(network, contract)

    if collection is None:
        raise Exception(f"No collection found for network={network}, contract={contract}")

    minter = collection["minter"]
    collection_name = collection["name"]
    website = collection["website"]

    total_supply = get_total_supply(network, contract, minter)
    nft_data = get_metadata(network, contract, token_id)

    nft_name = nft_data.get("name") or f"{collection_name} #{token_id}"
    nft_image = get_url(nft_data["image"], True)

    opensea = OPENSEA[network] + contract + "/" + token_id
    rarible = RARIBLE[network] + contract + ":" + token_id
    magicEden = MAGIC_EDEN[network] + contract + "/" + token_id
    apenft = "https://apenft.io/#/asset/" + contract + "/" + token_id

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
    message += '<a href="' + scan + "token/" + contract + "#code" + '">Contract</a>\n'

    attributes = nft_data.get("attributes")
    if attributes is not None:
        message += "\n<u>Traits:</u>\n"
        for attr in attributes:
            trait_type = attr.get("trait_type", "")
            value = attr.get("value", "")
            message += f"{trait_type}: {value}\n"

    if total_supply is not None:
        message += f"\nTotal minted: {total_supply}\n"

    message += '<a href="' + website + '">Website</a> | '

    if network == "tron-mainnet":
        message += '<a href="' + apenft + '">ApeNFT.io</a> '
    else:
        message += '<a href="' + opensea + '">Opensea</a> | '
        message += '<a href="' + rarible + '">Rarible</a> | '
        message += '<a href="' + magicEden + '">MagicEden</a>\n'

    message += "\n\nAD: "
    message += '<a href="https://t.me/EARNServices">Book a slot to show your ad here!</a>\n'
    message += "\n<i>Powered by @EARNServices</i>"

    return [nft_image, message]
