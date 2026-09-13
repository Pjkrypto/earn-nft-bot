import hashlib


def build_mint_event_key(network, contract, tx_hash, token_id):
    """
    Build a stable identifier for a unique on-chain mint.

    The webhook id is intentionally excluded. Replacing an Alchemy webhook must
    not cause an already processed mint to be announced again.
    """
    canonical = "|".join(
        str(value or "").strip().lower()
        for value in (network, contract, tx_hash, token_id)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
