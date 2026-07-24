# invercrypto/strategy/dataclasses.py
from dataclasses import dataclass
from typing import Tuple
""""
Validate data tuples for SQLite addition or update data functions
"""
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
            self.strategy,
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
class UpdateOperation:
    gain: float
    profit: float
    operation_id: int

    def as_tuple(self) -> Tuple:
        return(
            self.gain,
            self.profit,
            self.operation_id
        )

