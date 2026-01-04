import os
import aiohttp
import asyncio
import logging
from io import BytesIO
from PIL import Image
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from datetime import datetime, timedelta
import json
##bot is ready

# ---------------- Load Bot Token ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")

SUPPORT_CHAT = os.getenv("SUPPORT_CHAT")  # Optional support chat id (string or int)

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable not found!")

# ---------------- Admin / Channel config ----------------
SUPPORT_IDS = [7886119612]                   # Allowed support user IDs (will receive debug messages)
CHANNEL_ID = -1003251300654                 # Channel ID (negative) where posts will be sent

# ---------------- Footer / Branding ----------------
POST_FOOTER = "\n\n🌐 DexTools Trending Bot • visibility for your  token"

# ---------------- Logging setup (console + file) ----------------
logger = logging.getLogger("dextoolstrending")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

# Optional rotating file log (uncomment if you want file logs)
try:
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler("dextoolstrending.log", maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)
except Exception:
    pass

# ---------------- Payment Wallets ----------------
PAYMENT_WALLETS = {
    "solana": "AGN5AWVWWY3XxfqSnVDPgzcZRWHTHaunbp1ZkE8htaQm",
    "ethereum": "0x7042ED5C8e93B5afAEC6eE6c03B83aaD61aC4446",
    "base": "0x7042ED5C8e93B5afAEC6eE6c03B83aaD61aC4446",
    "bsc": "0x7042ED5C8e93B5afAEC6eE6c03B83aaD61aC4446"
}

# ---------------- Trending Packages ----------------
# Rates (approximate Jan 2026): 1 SOL = 0.042 ETH / 0.148 BNB / $125 USD
TRENDING_PACKAGES = {
    "solana": {"3h": 2.5, "6h": 6.5, "12h": 10, "24h": 15},
    "ethereum": {"3h": 0.1, "6h": 0.27, "12h": 0.42, "24h": 0.63},
    "base": {"3h": 0.1, "6h": 0.27, "12h": 0.42, "24h": 0.63},
    "bsc": {"3h": 0.37, "6h": 0.96, "12h": 1.48, "24h": 2.22}
}

# ---------------- Payment Units ----------------
PAYMENT_UNITS = {
    "solana": "SOL",
    "ethereum": "ETH",
    "base": "ETH",
    "bsc": "BNB"
}

# ---------------- Chain ID mapping ----------------
CHAIN_IDS = {
    "solana": "solana",
    "ethereum": "ethereum",
    "bsc": "bsc",
    "base": "base"
}

# ---------------- Network Emojis ----------------
NETWORK_EMOJIS = {
    "solana": "💜",
    "ethereum": "💠",
    "bsc": "🟡",
    "base": "🧊"
}

# ---------------- Initialize Bot ----------------
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot, storage=storage)

# ---------------- States ----------------
class UserState(StatesGroup):
    waiting_for_ca = State()
    waiting_for_trend_package = State()
    waiting_for_payment = State()
    waiting_for_tx_id = State()
    trending_active = State()

# ---------------- Runtime session storage ----------------
# key = session_id (channel message id), value = dict with session details
TREND_SESSIONS = {}

# Store user-specific contract addresses (temporary in-memory)
user_contracts = {}

# thresholds to watch (percent)
THRESHOLDS = [10, 20, 30, 40, 50, 60, 70]

# poll interval in seconds for checking updates (every 3 minutes as requested).
POLL_INTERVAL = 180

# ---------------- Helpers ----------------
async def send_support_log(level: str, text: str, extra: dict = None):
    """Send a short log message to all SUPPORT_IDS and print log to console/file."""
    timestamp = datetime.utcnow().isoformat()
    body = f"[{level}] {timestamp}\n{text}"
    if extra:
        try:
            body += "\n\n" + json.dumps(extra, default=str)[:1900]
        except:
            pass

    # Send to support IDs (DM)
    for sid in SUPPORT_IDS:
        try:
            await bot.send_message(sid, body, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Could not send support log to {sid}: {e}")

    # Also log locally
    if level.upper() == "ERROR":
        logger.error(text)
    elif level.upper() == "WARN" or level.upper() == "WARNING":
        logger.warning(text)
    else:
        logger.info(text)

# ---------------- Utils (fetch/format/resize) ----------------
async def fetch_token_info_raw(token_address: str):
    """
    Fetch raw dexscreener response for a token address.
    Returns the JSON or None on failure.
    """
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"DexScreener API returned status {response.status} for {token_address}")
                    return None
    except Exception as e:
        await send_support_log("ERROR", f"Error fetching token info raw: {e}", {"url": url})
        return None

