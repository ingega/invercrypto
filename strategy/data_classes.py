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

##################################################
#            Live DataClasses                    #
##################################################

###############  DATABASE DATACLASSES  ################
@dataclass
class CompletedLiveOperation:
    operation_id: int
    strategy: str
    ticker: str
    entry_date: str
    capital: float
    quantity: float
    exit_date: str
    outcome: str
    gain: float
    pnl: float
    commission: float
    fee: float
    profit: float

    def as_tuple(self) -> Tuple:
        return(
        self.operation_id,
        self.strategy,
        self.ticker,
        self.entry_date,
        self.capital,
        self.quantity,
        self.exit_date,
        self.outcome,
        self.gain,
        self.pnl,
        self.commission,
        self.fee,
        self.profit
        )

@dataclass
class PartialLiveOperation:
    operation_id: int
    order_id: int
    entry_date: str
    side: str
    entry_price: float
    type: str
    tp: float
    sl: float
    tp_algo_id: int
    sl_algo_id: int
    exit_date: str
    exit_price: float
    outcome: str
    gain: float
    pnl: float
    commission: float
    bet: str

    def as_tuple(self) -> Tuple:
        return(
            self.operation_id,
            self.order_id,
            self.entry_date,
            self.side,
            self.entry_price,
            self.type,
            self.tp,
            self.sl,
            self.tp_algo_id,
            self.sl_algo_id,
            self.exit_date,
            self.exit_price,
            self.outcome,
            self.gain,
            self.pnl,
            self.commission,
            self.bet
        )

@dataclass
class UpdateCompleteLiveOperation:
    exit_date: str
    outcome: str
    gain: float
    pnl: float
    commission: float
    fee: float
    profit: float
    operation_id: int

    def as_tuple(self) -> Tuple:
        return(
            self.exit_date,
            self.outcome,
            self.gain,
            self.pnl,
            self.commission,
            self.fee,
            self.profit,
            self.operation_id
        )

@dataclass
class UpdatePartialLiveOPeration:
    order_id: int
    exit_date: str
    exit_price: float
    outcome: str
    gain: float
    pnl: float
    commission: float
    operation_id: int

    def as_tuple(self) -> Tuple:
        return(
            self.order_id,
            self.exit_date,
            self.exit_price,
            self.outcome,
            self.gain,
            self.pnl,
            self.commission,
            self.operation_id
        )

###############  JSON DATACLASSES  ################

@dataclass
class AddBetToJSON:
    ticker: str
    operation_id: int

    def as_dict(self) -> dict:
        """
        Returnig a JSON object allows data growth easily
        """
        return(
            {
                self.ticker: {
                    "operation_id": self.operation_id
                }
            }
        )


def main():
    payload = ()
    print(payload)

if __name__ == '__main__':
    main()
