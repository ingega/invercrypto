import time
from datetime import datetime as dt
from datetime import UTC
from typing import Tuple
# I/O files functions
from common_files.paths import *
from common_files.logger import get_logger
# notional size and balance functions
from common_files.balances import calculate_notional_size, calculate_colateral, reduce_available_balance
# operations
from data_classes import DirectBet, CompletedOperation, PartialOperation
# database
from database import save_operation_to_db, save_partial_operation_to_db
# binance functions
from common_files.binance_utils.bars import get_bars

logger = get_logger(__name__)

def calculate_tpsl(side:str, entry_price:float) -> Tuple[float, float]:
    # get direct bet percentages
    direct_bet_pct = load_json_file(CONFIG_FILE)["direct_bet_percentage"]
    tp, sl = 0, 0
    if side == "BUY":
        tp = entry_price * (1 + direct_bet_pct)
        sl = entry_price * (1 - direct_bet_pct)
    else:
        tp = entry_price * (1 - direct_bet_pct)
        sl = entry_price * (1 + direct_bet_pct)
    return tp, sl

# aux funct for entry addition
def add_entry(ticker:str, side:str, entry_price: float):
    """
    This function must execute the next workflow:
    I. Get capitial: Capital is retrieved from main_balance, but calculated with available_balance.
    II. Available balance reduces its balance.
    III. The entry is added to completed op (With generic exit_date, outcome, gain, profit)
    IV. The entry is added to partial op as well, with generic exit_date, exit_price, outcome, gain
    V. Entry is added to direct_bets
    ----------------------------------------
    params:
        ticker(str): Name of ticker
        side(str): side of the position (BUY or SELL)
        entry_price(float): initial price for position 
    ----------------------------------------
    """
    logger.info(f"↩️ record {ticker} starts the add entry pipeline")
    # 1. Get capital
    capital = calculate_notional_size(ticker=ticker)
    # 2. reduces the available balance
    # calculate colateral
    colateral = calculate_colateral(capital=capital)
    # reduce the balance
    reduce_available_balance(colateral=colateral)
    # 3. add record to completed_operations
    # get operation_id
    operation_id = time.time_ns()
    completed_record = CompletedOperation(
        operation_id=operation_id,
        strategy="tangent",
        ticker=ticker,
        outcome="UNRESOLVED",
        gain=0,
        capital=capital,
        profit=0
    )
    save_operation_to_db(operation=completed_record)
    # 4 add the partial operation
    # get the missed data
    entry_date = dt.now().strftime("%Y-%m-%d %H:%M:%S")
    tp, sl = calculate_tpsl(side=side, entry_price=entry_price)
    partial_record = PartialOperation(
        operation_id=operation_id,
        entry_date=entry_date,
        side=side,
        entry_price=entry_price,
        tp=tp,
        sl=sl,
        exit_date=entry_date,
        exit_price=0,
        outcome="UNRESOLVED",
        gain=0,
        bet="D"
    )
    partial_operation_id = save_partial_operation_to_db(partial_operation=partial_record)
    partial_operation_id = 0 if not partial_operation_id else partial_operation_id
    # 5. add entry to direct bets json file
    direct_bet_file = load_json_file(BET_FILE)
    # build the json payload
    direct_bet_record = DirectBet(
        operation_id=operation_id,
        ticker=ticker,
        capital=capital,
        colateral=colateral,
        entry_date=entry_date,
        side=side,
        entry_price=entry_price,
        tp=tp,
        sl=sl,
        last_partial_id=partial_operation_id
    )
    json_bet = direct_bet_record.as_json()
    direct_bet_file.update(json_bet)
    save_json_file(BET_FILE, direct_bet_file)
    # finally inform
    logger.info(f"↩️ record was added to actual bets file with this value"
                f"{json_bet}")

def calculate_tangent_signal(
    closes: list[float],
    separation: int,
    threshold: float,
    mvr_threshold: float = -1.0,
) -> dict | None:
    """
    Pure-Python signal & Adaptive MVR evaluator:
    - MVR <= mvr_threshold: Trend-following (BUY on +, SELL on -)
    - MVR >  mvr_threshold: Exhaustion Fade (inverts BUY <-> SELL)
    """
    if len(closes) < separation + 1:
        return None

    last_close = closes[-1]
    fast_base = closes[-1 - separation]
    if fast_base == 0:
        return None

    raw_tangent = (last_close - fast_base) / fast_base
    abs_tangent = abs(raw_tangent)

    if abs_tangent < threshold:
        return None

    side = "BUY" if raw_tangent >= 0 else "SELL"
    mvr_value = 0.0
    regime = "TREND"

    # Compute MVR & apply Adaptive Regime Switch if enabled
    slow_separation = separation * 4
    if mvr_threshold > 0 and len(closes) >= slow_separation + 1:
        slow_base = closes[-1 - slow_separation]
        if slow_base != 0:
            abs_tangent_slow = abs((last_close - slow_base) / slow_base)
            mvr_value = (abs_tangent / abs_tangent_slow) if abs_tangent_slow > 0 else 0.0

            if mvr_value > mvr_threshold:
                side = "SELL" if side == "BUY" else "BUY"
                regime = "FADE"

    return {
        "side": side,
        "tangent": raw_tangent,
        "mvr": round(mvr_value, 4),
        "regime": regime,
        "entry_price": last_close,
    }


async def scan_tangent_opportunities(live=False):
    config = load_json_file(CONFIG_LIVE_FILE if live else CONFIG_FILE)
    tickers = load_json_file(TICKERS_FILE)["selected_tickers"]
    separation = config["separation"]
    threshold = config["threshold"]
    interval = config["timeframe"]
    mvr_threshold = config.get("mvr", -1.0)

    # Fetch 4x separation + 1 bars when MVR is enabled so slow_base is available
    bars_needed = (separation * 4 + 1) if mvr_threshold > 0 else (separation + 1)

    found_opportunities = []
    print(f"🔎 [PURE SCAN] Scanning tickers: {tickers} | Adaptive MVR: {mvr_threshold}")

    direct_bets = load_json_file(BET_FILE)
    secondary_bets = load_json_file(SECONDARY_BET_FILE)

    for ticker in tickers:
        if not live and (ticker in direct_bets or ticker in secondary_bets):
            continue
        try:
            klines = get_bars(ticker=ticker, bars=bars_needed, interval=interval)
            closes = [float(k[4]) for k in klines]

            signal = calculate_tangent_signal(
                closes=closes,
                separation=separation,
                threshold=threshold,
                mvr_threshold=mvr_threshold,
            )

            if signal:
                print(
                    f"✅ {ticker} | Side: {signal['side']} ({signal['regime']}) | "
                    f"Tangent: {signal['tangent']:.4f} | MVR: {signal['mvr']:.4f}"
                )
                if not live:
                    add_entry(ticker=ticker, side=signal["side"], entry_price=signal["entry_price"])

                found_opportunities.append({
                    "ticker": ticker,
                    "tangent": signal["tangent"],
                    "mvr": signal["mvr"],
                    "regime": signal["regime"],
                    "side": signal["side"],
                })

        except Exception as e:
            print(f"❌ Error sweeping live REST data for {ticker}: {e}")

    return found_opportunities