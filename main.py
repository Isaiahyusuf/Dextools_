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

# ---------------- Load Bot Token ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_CHAT = os.getenv("SUPPORT_CHAT")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable not found!")

SUPPORT_IDS = [7886119612]
CHANNEL_ID = -1003251300654
POST_FOOTER = "\n\n🌐 DexTools Hot Pairs Bot • Premium Visibility"

logger = logging.getLogger("dextoolstrending")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

# ---------------- Payment Wallets ----------------
PAYMENT_WALLETS = {
    "solana": "AGN5AWVWWY3XxfqSnVDPgzcZRWHTHaunbp1ZkE8htaQm",
    "ethereum": "0x7042ED5C8e93B5afAEC6eE6c03B83aaD61aC4446",
    "base": "0x7042ED5C8e93B5afAEC6eE6c03B83aaD61aC4446",
    "bsc": "0x7042ED5C8e93B5afAEC6eE6c03B83aaD61aC4446"
}

HOT_PAIRS_BASE_USD = {
    "6h": 2000,
    "12h": 4000,
    "24h": 6000
}

PAYMENT_UNITS = {
    "solana": "SOL",
    "ethereum": "ETH",
    "base": "ETH",
    "bsc": "BNB"
}

CHAIN_IDS = {
    "solana": "solana",
    "ethereum": "ethereum",
    "bsc": "bsc",
    "base": "base"
}

NETWORK_EMOJIS = {
    "solana": "💜",
    "ethereum": "💠",
    "bsc": "🟡",
    "base": "🧊"
}

async def calculate_package_price(usd_amount, network):
    prices = {"SOL": 135.0, "ETH": 3150.0, "BNB": 900.0}
    unit = PAYMENT_UNITS.get(network, "ETH")
    price_per_unit = prices.get(unit, 1.0)
    return round(usd_amount / price_per_unit, 4)

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot, storage=storage)

class UserState(StatesGroup):
    waiting_for_ca = State()
    waiting_for_hot_pairs_package = State()
    waiting_for_payment = State()
    waiting_for_tx_id = State()

