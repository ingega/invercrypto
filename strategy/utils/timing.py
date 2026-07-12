import asyncio
from datetime import datetime

async def wait_for_time_trigger(target_hour: int, target_minute: int = 59, target_second: int = 57):
    """
    Calculates the exact sleep duration down to the millisecond required to hit
    the pre-emptive target window right before the top-of-the-hour structural block.
    Configurable for 15m, 1h, etc.
    
    Examples:
    target_hour=0, target_minute=4, target_second=57 -> Trigger every 5 minutes (3s early)
    target_hour=1, target_minute=59, target_second=57 -> Trigger every hour (3s early)
    """
    while True:
        now = datetime.now()
        actual_hour = now.hour
        actual_minute = now.minute
        actual_second = now.second
        actual_microsecond = now.microsecond

        # Calculate remaining hours based on intervals
        if target_hour < 1:  # zero hour is less than an hour
            left_hours = 0
        else:
            left_hours = (target_hour - 1) - (actual_hour % target_hour)
            if left_hours < 0:
                left_hours = 0

        # Calculate minutes left for next iteration using your dynamic modulus rule
        left_minutes = target_minute - (actual_minute % (target_minute + 1))
        
        # Calculate seconds and precise microsecond alignment
        left_seconds = target_second - actual_second
        
        # Handle edge case where we are inside the target buffer minute but past the target second
        if left_minutes == 0 and left_seconds < 0:
            # Shift window forward by one full step block
            left_minutes = target_minute
            left_seconds = target_second - actual_second

        # Convert to total float seconds, subtracting microsecond fragments for pristine accuracy
        total_seconds = (left_hours * 3600) + (left_minutes * 60) + left_seconds - (actual_microsecond / 1_000_000.0)

        # 🛡️ Guard Rule: If we are too close or missed the window, buffer to avoid spinning hot loops
        if total_seconds < 2.0:
            print("⚠️ [CLOCK] Proximity hazard detected (< 2s left). Padding loop interval.")
            await asyncio.sleep(2.0)
            continue

        print(f"⏰ [CLOCK] Syncing execution window. Target reached in: {total_seconds:.3f} seconds")
        
        # ⚡ The Critical Fix: Non-blocking async sleep lets other network/state routines breathe
        await asyncio.sleep(total_seconds)

        print(f"⚡ [CLOCK] Pre-emptive execution window hit at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}! Triggering scan...")
        break
        