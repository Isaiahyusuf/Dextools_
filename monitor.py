import asyncio
import logging
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
        import main
        if address not in self.monitored_tokens:
            data = await main.fetch_token_info_raw(address)
            if data and 'pairs' in data and data['pairs']:
                pair = data['pairs'][0]
                self.monitored_tokens[address] = pair
                # Initialize buy tracking with current 24h volume
                self.last_buys[address] = float(pair.get('volume', {}).get('h24', 0))
                logger.info(f"Started monitoring {address}")

    async def check_tokens(self):
        import main
        for address, last_pair in list(self.monitored_tokens.items()):
            try:
                new_data = await main.fetch_token_info_raw(address)
                if not new_data or 'pairs' not in new_data or not new_data['pairs']:
                    continue
                
                new_pair = new_data['pairs'][0]
                
                # Check for Pump/Dump (>= 10%)
                change_1h = float(new_pair.get('priceChange', {}).get('h1', 0))
                
                if change_1h >= PUMP_THRESHOLD_1H:
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
                    await self.post_alert(new_pair, f"💰 BUY DETECTED (${diff:,.2f})")
                
                # Update state
                self.monitored_tokens[address] = new_pair
                self.last_buys[address] = new_volume
                
            except Exception as e:
                logger.error(f"Error checking token {address}: {e}")

    async def post_alert(self, pair_data, alert_type):
        import main
        msg_text, logo_url, chart_url = main.create_professional_message(pair_data)
        if not msg_text: return
        
        full_msg = f"<b>{alert_type}</b>\n\n{msg_text}"
        kb = InlineKeyboardMarkup()
        if chart_url:
            kb.add(InlineKeyboardButton(text="📊 View Chart", url=chart_url))
            
        try:
            if logo_url:
                img = await main.resize_image(logo_url)
                if img:
                    await main.bot.send_photo(main.CHANNEL_ID, photo=img, caption=full_msg, reply_markup=kb)
                    return
            await main.bot.send_message(main.CHANNEL_ID, full_msg, reply_markup=kb)
        except Exception as e:
            logger.error(f"Failed to post alert: {e}")

    async def run(self):
        self.is_running = True
        while self.is_running:
            await self.check_tokens()
            await asyncio.sleep(10) # Check every 10 seconds

monitor = TokenMonitor()