async def find_pair_for_chain(raw_data: dict, desired_chain: str):
    """
    Given DexScreener raw data, try to find the best pair for desired_chain.
    Returns the chosen pair dict or None.
    Also returns set of chains found in raw_data for reporting.
    """
    if not raw_data or 'pairs' not in raw_data:
        return None, set()

    pairs = raw_data.get('pairs', [])
    found_chains = set()
    desired_chain_lower = desired_chain.lower() if desired_chain else ""
    matching_pairs = []

    for p in pairs:
        # chainId or chain field may store identifiers like 'ethereum' or numeric IDs depending on API.
        chain_field = (str(p.get('chainId') or p.get('chain') or "")).lower()
        if chain_field:
            found_chains.add(chain_field)
        # consider a match if the chain_field contains the desired_chain string
        if desired_chain_lower and desired_chain_lower in chain_field:
            matching_pairs.append(p)

    if matching_pairs:
        # pick pair with max liquidity usd if available
        pair = max(matching_pairs, key=lambda x: float((x.get('liquidity', {}).get('usd', 0) or 0)))
        return pair, found_chains

    # no matching_pair found -> return None but give found_chains for diagnostics
    return None, found_chains

async def fetch_token_info(chain_id: str, token_address: str):
    """
    High-level fetch that returns a pair for the desired chain if available, otherwise None.
    """
    raw = await fetch_token_info_raw(token_address)
    pair, chains = await find_pair_for_chain(raw, chain_id)
    return pair, chains

def format_number(num):
    try:
        num = float(num)
        if num >= 1_000_000_000:
            return f"${num/1_000_000_000:.2f}B"
        elif num >= 1_000_000:
            return f"${num/1_000_000:.2f}M"
        elif num >= 1_000:
            return f"${num/1_000:.2f}K"
        else:
            return f"${num:.2f}"
    except:
        return "N/A"

def format_percentage(num):
    try:
        num = float(num)
        if num > 0: return f"🟢 +{num:.2f}%"
        elif num < 0: return f"🔴 {num:.2f}%"
        else: return f"⚪ {num:.2f}%"
    except:
        return "⚪ N/A"

