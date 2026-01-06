import os
import aiohttp
import asyncio
import logging
import re
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
POST_FOOTER = "\n\n🌐 DexTools Hot Pairs Bot • visibility for your token"

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
    waiting_for_confirmation = State()
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

async def resize_image(url, size=(300,300)):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200: return None
                img_bytes = await resp.read()
                img = Image.open(BytesIO(img_bytes))
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P': img = img.convert('RGBA')
                    if img.mode in ('RGBA', 'LA'): background.paste(img, mask=img.split()[-1])
                    else: background.paste(img)
                    img = background
                max_dim = max(img.size)
                square_img = Image.new('RGB', (max_dim, max_dim), (255, 255, 255))
                offset = ((max_dim - img.size[0]) // 2, (max_dim - img.size[1]) // 2)
                square_img.paste(img, offset)
                square_img.thumbnail(size, Image.Resampling.LANCZOS)
                bio = BytesIO()
                bio.name = "logo.png"
                square_img.save(bio, format="PNG", quality=95)
                bio.seek(0)
                return bio
    except: return None

def create_professional_message(pair_data):
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
    logo_url = pair_data.get('info', {}).get('imageUrl') or base_token.get('imageUrl')
    
    info = pair_data.get('info', {})
    social_links = info.get('socials', [])
    websites = info.get('websites', [])
    tg_link = ""
    tw_link = ""
    web_link = ""
    for site in websites:
        url = site.get('url')
        if url: web_link = url
    for social in social_links:
        s_type = social.get('type', '').lower()
        url = social.get('url')
        if not url: continue
        if 'telegram' in s_type or 't.me' in url: tg_link = url
        elif 'twitter' in s_type or 'x.com' in url: tw_link = url

    try:
        price_float = float(price_usd)
        if price_float < 0.000001: price_display = f"${price_float:.10f}"
        elif price_float < 0.01: price_display = f"${price_float:.8f}"
        else: price_display = f"${price_float:.6f}"
    except: price_display = "N/A"

    network_emoji = NETWORK_EMOJIS.get(str(pair_chain).lower(),"🔗")
    symbol = base_token.get('symbol','Unknown')
    name = base_token.get('name','Unknown')
    display_name = name
    if tg_link: display_name = f"<a href='{tg_link}'>{display_name}</a>"
    social_row = ""
    if tw_link or web_link:
        links = []
        if tw_link: links.append(f"<a href='{tw_link}'>Twitter</a>")
        if web_link: links.append(f"<a href='{web_link}'>Website</a>")
        social_row = " | ".join(links) + "\n\n"

    message = (
        f"╔══════════════════════════╗\n"
        f"     <b>🎯 TOKEN ANALYTICS</b>\n"
        f"╚══════════════════════════╝\n\n"
        f"{network_emoji} <b>{symbol}</b> • {display_name}\n"
        f"{social_row}"
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
        f"{POST_FOOTER}"
    )
    chart_url = f"https://dexscreener.com/{pair_chain}/{pair_address}" if pair_address else None
    return message, logo_url, chart_url

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
    msg, logo_url, chart_url = create_professional_message(pair)
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text="✅ Confirm & Activate", callback_data="confirm_project"))
    kb.add(InlineKeyboardButton(text="❌ Cancel", callback_data="get_hot_pairs"))

    if logo_url:
        img = await resize_image(logo_url)
        if img:
            await message.answer_photo(photo=img, caption=f"🔍 <b>Please confirm this is your project:</b>\n\n{msg}", reply_markup=kb)
        else:
            await message.answer(f"🔍 <b>Please confirm this is your project:</b>\n\n{msg}", reply_markup=kb)
    else:
        await message.answer(f"🔍 <b>Please confirm this is your project:</b>\n\n{msg}", reply_markup=kb)
    
    await UserState.waiting_for_confirmation.set()

@dp.callback_query_handler(lambda c: c.data == "confirm_project", state=UserState.waiting_for_confirmation)
async def handle_confirmation(c: types.CallbackQuery, state: FSMContext):
    await c.answer()
    data = await state.get_data()
    net = data['network']
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
    await c.message.answer(pay_msg, reply_markup=kb)
    await UserState.waiting_for_payment.set()

