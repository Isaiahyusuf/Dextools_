# OmniTrending (Stage 1)

Stage 1: basic Telegram bot for OmniTrending — multi-chain DEX trending MVP.

## Files
- `main.py` — main bot code. Uses `BOT_TOKEN` env var.
- `requirements.txt` — Python dependencies.

## Quick start (Render)
1. Deploy repo to Render and set environment variable `BOT_TOKEN`.
2. Set start command: `python main.py`

## Notes
- fetch_token_info() is a Stage-1 best-effort stub. Replace with proper API integration (DexScreener, Bitquery, Moralis) in Stage 2.
- Do not commit BOT tokens to the repo. Use environment variables.