async def resize_image(url, size=(300,300)):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                img_bytes = await resp.read()
                img = Image.open(BytesIO(img_bytes))

                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    if img.mode in ('RGBA', 'LA'):
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background

                # Create square canvas with padding
                max_dim = max(img.size)
                square_img = Image.new('RGB', (max_dim, max_dim), (255, 255, 255))
                offset = ((max_dim - img.size[0]) // 2, (max_dim - img.size[1]) // 2)
                square_img.paste(img, offset)

                # Resize to target size
                square_img.thumbnail(size, Image.Resampling.LANCZOS)

                bio = BytesIO()
                bio.name = "logo.png"
                square_img.save(bio, format="PNG", quality=95)
                bio.seek(0)
                return bio
    except Exception as e:
        await send_support_log("ERROR", f"Error resizing image: {e}", {"url": url})
        return None

def create_professional_message(pair_data, chain_name):
    if not pair_data:
        return None, None, None
    base_token = pair_data.get('baseToken',{})
    price_usd = pair_data.get('priceUsd','N/A')
    price_change_h24 = pair_data.get('priceChange',{}).get('h24',0)
    price_change_h6 = pair_data.get('priceChange',{}).get('h6',0)
    price_change_h1 = pair_data.get('priceChange',{}).get('h1',0)
    volume_24h = pair_data.get('volume',{}).get('h24',0)
    liquidity = pair_data.get('liquidity',{}).get('usd',0)
    fdv = pair_data.get('fdv',0)
    market_cap = pair_data.get('marketCap',0)
    pair_chain = pair_data.get('chainId','Unknown')
    dex_name = pair_data.get('dexId','Unknown')
    pair_address = pair_data.get('pairAddress','')
    logo_url = pair_data.get('info',{}).get('imageUrl') or base_token.get('imageUrl')

    # Price formatting
    try:
        price_float = float(price_usd)
        if price_float < 0.000001: price_display = f"${price_float:.10f}"
        elif price_float < 0.01: price_display = f"${price_float:.8f}"
        else: price_display = f"${price_float:.6f}"
    except: price_display = "N/A"

    network_emoji = NETWORK_EMOJIS.get(str(pair_chain).lower(),"🔗")

    message = (
        f"╔══════════════════════════╗\n"
        f"     <b>🎯 TOKEN ANALYTICS</b>\n"
        f"╚══════════════════════════╝\n\n"
        f"{network_emoji} <b>{base_token.get('symbol','Unknown')}</b> • {base_token.get('name','Unknown')}\n"
        f"🏦 <b>DEX:</b> {dex_name.upper()}\n"
        f"⛓️ <b>Chain:</b> {pair_chain.upper()}\n\n"
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  <b>💰 PRICE INFORMATION</b>   ┃\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
        f"💵 <b>Current Price:</b> {price_display}\n\n"
        f"📊 <b>Price Changes:</b>\n"
        f"  • 1H:  {format_percentage(price_change_h1)}\n"
        f"  • 6H:  {format_percentage(price_change_h6)}\n"
        f"  • 24H: {format_percentage(price_change_h24)}\n\n"
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  <b>📈 MARKET STATISTICS</b>   ┃\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
        f"💎 <b>Market Cap:</b> {format_number(market_cap)}\n"
        f"🌊 <b>Liquidity:</b> {format_number(liquidity)}\n"
        f"📊 <b>24h Volume:</b> {format_number(volume_24h)}\n"
        f"💹 <b>FDV:</b> {format_number(fdv)}\n\n"
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  <b>📝 CONTRACT INFO</b>       ┃\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
        f"<code>{base_token.get('address','N/A')}</code>\n"
    )
    chart_url = f"https://dexscreener.com/{pair_chain}/{pair_address}" if pair_address else None
    return logo_url, message, chart_url

# ---------------- Start Command ----------------
@dp.message_handler(commands=['start'], state='*')
async def start_command(message: types.Message, state: FSMContext):
    await state.finish()
    user_first = message.from_user.first_name or "there"
    start_text = (
        f"╔══════════════════════════╗\n"
        f"  <b>🌟 DEXTOOLS TRENDING BOT 🌟</b>\n"
        f"╚══════════════════════════╝\n\n"
        f"👋 Welcome, <b>{user_first}</b>!\n\n"
        f"Your professional multi-chain DEX analytics platform.\n\n"
        f"<b>📊 Track & Trend Across:</b>\n"
        f"💜 Solana  |  💠 Ethereum  |  🟡 BSC\n"
        f"🧊 Base\n\n"
        f"Select a network below to get started! 👇"
    )
    buttons = [
        [InlineKeyboardButton("💜 Solana", callback_data="select_solana")],
        [InlineKeyboardButton("💠 Ethereum", callback_data="select_ethereum")],
        [InlineKeyboardButton("🟡 BSC", callback_data="select_bsc")],
        [InlineKeyboardButton("🧊 Base", callback_data="select_base")],
        [InlineKeyboardButton("💰 Prices", callback_data="show_prices")],
        [InlineKeyboardButton("🛠️ Support", callback_data="support")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(start_text, reply_markup=keyboard)

# ---------------- Network Selection ----------------
@dp.callback_query_handler(lambda c: c.data.startswith("select_"), state='*')
async def handle_network_selection(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    network = callback_query.data.split("_")[1]
    await state.update_data(selected_network=network)
    await UserState.waiting_for_ca.set()
    network_emoji = NETWORK_EMOJIS.get(network,"🔗")
    await callback_query.message.answer(
        f"✅ <b>{network_emoji} {network.upper()} Network Selected</b>\n\n"
        f"Please send the <b>Contract Address (CA)</b> of the token you want to analyze."
    )

# ---------------- Contract Address Handler ----------------
@dp.message_handler(state=UserState.waiting_for_ca)
async def handle_contract_address(message: types.Message, state: FSMContext):
    ca = message.text.strip()
    user_data = await state.get_data()
    network = user_data.get('selected_network','ethereum')

    waiting_msg = await message.answer(f"🔍 <b>Analyzing Token Data...</b>\n<code>{ca}</code>\n⏳ Fetching real-time data...")

    try:
        chain_id = CHAIN_IDS.get(network, network)
        pair_data, found_chains = await fetch_token_info(chain_id, ca)

        # Token not found at all
        if not pair_data:
            # If dexscreener returned some chains but not the desired one, let the user know
            if found_chains:
                found_list = ", ".join(sorted(found_chains))
                await waiting_msg.edit_text(
                    f"⚠️ Token found on DexScreener but not for the selected network ({network.upper()}).\n"
                    f"Detected chains for this CA: {found_list}\n\n"
                    f"Please check the contract address and network, then try again."
                )
            else:
                await waiting_msg.edit_text("❌ Token not found on DexScreener. Please check the contract address and try again.")
            return

        # Create the professional message and continue
        logo_url, token_info, chart_url = create_professional_message(pair_data, network)

        if not token_info:
            await waiting_msg.edit_text("❌ <b>Unable to format token info.</b>")
            return

        buttons = []
        if chart_url:
            buttons.append([InlineKeyboardButton("📊 View Live Chart", url=chart_url)])
        buttons.append([InlineKeyboardButton("🚀 Start Trending", callback_data="start_trending")])
        buttons.append([InlineKeyboardButton("🔄 Analyze Another", callback_data=f"select_{network}")])
        buttons.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"),
                        InlineKeyboardButton("💬 Support", callback_data="support")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        if logo_url:
            img = await resize_image(logo_url)
            if img:
                await waiting_msg.delete()
                await message.answer_photo(photo=img, caption=token_info + POST_FOOTER, reply_markup=keyboard)
            else:
                await waiting_msg.edit_text(token_info + POST_FOOTER, reply_markup=keyboard)
        else:
            await waiting_msg.edit_text(token_info + POST_FOOTER, reply_markup=keyboard)

        # Save contract for the user session
        await state.update_data(contract_address=ca)
        user_contracts[message.from_user.id] = ca
        await UserState.waiting_for_trend_package.set()

    except Exception as e:
        await waiting_msg.edit_text(f"❌ Error fetching token info: {e}")
        await send_support_log("ERROR", f"Error in handle_contract_address: {e}", {"ca": ca})

# ---------------- Start Trending Callback ----------------
@dp.callback_query_handler(lambda c: c.data == "start_trending", state=UserState.waiting_for_trend_package)
async def handle_start_trending(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    user_data = await state.get_data()
    network = user_data.get("selected_network","ethereum")
    packages = TRENDING_PACKAGES.get(network,{})

    # Show packages to user
    buttons = [
        [InlineKeyboardButton(f"3H", callback_data="trend_3h")],
        [InlineKeyboardButton(f"6H", callback_data="trend_6h")],
        [InlineKeyboardButton(f"12H", callback_data="trend_12h")],
        [InlineKeyboardButton(f"24H", callback_data="trend_24h")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback_query.message.answer("📦 Select Trending Package:", reply_markup=keyboard)

# ---------------- Handle Trending Selection ----------------
@dp.callback_query_handler(lambda c: c.data.startswith("trend_"), state=UserState.waiting_for_trend_package)
async def handle_trend_package_selection(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()

    user_data = await state.get_data()
    network = user_data.get("selected_network", "ethereum")

    duration_map = {"trend_3h": "3h", "trend_6h": "6h", "trend_12h": "12h", "trend_24h": "24h"}
    package = callback_query.data
    duration_label = duration_map.get(package, "3h")

    # Get payment info
    payment_wallet = PAYMENT_WALLETS.get(network, "")
    packages = TRENDING_PACKAGES.get(network, {})
    amount = packages.get(duration_label, 0)

    network_emoji = NETWORK_EMOJIS.get(network, "🔗")

    # Store selected package info
    await state.update_data(selected_package=duration_label, payment_amount=amount)

    # Show payment info to user with "Paid" button
    payment_unit = PAYMENT_UNITS.get(network, "SOL")
    payment_message = (
        f"╔══════════════════════════╗\n"
        f"     <b>💳 PAYMENT DETAILS</b>\n"
        f"╚══════════════════════════╝\n\n"
        f"{network_emoji} <b>Network:</b> {network.upper()}\n"
        f"⏰ <b>Package:</b> {duration_label.upper()}\n"
        f"💰 <b>Amount:</b> {amount} {payment_unit}\n\n"
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  <b>📝 PAYMENT WALLET</b>      ┃\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
        f"<code>{payment_wallet}</code>\n\n"
        f"<b>📌 Instructions:</b>\n"
        f"1️⃣ Send <b>{amount} {payment_unit}</b> to the wallet above\n"
        f"2️⃣ Click the <b>Paid</b> button below to provide your <b>Transaction ID / Hash</b>\n"
    )

    paid_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✅ Paid", callback_data="payment_paid")]
    ])

    await callback_query.message.answer(payment_message, reply_markup=paid_button)
    await UserState.waiting_for_payment.set()

# ---------------- Handle Payment Confirmation ----------------
@dp.callback_query_handler(lambda c: c.data == "payment_paid", state=UserState.waiting_for_payment)
async def handle_payment_paid(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await callback_query.message.answer("📩 Please send the <b>Transaction ID (TX ID) / Hash</b> of your payment.")
    await UserState.waiting_for_tx_id.set()

# ---------------- Handle TX ID Submission ----------------
@dp.message_handler(state=UserState.waiting_for_tx_id)
async def handle_tx_id_submission(message: types.Message, state: FSMContext):
    tx_id = message.text.strip()
    user_data = await state.get_data()
    network = user_data.get("selected_network", "ethereum")
    contract_address = user_data.get("contract_address", "N/A")
    selected_package = user_data.get("selected_package", "3h")
    payment_amount = user_data.get("payment_amount", 0)
    payment_unit = PAYMENT_UNITS.get(network, "SOL")

    network_emoji = NETWORK_EMOJIS.get(network, "🔗")
    username = message.from_user.username or "Unknown"
    user_id = message.from_user.id
    user_full_name = message.from_user.full_name or "Unknown"

    # Notify support team with activation button
    try:
        support_notification = (
            f"╔══════════════════════════╗\n"
            f"  <b>🚀 PAYMENT SUBMITTED</b>\n"
            f"╚══════════════════════════╝\n\n"
            f"👤 <b>User:</b> {user_full_name} (@{username})\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n\n"
            f"{network_emoji} <b>Network:</b> {network.upper()}\n"
            f"📝 <b>Contract:</b> <code>{contract_address}</code>\n"
            f"⏰ <b>Package:</b> {selected_package.upper()}\n"
            f"💰 <b>Amount:</b> {payment_amount} {payment_unit}\n"
            f"🔗 <b>TX ID:</b> <code>{tx_id}</code>\n\n"
            f"<b>Please verify the transaction and activate trending below.</b>"
        )

        # Add activation & reject buttons for support
        activate_button = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton("✅ Activate", callback_data=f"activate_{user_id}_{network}_{selected_package}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}_{network}_{selected_package}")
            ]
        ])

        # Send to optional support chat if provided, else to first SUPPORT_ID
        if SUPPORT_CHAT:
            try:
                await bot.send_message(int(SUPPORT_CHAT), support_notification, reply_markup=activate_button)
            except Exception as e:
                logger.warning("Failed to send support notification to SUPPORT_CHAT: %s", e)
                for sid in SUPPORT_IDS:
                    try:
                        await bot.send_message(sid, support_notification, reply_markup=activate_button)
                    except:
                        pass
        else:
            for sid in SUPPORT_IDS:
                try:
                    await bot.send_message(sid, support_notification, reply_markup=activate_button)
                except Exception as e:
                    logger.warning("Could not send notification to support %s: %s", sid, e)
    except Exception as e:
        logger.exception("Error preparing support notification: %s", e)

    # Confirm receipt to user
    confirmation_msg = (
        "✅ <b>Transaction Received!</b>\n\n"
        "Our team is currently verifying your payment. Once confirmed, your trending session will be activated automatically.\n\n"
        "⏳ <b>Estimated time:</b> 5-15 minutes."
    )
    await message.answer(confirmation_msg)
    await state.finish()

# ---------------- Reject Payment (Support Only) ----------------
@dp.callback_query_handler(lambda c: c.data.startswith("reject_"))
async def handle_reject_payment(callback_query: types.CallbackQuery):
    """Support-only rejection: notify user and cancel pending data."""
    if callback_query.from_user.id not in SUPPORT_IDS:
        await callback_query.answer("🚫 You are not authorized to reject payments.", show_alert=True)
        return

    await callback_query.answer()
    parts = callback_query.data.split("_")
    if len(parts) < 4:
        await callback_query.message.answer("❌ Invalid reject data.")
        return

    try:
        target_user_id = int(parts[1])
    except Exception as e:
        await callback_query.message.answer(f"❌ Failed to parse reject data: {e}")
        return

    # notify user
    try:
        await bot.send_message(target_user_id, "❌ Your payment was not approved by support. Please contact support for assistance.")
    except:
        pass

    # update support message to reflect rejection
    try:
        await callback_query.message.edit_text(callback_query.message.text + f"\n\n❌ <b>Rejected by {callback_query.from_user.full_name}</b>")
    except:
        pass

    await send_support_log("INFO", f"Payment rejected for user {target_user_id}", {"by": callback_query.from_user.id})

# ---------------- Activate Trending (Support Only) ----------------
@dp.callback_query_handler(lambda c: c.data.startswith("activate_"))
async def handle_activate_trending(callback_query: types.CallbackQuery):
    """Support-only activation: create channel post, start monitor task."""
    # authorize
    if callback_query.from_user.id not in SUPPORT_IDS:
        await callback_query.answer("🚫 You are not authorized to activate trends.", show_alert=True)
        return

    await callback_query.answer()

    # Parse callback data: activate_{user_id}_{network}_{package}
    parts = callback_query.data.split("_")
    if len(parts) < 4:
        await callback_query.message.answer("❌ Invalid activation data.")
        return

    try:
        target_user_id = int(parts[1])
        network = parts[2]
        package = parts[3]  # e.g., "3h", "12h", "24h"
    except Exception as e:
        await callback_query.message.answer(f"❌ Failed to parse activation data: {e}")
        return

    # Determine duration
    # Uses your existing mapping semantics (hours). Adjust if you change package keys.
    duration_map = {"3h": 3, "6h": 6, "12h": 12, "24h": 24}
    hours = duration_map.get(package.lower(), 3)
    duration = timedelta(hours=hours)
    end_time = datetime.utcnow() + duration

    # Recover contract address from user's FSM storage
    async with dp.current_state(user=target_user_id).proxy() as user_data:
        contract_address = user_data.get("contract_address")

    if not contract_address:
        # fallback to in-memory dict if present
        contract_address = user_contracts.get(target_user_id)

    if not contract_address:
        await callback_query.message.answer("❌ No contract address found for this user (they must analyze a token first).")
        return

    # Fetch initial token info (validate again)
    pair_data, _ = await fetch_token_info(CHAIN_IDS.get(network, network), contract_address)
    if not pair_data:
        await callback_query.message.answer("❌ Could not fetch token info from DexScreener.")
        return

    logo_url, token_info, chart_url = create_professional_message(pair_data, network)

    # baseline price (float)
    try:
        baseline = float(pair_data.get('priceUsd') or pair_data.get('price') or 0)
    except:
        baseline = 0.0

    # Compose the "Trending Started" header message text
    base_token = pair_data.get('baseToken', {})
    symbol = base_token.get('symbol', 'TOKEN')
    started_text = (
        f"🔥 <b>TRENDING STARTED FOR {symbol}</b>\n\n"
        f"🪙 <b>Contract:</b> <code>{contract_address}</code>\n"
        f"🌐 <b>Network:</b> {network.upper()}\n"
        f"⏰ <b>Duration:</b> {package.upper()}\n"
        f"💵 <b>Baseline Price:</b> ${baseline}\n\n"
        f"📈 Tracking price action and alerting for new highs and dumps (±10%..±70%)."
        f"{POST_FOOTER}"
    )

    buttons = []
    # Social Links extraction
    social_buttons = []
    social_links = pair_data.get('info', {}).get('socials', [])
    websites = pair_data.get('info', {}).get('websites', [])

    for site in websites:
        label = site.get('label', 'Website')
        url = site.get('url')
        if url:
            social_buttons.append(InlineKeyboardButton(f"🌐 {label}", url=url))

    for social in social_links:
        s_type = social.get('type', '').lower()
        url = social.get('url')
        if not url: continue

        if 'telegram' in s_type or 't.me' in url:
            social_buttons.append(InlineKeyboardButton("✈️ Telegram", url=url))
        elif 'twitter' in s_type or 'x.com' in url:
            social_buttons.append(InlineKeyboardButton("🐦 Twitter/X", url=url))
        elif 'discord' in s_type:
            social_buttons.append(InlineKeyboardButton("👾 Discord", url=url))

    # Add socials to keyboard in rows of 2
    for i in range(0, len(social_buttons), 2):
        buttons.append(social_buttons[i:i+2])

    if chart_url:
        buttons.append([InlineKeyboardButton("📊 View Chart", url=chart_url)])
    buttons.append([InlineKeyboardButton("🌐 DexTools Trending Bot • 100K Monthly Subscribers", url="https://t.me/DEXToolsTrend_Support")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Post to channel (photo if logo available)
    try:
        if logo_url:
            img = await resize_image(logo_url)
            if img:
                channel_msg = await bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=img,
                    caption=started_text,
                    reply_markup=keyboard
                )
            else:
                channel_msg = await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=started_text,
                    reply_markup=keyboard
                )
        else:
            channel_msg = await bot.send_message(
                chat_id=CHANNEL_ID,
                text=started_text,
                reply_markup=keyboard
            )
    except Exception as e:
        error_msg = str(e)
        if "chat not found" in error_msg.lower():
            await callback_query.message.answer(f"❌ <b>Activation Error:</b> Channel not found.\n\nPlease ensure the bot is added to the channel <code>{CHANNEL_ID}</code> as an <b>Administrator</b> with posting permissions.")
        else:
            await callback_query.message.answer(f"❌ <b>Failed to post to channel:</b> {e}")
        await send_support_log("ERROR", f"Failed to post trending started: {e}", {"contract": contract_address, "channel_id": CHANNEL_ID})
        return

    # Build session and store it
    session = {
        "user_id": target_user_id,
        "network": network,
        "contract": contract_address,
        "baseline": baseline,
        "start_time": datetime.utcnow(),
        "end_time": end_time,
        "channel_message": {"chat_id": CHANNEL_ID, "message_id": channel_msg.message_id, "is_photo": bool(logo_url)},
        "chart_url": chart_url,
        "logo_url": logo_url,
        "thresholds_triggered": set(),  # e.g., "high_10", "dump_20"
        "active": True
    }
    TREND_SESSIONS[channel_msg.message_id] = session

    # Notify user
    try:
        await bot.send_message(
            target_user_id,
            f"🎉 <b>TRENDING ACTIVATED!</b>\n\n"
            f"{NETWORK_EMOJIS.get(network, '')} <b>Network:</b> {network.upper()}\n"
            f"⏰ <b>Duration:</b> {package.upper()}\n\n"
            f"Your token is now live on the DexTools Trending Bot Channel! 🚀"
        )
    except Exception as e:
        logger.warning("Failed to notify target user: %s", e)

    # Log to support (activation)
    await send_support_log("INFO", f"Activated trending for {symbol}", {
        "user_id": target_user_id,
        "contract": contract_address,
        "network": network,
        "baseline": baseline,
        "channel_message_id": channel_msg.message_id
    })

    # Update support UI message text for admin in the activation button message
    try:
        await callback_query.message.edit_text(
            callback_query.message.text + f"\n\n✅ <b>Activated by {callback_query.from_user.full_name}</b>"
        )
    except:
        pass

    # Start background monitor task
    asyncio.create_task(monitor_trending_session(channel_msg.message_id))

async def monitor_trending_session(session_msg_id):
    """Monitor one trending session until end_time; post alerts only when thresholds crossed."""
    session = TREND_SESSIONS.get(session_msg_id)
    if not session:
        return

    try:
        while session["active"] and datetime.utcnow() < session["end_time"]:
            # Fetch latest data
            pair_data, _ = await fetch_token_info(CHAIN_IDS.get(session["network"], session["network"]), session["contract"])
            if pair_data:
                logo_url, token_info, chart_url = create_professional_message(pair_data, session["network"])

                # compute price and percent change vs baseline
                try:
                    current_price = float(pair_data.get('priceUsd') or pair_data.get('price') or 0.0)
                except:
                    current_price = 0.0

                baseline = float(session.get("baseline") or 0.0)
                pct_change = 0.0
                if baseline and current_price:
                    pct_change = ((current_price - baseline) / baseline) * 100.0

                # Prepare updated pinned message caption/text
                caption_extra = f"\n\n<b>Baseline:</b> {baseline}\n<b>Current:</b> {current_price}\n<b>Change:</b> {pct_change:.2f}%"
                caption_with_footer = f"{token_info}{caption_extra}{POST_FOOTER}"

                # edit the main channel post
                try:
                    if session["channel_message"]["is_photo"]:
                        await bot.edit_message_caption(
                            chat_id=session["channel_message"]["chat_id"],
                            message_id=session["channel_message"]["message_id"],
                            caption=caption_with_footer,
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton("📊 View Chart", url=session.get("chart_url") or chart_url)]
                            ]) if (session.get("chart_url") or chart_url) else None
                        )
                    else:
                        await bot.edit_message_text(
                            chat_id=session["channel_message"]["chat_id"],
                            message_id=session["channel_message"]["message_id"],
                            text=caption_with_footer,
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton("📊 View Chart", url=session.get("chart_url") or chart_url)]
                            ]) if (session.get("chart_url") or chart_url) else None
                        )
                except Exception as e:
                    logger.debug("Failed to edit channel message: %s", e)

                # Send debug update to support (every poll)
                await send_support_log("DEBUG", f"Update for {pair_data.get('baseToken',{}).get('symbol','TOKEN')}: price={current_price}, change={pct_change:.2f}%", {
                    "contract": session["contract"],
                    "network": session["network"],
                    "current_price": current_price,
                    "pct_change": pct_change,
                    "time": datetime.utcnow().isoformat()
                })

                # Check thresholds for highs and dumps (10..70)
                # For highs
                for th in THRESHOLDS:
                    key = f"high_{th}"
                    if key not in session["thresholds_triggered"]:
                        if pct_change >= th:
                            session["thresholds_triggered"].add(key)
                            await post_threshold_alert(session, pair_data, current_price, pct_change, th, is_high=True)

                # For dumps (negative)
                for th in THRESHOLDS:
                    key = f"dump_{th}"
                    if key not in session["thresholds_triggered"]:
                        if pct_change <= -th:
                            session["thresholds_triggered"].add(key)
                            await post_threshold_alert(session, pair_data, current_price, pct_change, th, is_high=False)

            # small sleep between polls
            await asyncio.sleep(POLL_INTERVAL)

        # session ended
        session["active"] = False
        # notify user and support
        try:
            await bot.send_message(
                session["user_id"],
                "✅ <b>TRENDING COMPLETED!</b>\n\nYour token's trending session has ended. Thanks for using DexTools Trending Bot! 🚀"
            )
        except Exception as e:
            logger.warning("Failed to notify user about completion: %s", e)

        # post "Trending Completed" to channel
        try:
            end_text = (
                f"✅ <b>TRENDING ENDED FOR {session['contract']}</b>\n\n"
                f"Thanks for using DexTools Trending Bot!\n"
                f"{POST_FOOTER}"
            )
            await bot.send_message(session["channel_message"]["chat_id"], end_text)
        except Exception as e:
            logger.debug("Failed to send trending completed to channel: %s", e)

        # notify support(s)
        complete_msg = {
            "event": "Trending Completed",
            "user_id": session['user_id'],
            "contract": session['contract'],
            "network": session['network'],
            "started": str(session['start_time']),
            "ended": str(session['end_time'])
        }
        await send_support_log("INFO", "Trending session completed", complete_msg)

    except Exception as e:
        await send_support_log("ERROR", f"Error in monitor_trending_session: {e}", {"session_id": session_msg_id})
    finally:
        # cleanup session entry
        if session_msg_id in TREND_SESSIONS:
            del TREND_SESSIONS[session_msg_id]

