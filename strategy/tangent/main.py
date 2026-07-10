from pathlib import Path
import time
from datetime import datetime
from utils.timing import wait_for_time_trigger
from .filter import scan_tangent_opportunities
# logger
from common_files.logger import get_logger

logger = get_logger(__name__)

def main_engine_loop():
    logger.info("🤖 Invercrypto 2.0 Live Simulator Pipeline Initialize.")
    
    # Configure variables for top-of-the-hour pre-emption (e.g., 3 seconds before close)
    TARGET_MIN = 59
    TARGET_SEC = 55  # 5 seconds is enough time
    
    while True:
        # 1. Yield thread control until the exact pre-emptive offset window is hit
        wait_for_time_trigger(target_hour=0,
            target_minute=TARGET_MIN, target_second=TARGET_SEC)
        
        # 2. Fire the asset tangent scanner matrix
        logger.info("⚡ Pre-emptive trigger fired! Commencing structural sweep...")
        opportunities = scan_tangent_opportunities()
        
        if not opportunities:
            logger.info("🤷 Sweep complete. Zero opportunities matched current boundaries.")
        else:
            for opp in opportunities:
                alert_msg = (
                    f"🚨 Opportunity alarm: Ticker={opp['ticker']} | "
                    f"Directional-Side={opp['side']} | Tangent-Value={opp['val']:.4f} | "
                    f"Trigger-Price={opp['price']}"
                )
                logger.info(alert_msg)
                
        # Give a small buffer pause to prevent hitting the same execution second twice
        time.sleep(7)

if __name__ == "__main__":
    try:
        main_engine_loop()
    except KeyboardInterrupt:
        logger.exception("\n🛑 Simulator runtime manually terminated safely. Standing down.")