import asyncio
import logging
from main import fetch_token_info_raw, CHANNEL_ID, bot, create_professional_message, resize_image
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("token_monitor")

# Configurable thresholds
BIG_BUY_THRESHOLD_USD = 500  # Example: $500
PUMP_THRESHOLD_1H = 10.0      # Minimum 10% pump
DUMP_THRESHOLD_1H = -10.0     # Minimum 10% dump

class TokenMonitor:
    def __init__(self):
        self.monitored_tokens = {} # token_address: last_data
        self.last_buys = {}        # token_address: last_volume
        self.is_running = False

    async def add_token(self, address):
        if address not in self.monitored_tokens:
            data = await fetch_token_info_raw(address)
            if data and 'pairs' in data and data['pairs']:
                pair = data['pairs'][0]
                self.monitored_tokens[address] = pair
                # Initialize buy tracking with current 24h volume or specific buy metrics if available
                # Since DexScreener doesn't give a live transaction feed via this endpoint, 
                # we track volume changes as a proxy for 'buys'
                self.last_buys[address] = float(pair.get('volume', {}).get('h24', 0))
                logger.info(f"Started monitoring {address}")

    async def check_tokens(self):
        for address, last_pair in list(self.monitored_tokens.items()):
            try:
                new_data = await fetch_token_info_raw(address)
                if not new_data or 'pairs' not in new_data or not new_data['pairs']:
                    continue
                
                new_pair = new_data['pairs'][0]
                
                # Check for Pump/Dump (>= 10%)
                change_1h = float(new_pair.get('priceChange', {}).get('h1', 0))
                
                if change_1h >= PUMP_THRESHOLD_1H:
                    # Only alert if it's a "new" pump or significantly higher than last check
                    last_change = float(last_pair.get('priceChange', {}).get('h1', 0))
                    if last_change < PUMP_THRESHOLD_1H:
                        await self.post_alert(new_pair, "🚀 BIG PUMP ALERT (10%+) ")
                
                elif change_1h <= DUMP_THRESHOLD_1H:
                    last_change = float(last_pair.get('priceChange', {}).get('h1', 0))
                    if last_change > DUMP_THRESHOLD_1H:
                        await self.post_alert(new_pair, "📉 BIG DUMP ALERT (10%+) ")

                # Check for 'Buys' (Volume increases) every 10s
                new_volume = float(new_pair.get('volume', {}).get('h24', 0))
                last_volume = self.last_buys.get(address, 0)
                
                if new_volume > last_volume:
                    diff = new_volume - last_volume
                    if diff >= BIG_BUY_THRESHOLD_USD:
                        await self.post_alert(new_pair, f"💰 BIG BUY DETECTED (${diff:,.2f})")
                
                # Update state
                self.monitored_tokens[address] = new_pair
                self.last_buys[address] = new_volume
                
            except Exception as e:
                logger.error(f"Error checking token {address}: {e}")

    async def run(self):
        self.is_running = True
        while self.is_running:
            await self.check_tokens()
            await asyncio.sleep(10) # Check every 10 seconds as requested

monitor = TokenMonitor()