async def post_threshold_alert(session, pair_data, current_price, pct_change, threshold, is_high=True):
    """Post an alert to the channel with logo + stats when a threshold is crossed."""
    symbol = pair_data.get('baseToken',{}).get('symbol', 'TOKEN')
    name = pair_data.get('baseToken',{}).get('name', '')
    chart_url = session.get("chart_url") or (pair_data.get('pairAddress') and f"https://dexscreener.com/{pair_data.get('chainId')}/{pair_data.get('pairAddress')}")
    logo_url = session.get("logo_url") or pair_data.get('info',{}).get('imageUrl') or pair_data.get('baseToken',{}).get('imageUrl')

    if is_high:
        title = f"🚀 NEW HIGH +{pct_change:.2f}% on {symbol} (≥ +{threshold}%)"
    else:
        title = f"💥 BIG DUMP {pct_change:.2f}% on {symbol} (≤ -{threshold}%)"

    # Build alert message
    msg_text = (
        f"{title}\n\n"
        f"<b>{symbol}</b> • {name}\n"
        f"💵 <b>Price:</b> ${current_price:.8f}\n"
        f"📈 <b>Change vs baseline:</b> {pct_change:.2f}%\n"
    )
    if pair_data.get('liquidity',{}):
        msg_text += f"🌊 <b>Liquidity:</b> {format_number(pair_data.get('liquidity',{}).get('usd',0))}\n"
    if pair_data.get('volume',{}):
        msg_text += f"📊 <b>24h Volume:</b> {format_number(pair_data.get('volume',{}).get('h24',0))}\n"
    if chart_url:
        msg_text += f"\n📊 <a href='{chart_url}'>View chart on DexScreener</a>"

    # include powered by footer
    msg_text += f"\n\n🌐 <b>Powered by DexTools Trending Bot</b>{POST_FOOTER}"

    # send photo alert if logo exists
    try:
        if logo_url:
            img = await resize_image(logo_url)
            if img:
                await bot.send_photo(chat_id=CHANNEL_ID, photo=img, caption=msg_text, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=CHANNEL_ID, text=msg_text, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=CHANNEL_ID, text=msg_text, parse_mode="HTML")

        # send debug copy to support about this alert
        await send_support_log("ALERT", f"{'HIGH' if is_high else 'DUMP'} triggered for {symbol}", {
            "contract": session["contract"],
            "threshold": threshold,
            "pct_change": pct_change,
            "current_price": current_price
        })

    except Exception as e:
        await send_support_log("ERROR", f"Failed to send threshold alert: {e}", {"contract": session.get("contract")})

