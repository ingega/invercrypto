import time
from datetime import datetime

def wait_for_time_trigger(target_hour: int, target_minute: int = 59, target_second: int = 57):
    """
    Calculates the exact sleep duration down to the millisecond required to hit
    the pre-emptive target window right before the top-of-the-hour structural block.
    Configurable for 15m, 1h, etc.
    Examples:
    0 hours, 4 minutes, 57 secs, means, trigger every 4:57 mins (3 seconds before 5 mins)
    3 hours, 59 minutes, 57 seconds, means 3 seconds before 4 hrs
    """
    while True:
        now = datetime.now()
        actual_hour = now.hour
        actual_minute = now.minute
        actual_second = now.second
        if target_hour < 1:  # zero hour is less than an hour, negative is impossible
            left_hours = 0
        else:
            left_hours = actual_hour % target_hour
        # calculate the minutes left for next iteration
        left_minutes = target_minute - (actual_minute % (target_minute + 1))  # example, minutes = 4, trigger
        # at 4, 9, 14 etc. if actual is 23, 23 % 5 = 3, therefore 4 - 3 = 1
        # for 36, is 36 % 5 = 1, therefore 4 - 1 = 3
        # if minutes = 59, and actual minutes = 36 then 36 % 60 = 36, therefore, 59 - 36 = 23
        left_seconds = target_second - actual_second
        # if the second is missed, let's add a 2 secs sleep
        if left_seconds < 2:  # one second left is risky
            time.sleep(2)
        total_seconds = (left_hours * 3600) + (left_minutes * 60) + left_seconds
        print(f"⏰ [CLOCK] Syncing execution window. Target reached in: {total_seconds} seconds")
        time.sleep(total_seconds)

        print(
            f"⚡ [CLOCK] Pre-emptive execution window hit at {datetime.now().strftime('%H:%M:%S.%f')[:-3]} UTC! Triggering scan...")
        break
        