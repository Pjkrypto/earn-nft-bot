import os
from tg_nft_bot.utils.credentials import (
    QUICKNODE_ENDPOINT_API_KEY,
    ALCHEMY_API_KEY,
    ALCHEMY_HTTPS_URL,
)

# ------------------------------------------------------------
# Network aliases / canonical helpers
# ------------------------------------------------------------
NETWORK_ALIASES = {
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


def normalize_network(net: str) -> str:
    if not net:
        return net
    raw = str(net).strip()
    return NETWORK_ALIASES.get(raw.upper(), raw)


# ------------------------------------------------------------
# Display names
# ------------------------------------------------------------
NETWORK_SYMBOLS = {
    "ethereum-mainnet": "ETH",
    "base-mainnet": "BASE",
    "bnbchain-mainnet": "BNB",
    "arbitrum-mainnet": "ARB",
    "avalanche-mainnet": "AVAX",
    "polygon-mainnet": "MATIC",
    "tron-mainnet": "TRON",

    # legacy aliases for safety
    "MATIC": "MATIC",
    "POLYGON": "MATIC",
    "ETH": "ETH",
    "ARB": "ARB",
    "BNB": "BNB",
    "TRON": "TRON",
}

# ------------------------------------------------------------
# RPC URLs
# Priority:
# 1) explicit per-network env override
# 2) shared ALCHEMY_HTTPS_URL for polygon only if supplied
# 3) ALCHEMY_API_KEY derived URL for supported EVM chains
# 4) existing QuickNode fallback
# ------------------------------------------------------------

ETH_RPC = (
    os.getenv("ETHEREUM_RPC_HTTP_URL", "").strip()
    or (
        f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
        if ALCHEMY_API_KEY
        else f"https://tame-divine-leaf.quiknode.pro/{QUICKNODE_ENDPOINT_API_KEY}/"
    )
)

BNB_RPC = (
    os.getenv("BNBCHAIN_RPC_HTTP_URL", "").strip()
    or (
        # Alchemy does not cover BNB in the same standard way as ETH/Polygon/Base/Arb
        f"https://tame-divine-leaf.bsc.quiknode.pro/{QUICKNODE_ENDPOINT_API_KEY}/"
    )
)

BASE_RPC = (
    os.getenv("BASE_RPC_HTTP_URL", "").strip()
    or (
        f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
        if ALCHEMY_API_KEY
        else f"https://tame-divine-leaf.base-mainnet.quiknode.pro/{QUICKNODE_ENDPOINT_API_KEY}/"
    )
)

AVAX_RPC = (
    os.getenv("AVALANCHE_RPC_HTTP_URL", "").strip()
    or (
        # Alchemy fallback not assumed here
        f"https://tame-divine-leaf.avalanche-mainnet.quiknode.pro/{QUICKNODE_ENDPOINT_API_KEY}/ext/bc/C/rpc/"
    )
)

ARB_RPC = (
    os.getenv("ARBITRUM_RPC_HTTP_URL", "").strip()
    or (
        f"https://arb-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
        if ALCHEMY_API_KEY
        else f"https://tame-divine-leaf.arbitrum-mainnet.quiknode.pro/{QUICKNODE_ENDPOINT_API_KEY}/"
    )
)

POLYGON_RPC = (
    os.getenv("POLYGON_RPC_HTTP_URL", "").strip()
    or os.getenv("RPC_HTTP_URL", "").strip()
    or ALCHEMY_HTTPS_URL.strip()
    or (
        f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
        if ALCHEMY_API_KEY
        else f"https://tame-divine-leaf.matic.quiknode.pro/{QUICKNODE_ENDPOINT_API_KEY}/"
    )
)

TRON_RPC = (
    os.getenv("TRON_RPC_HTTP_URL", "").strip()
    or f"https://tame-divine-leaf.tron-mainnet.quiknode.pro/{QUICKNODE_ENDPOINT_API_KEY}"
)

SOLANA_RPC = (
    os.getenv("SOLANA_RPC_HTTP_URL", "").strip()
    or f"https://tame-divine-leaf.solana-mainnet.quiknode.pro/{QUICKNODE_ENDPOINT_API_KEY}"
)

RPC = {
    "ethereum-mainnet": ETH_RPC,
    "bnbchain-mainnet": BNB_RPC,
    "base-mainnet": BASE_RPC,
    "avalanche-mainnet": AVAX_RPC,
    "arbitrum-mainnet": ARB_RPC,
    "polygon-mainnet": POLYGON_RPC,
    "tron-mainnet": TRON_RPC,
    "solana-mainnet": SOLANA_RPC,

    # legacy aliases for safety
    "MATIC": POLYGON_RPC,
    "POLYGON": POLYGON_RPC,
    "ETH": ETH_RPC,
    "ARB": ARB_RPC,
    "BNB": BNB_RPC,
    "TRON": TRON_RPC,
}

SCANS = {
    "ethereum-mainnet": "https://etherscan.io/",
    "bnbchain-mainnet": "https://bscscan.com/",
    "base-mainnet": "https://basescan.org/",
    "avalanche-mainnet": "https://snowtrace.io/",
    "arbitrum-mainnet": "https://arbiscan.io/",
    "polygon-mainnet": "https://polygonscan.com/",
    "tron-mainnet": "https://tronscan.org/",

    # legacy aliases for safety
    "MATIC": "https://polygonscan.com/",
    "POLYGON": "https://polygonscan.com/",
    "ETH": "https://etherscan.io/",
    "ARB": "https://arbiscan.io/",
    "BNB": "https://bscscan.com/",
    "TRON": "https://tronscan.org/",
}
