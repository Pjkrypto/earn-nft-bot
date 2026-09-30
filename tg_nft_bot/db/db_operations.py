from flask_sqlalchemy import SQLAlchemy
import psycopg2
from psycopg2.extras import RealDictCursor
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from web3 import Web3

from tg_nft_bot.utils.credentials import TABLE
from tg_nft_bot.utils.event_keys import build_mint_event_key, normalize_token_id

db = SQLAlchemy()
from tg_nft_bot.bot.bot_config import flask_app


class CollectionConfigs(db.Model):
    __tablename__ = TABLE

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=True)
    slug = db.Column(db.String(255), nullable=True)
    network = db.Column(db.String(255), nullable=True)
    contract = db.Column(db.String(255), nullable=True)
    minter = db.Column(db.String(255), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    webhookId = db.Column(db.String(255), nullable=True)
    chats = db.Column(db.ARRAY(db.BigInteger), nullable=True)


class ProcessedMintEvents(db.Model):
    """Persistently prevents duplicate notifications for the same NFT mint."""

    __tablename__ = "processed_mint_events"

    event_key = db.Column(db.String(64), primary_key=True)
    webhook_id = db.Column(db.String(255), nullable=False)
    network = db.Column(db.String(255), nullable=False)
    contract = db.Column(db.String(255), nullable=False)
    tx_hash = db.Column(db.String(255), nullable=False)
    token_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )


def claim_mint_event(webhook_id, network, contract, tx_hash, token_id):
    """
    Atomically claim a mint for notification processing.

    Returns True only for the first delivery. Concurrent Alchemy deliveries for
    the same transaction/token hit the primary-key constraint and return False.
    """
    normalized_network = str(network).strip().lower()
    normalized_contract = str(contract).strip().lower()
    normalized_token_id = normalize_token_id(token_id)
    event_key = build_mint_event_key(
        normalized_network,
        normalized_contract,
        tx_hash,
        normalized_token_id,
    )

    with flask_app.app_context():
        # Rows created by older releases used the transaction hash in the
        # primary key. Check their stored identity fields before inserting the
        # new contract/token key so an Alchemy replay after deployment does not
        # announce a historical mint one more time.
        token_id_candidates = {normalized_token_id}
        if normalized_token_id.isdigit():
            token_id_candidates.add(hex(int(normalized_token_id)))

        existing_event = ProcessedMintEvents.query.filter(
            db.func.lower(ProcessedMintEvents.network) == normalized_network,
            db.func.lower(ProcessedMintEvents.contract) == normalized_contract,
            db.func.lower(ProcessedMintEvents.token_id).in_(token_id_candidates),
        ).first()
        if existing_event is not None:
            return False

        event = ProcessedMintEvents(
            event_key=event_key,
            webhook_id=str(webhook_id),
            network=normalized_network,
            contract=normalized_contract,
            tx_hash=str(tx_hash).lower(),
            token_id=normalized_token_id,
        )
        db.session.add(event)

        try:
            db.session.commit()
            return True
        except IntegrityError:
            db.session.rollback()
            return False


# class BotAuthorizations(db.Model):
#     __tablename__ = "authorizations"
#
#     id = db.Column(db.Integer, primary_key=True)
#     name = db.Column(db.String(255), nullable=True)
#     tgId = db.Column(db.BigInteger, nullable=True)


def _collection_to_dict(collection):
    """
    Convert a CollectionConfigs row to the dictionary format used by the bot.
    Return None when no matching database row exists.
    """
    if collection is None:
        return None

    return {
        "id": collection.id,
        "name": collection.name,
        "slug": collection.slug,
        "contract": collection.contract,
        "minter": collection.minter,
        "network": collection.network,
        "website": collection.website,
        "webhookId": collection.webhookId,
        "chats": collection.chats,
    }


def _normalize_contract_for_lookup(network, contract):
    """
    Database EVM contracts are stored as checksum addresses.

    Alchemy and other webhook providers may send the same address in lowercase,
    so normalize EVM addresses before database lookups. TRON addresses are left
    unchanged.

    If a non-address value is supplied, return it unchanged so callers get a
    normal "not found" result instead of crashing during lookup.
    """
    if contract is None:
        return None

    if network == "tron-mainnet":
        return contract

    try:
        return Web3.to_checksum_address(contract)
    except Exception:
        return contract


def query_table():
    with flask_app.app_context():
        collections = CollectionConfigs.query.all()
        collection_list = [_collection_to_dict(collection) for collection in collections]
    return collection_list


def query_collection(network, contract):
    """
    Find a collection by network + contract.

    EVM contract matching is normalized to checksum form so lowercase Alchemy
    contract addresses correctly match the checksum address stored in the DB.
    Returns None when no collection is found.
    """
    lookup_contract = _normalize_contract_for_lookup(network, contract)

    with flask_app.app_context():
        collection = CollectionConfigs.query.filter_by(
            contract=lookup_contract,
            network=network,
        ).first()

        return _collection_to_dict(collection)


