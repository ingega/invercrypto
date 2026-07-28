# invercrypto/strategy/dataclasses.py
from dataclasses import dataclass
from typing import Tuple
""""
Validate data tuples for SQLite addition or update data functions
"""
# bet classes
@dataclass
class DirectBet:
    operation_id: int
    ticker: str
    capital: float
    colateral: float
    entry_date: str
    side: str
    entry_price: float
    tp: float
    sl: float
    last_partial_id: int

    def as_json(self):
        return {
            self.ticker: {
                "operation_id": self.operation_id,
                "capital": self.capital,
                "colateral": self.colateral,
                "entry_date": self.entry_date,
                "side": self.side,
                "entry_price": self.entry_price,
                "tp": self.tp,
                "sl": self.sl,
                "last_partial_id": self.last_partial_id
            }
        }

@dataclass
class SecondaryBet:
    ticker: str
    last_partial_id: int
    operation_id: int
    capital: float
    colateral: float
    entry_price: float
    entry_date: str
    actual_loss_percentage: float
    cycle_start_time: str
    actual_side: str
    tp: float
    sl: float

    def as_json(self):
        return {
            self.ticker: {
                "last_partial_id": self.last_partial_id,
                "operation_id": self.operation_id,
                "capital": self.capital,
                "colateral": self.colateral,
                "entry_price": self.entry_price,
                "entry_date": self.entry_date,
                "actual_loss_percentage": self.actual_loss_percentage,
                "cycle_start_time": self.cycle_start_time,
                "actual_side": self.actual_side,
                "tp": self.tp,
                "sl": self.sl
            }
        }

        
# operations classes
@dataclass
class CompletedOperation:
    operation_id: int 
    strategy: str 
    ticker: str 
    outcome: str 
    gain: float
    capital: float
    profit: float

    def as_tuple(self) -> Tuple:
        return (
            self.operation_id,
            self.strategy,
            self.ticker,
            self.outcome,
            self.gain,
            self.capital,
            self.profit
        )

@dataclass
class PartialOperation:
    operation_id: int
    entry_date: str
    side: str
    entry_price: float
    tp: float
    sl: float
    exit_date: str
    exit_price: float
    outcome: str
    gain: float
    bet: str

    def as_tuple(self) -> Tuple:
        return (
            self.operation_id,
            self.entry_date,
            self.side,
            self.entry_price,
            self.tp,
            self.sl,
            self.exit_date,
            self.exit_price,
            self.outcome,
            self.gain,
            self.bet
        )

@dataclass
class UpdateCompletedOperation:
    outcome: str
    gain: float
    profit: float
    operation_id: int

    def as_tuple(self) -> Tuple:
        return(
            self.outcome,
            self.gain,
            self.profit,
            self.operation_id
        )

@dataclass 
class UpdatePartialOperation:
    exit_date: str
    exit_price: float
    outcome: str
    gain: float
    partial_id: int

    def as_tuple(self):
        return(
            self.exit_date,
            self.exit_price,
            self.outcome,
            self.gain,
            self.partial_id
        )


def main():
    payload = DirectBet(
        operation_id=1,
        ticker="BTCUSDT",
        capital=100,
        colateral=50,
        entry_date="2026-07-25 00:00:00",
        side="BUY",
        entry_price=64000
    )
    print(payload.as_json())

if __name__ == '__main__':
    main()