@dp.callback_query_handler(lambda c: c.data == "paid", state=UserState.waiting_for_payment)
async def ask_tx(c: types.CallbackQuery):
    await UserState.waiting_for_tx_id.set()
    await c.message.answer("Please send your <b>Transaction Hash / ID</b>:")

@dp.message_handler(state=UserState.waiting_for_tx_id)
async def handle_tx(message: types.Message, state: FSMContext):
    tx = message.text.strip()
    data = await state.get_data()
    user_info = f"👤 User: {message.from_user.full_name} (@{message.from_user.username})\n🆔 ID: {message.from_user.id}"
    
    admin_msg = (
        f"🔔 <b>NEW PAYMENT SUBMITTED</b>\n\n"
        f"{user_info}\n\n"
        f"🔥 <b>Service:</b> Hot Pairs ({data['duration']})\n"
        f"⛓️ <b>Network:</b> {data['network'].upper()}\n"
        f"💰 <b>Amount:</b> {data['crypto']} {PAYMENT_UNITS.get(data['network'])}\n"
        f"📝 <b>CA:</b> {data['ca']}\n"
        f"🔗 <b>TX ID:</b> {tx}"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text="✅ Activate Now", callback_data=f"admin_activate_{message.from_user.id}"))
    
    for admin_id in SUPPORT_IDS:
        try:
            await bot.send_message(admin_id, admin_msg, reply_markup=kb)
        except: pass
        
    await message.answer("⏳ <b>Payment Submitted!</b>\nAdmin is verifying your payment. Your token will be activated shortly.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("admin_activate_"), state='*')
async def admin_activate(c: types.CallbackQuery):
    try:
        user_id = int(c.data.split("_")[2])
        msg_text = c.message.text or c.message.caption or ""
        
        # Simple extraction using fixed prefixes
        ca = None
        net = None
        
        for line in msg_text.split('\n'):
            if "CA:" in line:
                ca = line.split("CA:")[1].strip()
            if "Network:" in line:
                net = line.split("Network:")[1].strip().lower()
                
                if ca and net:
                    await monitor.add_token(ca) # Start monitoring the token when activated
                    pair = await fetch_token_info(CHAIN_IDS.get(net, net), ca)
            if pair:
                msg, logo_url, chart_url = create_professional_message(pair)
                kb = InlineKeyboardMarkup()
                if chart_url:
                    kb.add(InlineKeyboardButton(text="📊 View Chart", url=chart_url))
                
                if logo_url:
                    img = await resize_image(logo_url)
                    if img: await bot.send_photo(CHANNEL_ID, photo=img, caption=msg, reply_markup=kb)
                    else: await bot.send_message(CHANNEL_ID, msg, reply_markup=kb)
                else:
                    await bot.send_message(CHANNEL_ID, msg, reply_markup=kb)
                    
                await c.message.edit_text(msg_text + "\n\n✅ <b>ACTIVATED!</b>")
                try:
                    await bot.send_message(user_id, "✅ <b>Payment Verified!</b>\nYour token is now live on Hot Pairs! 🚀")
                except: pass
            else:
                await c.answer("Error: Token info not found.")
        else:
            logger.error(f"Failed to parse CA or Network. Text: {msg_text}")
            await c.answer("Error parsing CA/Network.")
    except Exception as e:
        logger.error(f"Error in admin_activate: {e}")
        await c.answer(f"Error: {e}")

@dp.callback_query_handler(lambda c: c.data == "support", state='*')
async def support(c: types.CallbackQuery):
    await c.message.answer("🛠 <b>Support:</b> @DEXToolsTrend_Support")

@dp.callback_query_handler(lambda c: c.data == "start", state='*')
async def main_menu(c: types.CallbackQuery, state: FSMContext):
    await start_cmd(c.message, state)

# Moved to avoid circular import
from monitor import monitor

async def on_startup(dp):
    asyncio.create_task(monitor.run())
    logger.info("Bot started and monitor task created")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
