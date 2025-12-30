# OmniTrending Telegram Bot

## Overview
OmniTrending is a multi-chain DEX trending bot that provides real-time token analytics across multiple blockchain networks including Solana, Ethereum, BSC, Base, and Arbitrum. The bot fetches live data from DexScreener API and allows users to trend tokens across different networks.

## Current State
- **Status**: Ready to run (waiting for BOT_TOKEN)
- **Language**: Python 3.11
- **Main Bot Framework**: aiogram 2.25.1
- **Bot Type**: Telegram Bot (console-based)

## Recent Changes (October 08, 2025)
- Fixed syntax errors in main.py (incomplete BotCommand statement)
- Added missing Pillow dependency for image processing
- Made SUPPORT_CHAT environment variable optional
- Added support handler and help command
- Configured workflow to run the bot

## Project Architecture
### File Structure
- `main.py` - Main bot code with handlers for network selection, token analysis, and trending
- `requirements.txt` - Python dependencies (aiogram, aiohttp, Pillow, python-dotenv)
- `.gitignore` - Python-specific ignore patterns

### Key Features
1. Multi-chain support (Solana, Ethereum, BSC, Base, Arbitrum)
2. Real-time token data fetching from DexScreener API
3. Professional token analytics display with charts
4. Trending packages with different durations (3H, 12H, 24H)
5. FSM-based conversation flow
6. Image resizing for token logos

### Dependencies
- **aiogram 2.25.1** - Telegram Bot API framework
- **aiohttp 3.8.6** - Async HTTP client for API requests
- **Pillow 10.0.0** - Image processing for token logos
- **python-dotenv 1.0.1** - Environment variable management

## Environment Variables Required
- `BOT_TOKEN` (required) - Telegram bot token from @BotFather
- `SUPPORT_CHAT` (optional) - Telegram chat ID for support notifications

## How to Run
The bot runs automatically via the configured workflow. Once BOT_TOKEN is provided:
1. The bot connects to Telegram
2. Users can interact with it via /start command
3. They select a network and provide contract addresses
4. The bot fetches and displays token analytics

## User Preferences
- None specified yet
