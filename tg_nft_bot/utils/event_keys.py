import hashlib


def normalize_token_id(token_id):
    """Return one stable representation for decimal or hexadecimal token IDs."""
    value = str(token_id or "").strip().lower()
    if not value:
        return value

    try:
        base = 16 if value.startswith("0x") else 10
        return str(int(value, base))
    except ValueError:
        # Keep unexpected provider values deterministic instead of preventing
        # the webhook from being acknowledged.
        return value


def build_mint_event_key(network, contract, tx_hash, token_id):
    """
    Build a stable identifier for a unique ERC-721 token mint.

    The webhook id is intentionally excluded. Replacing an Alchemy webhook must
    not cause an already processed mint to be announced again. The transaction
    hash is also intentionally excluded because providers can omit or format it
    differently on a retry. A contract/token pair can only be minted once.

    ``tx_hash`` remains in the function signature for compatibility with
    existing callers and audit logging.
    """
    canonical = "|".join(
        (
            str(network or "").strip().lower(),
            str(contract or "").strip().lower(),
            normalize_token_id(token_id),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
