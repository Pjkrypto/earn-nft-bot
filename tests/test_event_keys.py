from tg_nft_bot.utils.event_keys import build_mint_event_key, normalize_token_id


def test_normalize_token_id_handles_decimal_and_hex():
    assert normalize_token_id("2632") == "2632"
    assert normalize_token_id("0xA48") == "2632"
    assert normalize_token_id(2632) == "2632"


def test_mint_key_ignores_transaction_hash_format_and_case():
    first = build_mint_event_key(
        "polygon-mainnet",
        "0xcB124CF226f045fa49b1793031C79DA517387f7f",
        "0xABC",
        "2632",
    )
    replay = build_mint_event_key(
        "POLYGON-MAINNET",
        "0xCB124CF226F045FA49B1793031C79DA517387F7F",
        "",
        "0xA48",
    )

    assert replay == first


def test_different_tokens_have_different_mint_keys():
    first = build_mint_event_key("polygon", "0xabc", "0xtx", "2632")
    second = build_mint_event_key("polygon", "0xabc", "0xtx", "2633")

    assert first != second
