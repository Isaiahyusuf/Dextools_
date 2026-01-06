import asyncio
import logging
from main import fetch_token_info_raw, CHANNEL_ID, bot, create_professional_message, resize_image
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("token_monitor")

# Configurable thresholds
BIG_BUY_THRESHOLD_USD = 500  # Example: $500
PUMP_THRESHOLD_1H = 10.0      # Example: 10% in 1h
DUMP_THRESHOLD_1H = -10.0     # Example: -10% in 1h

class TokenMonitor:
    def __init__(self):
        self.monitored_tokens = {} # token_address: last_data
        self.is_running = False

    async def add_token(self, address):
        if address not in self.monitored_tokens:
            data = await fetch_token_info_raw(address)
            if data and 'pairs' in data:
                self.monitored_tokens[address] = data['pairs'][0]
                logger.info(f"Started monitoring {address}")

    async def check_tokens(self):
        for address, last_pair in list(self.monitored_tokens.items()):
            try:
                new_data = await fetch_token_info_raw(address)
                if not new_data or 'pairs' not in new_data:
                    continue
                
                new_pair = new_data['pairs'][0]
                
                # Check for Pump/Dump
                change_1h = float(new_pair.get('priceChange', {}).get('h1', 0))
                last_change_1h = float(last_pair.get('priceChange', {}).get('h1', 0))
                
                if change_1h >= PUMP_THRESHOLD_1H and last_change_1h < PUMP_THRESHOLD_1H:
                    await self.post_alert(new_pair, "🚀 BIG PUMP ALERT")
                elif change_1h <= DUMP_THRESHOLD_1H and last_change_1h > DUMP_THRESHOLD_1H:
                    await self.post_alert(new_pair, "📉 BIG DUMP ALERT")

                # Update state
                self.monitored_tokens[address] = new_pair
                
            except Exception as e:
                logger.error(f"Error checking token {address}: {e}")

    async def post_alert(self, pair_data, alert_type):
        msg_text, logo_url, chart_url = create_professional_message(pair_data)
        if not msg_text: return
        
        full_msg = f"<b>{alert_type}</b>\n\n{msg_text}"
        kb = InlineKeyboardMarkup()
        if chart_url:
            kb.add(InlineKeyboardButton(text="📊 View Chart", url=chart_url))
            
        try:
            if logo_url:
                img = await resize_image(logo_url)
                if img:
                    await bot.send_photo(CHANNEL_ID, photo=img, caption=full_msg, reply_markup=kb)
                    return
            await bot.send_message(CHANNEL_ID, full_msg, reply_markup=kb)
        except Exception as e:
            logger.error(f"Failed to post alert: {e}")

    async def run(self):
        self.is_running = True
        while self.is_running:
            await self.check_tokens()
            await asyncio.sleep(300) # Check every 5 minutes

monitor = TokenMonitor()