def query_collection_by_webhook(webhook_id):
    with flask_app.app_context():
        collection = CollectionConfigs.query.filter_by(webhookId=webhook_id).first()
        return _collection_to_dict(collection)


def query_collection_by_chat(chatId):
    with flask_app.app_context():
        collections = CollectionConfigs.query.filter(
            CollectionConfigs.chats.any(chatId)
        ).all()

        collection_list = [_collection_to_dict(collection) for collection in collections]

    return collection_list


def query_collection_by_id(cid):
    with flask_app.app_context():
        collection = CollectionConfigs.query.filter_by(id=cid).first()
        return _collection_to_dict(collection)


def query_network_by_webhook(webhook_id):
    with flask_app.app_context():
        entry = CollectionConfigs.query.filter_by(webhookId=webhook_id).first()

    if entry is None:
        return None
    return entry.network


def query_website_by_contract(contract, network):
    lookup_contract = _normalize_contract_for_lookup(network, contract)

    with flask_app.app_context():
        entry = CollectionConfigs.query.filter_by(
            contract=lookup_contract,
            network=network,
        ).first()

    if entry is None:
        return None
    return entry.website


def query_name_by_contract(network, contract):
    lookup_contract = _normalize_contract_for_lookup(network, contract)

    with flask_app.app_context():
        entry = CollectionConfigs.query.filter_by(
            contract=lookup_contract,
            network=network,
        ).first()

    if entry is None:
        return None
    return entry.name


def query_minter_by_webhook(webhook_id):
    with flask_app.app_context():
        entry = CollectionConfigs.query.filter_by(webhookId=webhook_id).first()

    if entry is None:
        return None
    return entry.minter


def query_slug_by_contract(network, contract):
    lookup_contract = _normalize_contract_for_lookup(network, contract)

    with flask_app.app_context():
        entry = CollectionConfigs.query.filter_by(
            contract=lookup_contract,
            network=network,
        ).first()

    if entry is None:
        return None
    return entry.slug


def query_chats_by_contract(network, contract):
    lookup_contract = _normalize_contract_for_lookup(network, contract)

    with flask_app.app_context():
        entry = CollectionConfigs.query.filter_by(
            contract=lookup_contract,
            network=network,
        ).first()

    if entry is None:
        return None
    return entry.chats


def check_if_exists(network, contract):
    lookup_contract = _normalize_contract_for_lookup(network, contract)

    with flask_app.app_context():
        entry = CollectionConfigs.query.filter_by(
            contract=lookup_contract,
            network=network,
        ).first()

    if entry is None:
        return None

    print("Entry: ", entry.id)
    return entry.id


def initial_config():
    print("initializing app with database...")
    db.init_app(flask_app)

    with flask_app.app_context():
        engine = db.get_engine()
        if not inspect(engine).has_table(TABLE):
            db.drop_all()

        # Also creates newly introduced support tables, such as the persistent
        # mint-event deduplication table, without altering existing tables.
        db.create_all()
        db.session.commit()


def add_config(name, slug, network, contract, minter, website, webhook_id, chats):
    with flask_app.app_context():
        config = CollectionConfigs(
            name=name,
            slug=slug,
            network=network,
            contract=(
                contract
                if network == "tron-mainnet"
                else Web3.to_checksum_address(contract)
            ),
            minter=(
                minter
                if network == "tron-mainnet"
                else Web3.to_checksum_address(minter)
            ),
            website=website,
            webhookId=webhook_id,
            chats=chats,
        )

        db.session.add(config)
        db.session.commit()


def update_config(name, slug, network, contract, minter, website, webhook_id, chats):
    lookup_contract = _normalize_contract_for_lookup(network, contract)

    with flask_app.app_context():
        row_to_update = CollectionConfigs.query.filter_by(
            contract=lookup_contract,
            network=network,
        ).first()

        if row_to_update is None:
            raise ValueError(
                f"Collection configuration not found for "
                f"network={network}, contract={contract}"
            )

        row_to_update.name = name
        row_to_update.slug = slug
        row_to_update.network = network
        row_to_update.contract = (
            contract
            if network == "tron-mainnet"
            else Web3.to_checksum_address(contract)
        )
        row_to_update.minter = (
            minter
            if network == "tron-mainnet"
            else Web3.to_checksum_address(minter)
        )
        row_to_update.website = website
        row_to_update.webhookId = webhook_id
        row_to_update.chats = chats

        db.session.commit()


def update_chats_by_id(id, chats):
    with flask_app.app_context():
        collection_update = CollectionConfigs.query.filter(
            CollectionConfigs.id == id
        ).one()

        collection_update.chats = chats
        db.session.commit()


def delete_config_by_id(id):
    with flask_app.app_context():
        collection = CollectionConfigs.query.filter(
            CollectionConfigs.id == id
        ).one()

        db.session.delete(collection)
        db.session.commit()
