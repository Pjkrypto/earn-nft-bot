def generate_output(network, contract, owner, token_id, hash, info):
    network = normalize_scan_network(network)
    token_id = str(token_id)

    contract_lower = contract.lower()
    contract_checksum = Web3.to_checksum_address(contract)

    collection = query_collection(network, contract_lower)
    if collection is None:
        collection = query_collection(network, contract_checksum)

    if collection is None:
        raise Exception(
            f"No collection found for network={network}, contract={contract}"
        )

    minter = collection["minter"]
    collection_name = collection["name"]
    website = collection["website"]

    total_supply = get_total_supply(network, contract_checksum, minter)

    # Retry metadata because Alchemy webhooks can arrive before metadata indexes
    nft_data = None
    for _ in range(10):  # up to ~20 seconds
        nft_data = get_metadata(network, contract_checksum, token_id)
        if nft_data:
            break
        time.sleep(2)

    if nft_data is None:
        nft_data = {}

    nft_name = nft_data.get("name") or f"{collection_name} #{token_id}"

    raw_image = nft_data.get("image")
    if raw_image:
        nft_image = get_url(raw_image, True)
    else:
        nft_image = website

    opensea = OPENSEA[network] + contract_checksum + "/" + token_id
    rarible = RARIBLE[network] + contract_checksum + ":" + token_id
    magicEden = MAGIC_EDEN[network] + contract_checksum + "/" + token_id
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