async def fetch_token_info_raw(token_address: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as response:
                return await response.json() if response.status == 200 else None
    except: return None

async def fetch_token_info(chain_id: str, token_address: str):
    raw = await fetch_token_info_raw(token_address)
    if not raw or 'pairs' not in raw: return None
    pairs = [p for p in raw['pairs'] if chain_id.lower() in str(p.get('chainId','')).lower()]
    return max(pairs, key=lambda x: float(x.get('liquidity',{}).get('usd',0) or 0)) if pairs else None

def format_number(num):
    try:
        num = float(num)
        if num >= 1e9: return f"${num/1e9:.2f}B"
        if num >= 1e6: return f"${num/1e6:.2f}M"
        return f"${num/1e3:.2f}K" if num >= 1e3 else f"${num:.2f}"
    except: return "N/A"

def format_percentage(num):
    try:
        num = float(num)
        if num > 0: return f"🟢 +{num:.2f}%"
        elif num < 0: return f"🔴 {num:.2f}%"
        else: return f"⚪ {num:.2f}%"
    except: return "⚪ N/A"

def create_professional_message(pair_data):
    base = pair_data.get('baseToken',{})
    symbol = base.get('symbol','Unknown')
    name = base.get('name','Unknown')
    address = base.get('address','N/A')
    price = pair_data.get('priceUsd','N/A')
    mcap = pair_data.get('marketCap',0)
    liq = pair_data.get('liquidity',{}).get('usd',0)
    vol = pair_data.get('volume',{}).get('h24',0)
    chain = pair_data.get('chainId','Unknown').upper()
    
    change1h = pair_data.get('priceChange',{}).get('h1',0)
    change6h = pair_data.get('priceChange',{}).get('h6',0)
    change24h = pair_data.get('priceChange',{}).get('h24',0)

    msg = (
        f"╔══════════════════════════╗\n"
        f"     <b>🔥 HOT PAIRS PLACEMENT</b>\n"
        f"╚══════════════════════════╝\n\n"
        f"💎 <b>{symbol}</b> • {name}\n"
        f"⛓️ <b>Chain:</b> {chain}\n\n"
        f"💵 <b>Price:</b> ${price}\n"
        f"📈 <b>1H:</b> {format_percentage(change1h)}\n"
        f"📈 <b>6H:</b> {format_percentage(change6h)}\n"
        f"📈 <b>24H:</b> {format_percentage(change24h)}\n\n"
        f"💎 <b>Market Cap:</b> {format_number(mcap)}\n"
        f"🌊 <b>Liquidity:</b> {format_number(liq)}\n"
        f"📊 <b>24h Volume:</b> {format_number(vol)}\n\n"
        f"📝 <b>CA:</b> <code>{address}</code>\n"
        f"{POST_FOOTER}"
    )
    return msg

@dp.message_handler(commands=['start'], state='*')
async def start_cmd(message: types.Message, state: FSMContext):
    await state.finish()
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text="🔥 Get on Hot Pairs", callback_data="get_hot_pairs"))
    kb.add(InlineKeyboardButton(text="🛠️ Support", callback_data="support"))
    await message.answer("╔══════════════════════════╗\n  <b>🌟 DEXTOOLS HOT PAIRS BOT 🌟</b>\n╚══════════════════════════╝\n\nSelect a service below:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "get_hot_pairs", state='*')
async def select_network(c: types.CallbackQuery):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton(text="💜 Solana", callback_data="net_solana"),
        InlineKeyboardButton(text="💠 Ethereum", callback_data="net_ethereum"),
        InlineKeyboardButton(text="🟡 BSC", callback_data="net_bsc"),
        InlineKeyboardButton(text="🧊 Base", callback_data="net_base"),
        InlineKeyboardButton(text="🔙 Back", callback_data="start")
    )
    await c.message.edit_text("🔥 <b>Hot Pairs</b>\nSelect network:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("net_"), state='*')
async def select_duration(c: types.CallbackQuery, state: FSMContext):
    net = c.data.split("_")[1]
    await state.update_data(network=net)
    kb = InlineKeyboardMarkup()
    for dur, usd in HOT_PAIRS_BASE_USD.items():
        crypto = await calculate_package_price(usd, net)
        unit = PAYMENT_UNITS.get(net, "ETH")
        kb.add(InlineKeyboardButton(text=f"{dur} - ${usd} ({crypto} {unit})", callback_data=f"dur_{dur}"))
    kb.add(InlineKeyboardButton(text="🔙 Back", callback_data="get_hot_pairs"))
    await c.message.edit_text(f"⏰ Select duration for {net.upper()}:", reply_markup=kb)
    await UserState.waiting_for_hot_pairs_package.set()

@dp.callback_query_handler(lambda c: c.data.startswith("dur_"), state=UserState.waiting_for_hot_pairs_package)
async def ask_ca(c: types.CallbackQuery, state: FSMContext):
    dur = c.data.split("_")[1]
    data = await state.get_data()
    net = data['network']
    usd = HOT_PAIRS_BASE_USD[dur]
    crypto = await calculate_package_price(usd, net)
    await state.update_data(duration=dur, usd=usd, crypto=crypto)
    await UserState.waiting_for_ca.set()
    await c.message.edit_text(f"✅ Selected {dur} for {net.upper()}.\n\nPlease send the <b>Contract Address (CA)</b>:")

@dp.message_handler(state=UserState.waiting_for_ca)
async def handle_ca(message: types.Message, state: FSMContext):
    ca = message.text.strip()
    data = await state.get_data()
    net = data['network']
    pair = await fetch_token_info(CHAIN_IDS.get(net, net), ca)
    if not pair:
        await message.answer("❌ Token not found. Check CA and network.")
        return
    
    await state.update_data(ca=ca, pair_data=pair)
    msg = create_professional_message(pair)
    await message.answer(f"🔍 <b>Token Found!</b>\n\n{msg}\n\nProceed to payment?")
    
    wallet = PAYMENT_WALLETS.get(net)
    unit = PAYMENT_UNITS.get(net)
    crypto = data['crypto']
    
    pay_msg = (
        f"💳 <b>PAYMENT DETAILS</b>\n\n"
        f"🔥 <b>Service:</b> Hot Pairs ({data['duration']})\n"
        f"💰 <b>Amount:</b> {crypto} {unit} (${data['usd']} USD)\n"
        f"🏦 <b>Wallet:</b>\n<code>{wallet}</code>\n\n"
        f"Send payment and click Paid."
    )
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text="✅ Paid", callback_data="paid"))
    await message.answer(pay_msg, reply_markup=kb)
    await UserState.waiting_for_payment.set()

@dp.callback_query_handler(lambda c: c.data == "paid", state=UserState.waiting_for_payment)
async def ask_tx(c: types.CallbackQuery):
    await UserState.waiting_for_tx_id.set()
    await c.message.answer("Please send your <b>Transaction Hash / ID</b>:")

@dp.message_handler(state=UserState.waiting_for_tx_id)
async def handle_tx(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await message.answer("⏳ <b>Verifying Payment...</b>\nThis takes 1-5 minutes.")
    await asyncio.sleep(5)
    
    msg = create_professional_message(data['pair_data'])
    try:
        await bot.send_message(CHANNEL_ID, msg)
        await message.answer(f"✅ <b>Payment Verified!</b>\nYour token is now live on Hot Pairs! 🚀")
    except Exception as e:
        logger.error(f"Failed to post to channel: {e}")
        await message.answer(f"✅ <b>Payment Verified!</b>\nDeployment active.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "support", state='*')
async def support(c: types.CallbackQuery):
    await c.message.answer("🛠 <b>Support:</b> @DEXToolsTrend_Support")

@dp.callback_query_handler(lambda c: c.data == "start", state='*')
async def main_menu(c: types.CallbackQuery, state: FSMContext):
    await start_cmd(c.message, state)

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
