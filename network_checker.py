# network_checker.py
import json
import urllib.request
import urllib.error

# ---------------- DexScreener Network Detection ---------------- #

def detect_network_from_dexscreener(ca: str, supported_networks: list[str]) -> str | None:
    """
    Detects which blockchain a contract belongs to using DexScreener public API.
    Works with built-in libraries only (no aiohttp or requests needed).

    Returns:
        - the network name (e.g. 'bsc', 'ethereum', 'solana', etc.)
        - None if not found
    """
    if not ca:
        return None

    url = f"https://api.dexscreener.com/latest/dex/search/?q={ca}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[NetworkChecker] Error fetching DexScreener data: {e}")
        return None

    pairs = data.get("pairs") or []
    if not pairs:
        print("[NetworkChecker] No pairs found for CA.")
        return None

    supported = set(n.lower() for n in supported_networks)
    for p in pairs:
        for key in ("chainId", "chain", "chainName", "network"):
            val = p.get(key)
            if isinstance(val, str):
                val_l = val.lower()
                for s in supported:
                    if s in val_l or val_l in s:
                        print(f"[NetworkChecker] Detected network: {s}")
                        return s

    print("[NetworkChecker] Could not match any supported network.")
    return None