# ---------------- Main Menu & other handlers (unchanged) ----------------
@dp.callback_query_handler(lambda c: c.data == "main_menu", state='*')
async def handle_main_menu(callback_query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await callback_query.answer()
    user_first = callback_query.from_user.first_name or "there"
    start_text = f"╔══════════════════════════╗\n  <b>🌟 DEXTOOLS TRENDING BOT 🌟</b>\n╚══════════════════════════╝\n\n👋 Welcome back, <b>{user_first}</b>!\nSelect a network below to get started! 👇"
    buttons = [
        [InlineKeyboardButton("💜 Solana", callback_data="select_solana")],
        [InlineKeyboardButton("💠 Ethereum", callback_data="select_ethereum")],
        [InlineKeyboardButton("🟡 BSC", callback_data="select_bsc")],
        [InlineKeyboardButton("🧊 Base", callback_data="select_base")],
        [InlineKeyboardButton("🛠️ Support", callback_data="support")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback_query.message.edit_text(start_text, reply_markup=keyboard)
    except:
        await callback_query.message.answer(start_text, reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == "show_prices", state='*')
async def handle_show_prices(callback_query: types.CallbackQuery):
    await callback_query.answer()

    prices_text = (
        f"╔══════════════════════════╗\n"
        f"     <b>💰 TRENDING PRICES</b>\n"
        f"╚══════════════════════════╝\n\n"
        f"💜 <b>Solana:</b>\n"
        f"  • 3H: 2.5 SOL | 6H: 6.5 SOL\n"
        f"  • 12H: 10 SOL | 24H: 15 SOL\n\n"
        f"💠 <b>Ethereum / Base:</b>\n"
        f"  • 3H: 0.10 ETH | 6H: 0.27 ETH\n"
        f"  • 12H: 0.42 ETH | 24H: 0.63 ETH\n\n"
        f"🟡 <b>BSC:</b>\n"
        f"  • 3H: 0.37 BNB | 6H: 0.96 BNB\n"
        f"  • 12H: 1.48 BNB | 24H: 2.22 BNB\n\n"
        f"🚀 <i>Prices are fixed equivalents!</i>\n\n"
        f"<b>📌 How It Works:</b>\n"
        f"1️⃣ Select a network and provide token CA\n"
        f"2️⃣ Choose trending package duration\n"
        f"3️⃣ Make payment and send TX ID to support\n"
        f"4️⃣ Your token goes trending! 🚀"
    )

    back_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
    ])

    await callback_query.message.answer(prices_text, reply_markup=back_button)

@dp.callback_query_handler(lambda c: c.data == "support", state='*')
async def handle_support(callback_query: types.CallbackQuery):
    await callback_query.answer()
    support_text = (
        "🛠 <b>DexTools Trending Bot Support</b>\n\n"
        "If you need help, contact our team below:\n"
        "📩 <a href='https://t.me/DEXToolsTrend_Support'>Contact Support</a>\n\n"
        "We'll respond as quickly as possible!"
    )
    await callback_query.message.answer(support_text, disable_web_page_preview=True)

# ---------------- Run Bot ----------------
async def on_startup(dp):
    commands = [
        types.BotCommand(command="/start", description="🏠 Start the bot"),
        types.BotCommand(command="/help", description="📘 How to use the bot")
    ]
    await bot.set_my_commands(commands)
    logger.info("🚀 DexTools Trending Bot is now running...")
    await send_support_log("INFO", "Bot started", {"time": datetime.utcnow().isoformat()})

@dp.message_handler(commands=['help'], state='*')
async def help_command(message: types.Message):
    help_text = (
        "📘 <b>How DexTools Trending Bot Works:</b>\n\n"
        "1️⃣ Choose your preferred blockchain network.\n"
        "2️⃣ Provide a token contract address (CA).\n"
        "3️⃣ The bot fetches live data from DEX sources.\n"
        "4️⃣ Use the trending system to boost token visibility.\n\n"
        "Need more assistance? Tap <b>Support</b> below."
    )
    await message.answer(help_text)

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
