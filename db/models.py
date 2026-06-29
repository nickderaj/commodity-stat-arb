from datetime import date, datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)  # e.g. "CLF24"
    product = Column(String(10), nullable=False)  # e.g. "CL", "BZ"
    exchange = Column(String(10), nullable=False)  # "CME", "ICE"
    contract_month = Column(String(20), nullable=False)  # "2024-01" or "continuous"
    expiry = Column(Date, nullable=False)
    first_notice_date = Column(Date)
    last_trade_date = Column(Date)

    bars = relationship("OHLCVBar", back_populates="contract", cascade="all, delete-orphan")
    metrics = relationship("ContractMetrics", back_populates="contract", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("ticker", name="uq_contracts_ticker"),)


class OHLCVBar(Base):
    __tablename__ = "ohlcv_bars"

    id = Column(BigInteger, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger)
    open_interest = Column(BigInteger)

    contract = relationship("Contract", back_populates="bars")

    __table_args__ = (UniqueConstraint("contract_id", "date", name="uq_ohlcv_contract_date"),)


class ContractMetrics(Base):
    """Daily microstructure proxies derived from OHLCV (not true tick-level microstructure)."""

    __tablename__ = "contract_metrics"

    id = Column(BigInteger, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    date = Column(Date, nullable=False)
    realised_vol_20d = Column(Float)   # annualised std of 20-day log returns
    hl_range_pct = Column(Float)       # (high - low) / close - bid-ask spread proxy
    avg_volume_20d = Column(Float)     # 20-day rolling mean volume
    avg_oi_20d = Column(Float)         # 20-day rolling mean open interest

    contract = relationship("Contract", back_populates="metrics")

    __table_args__ = (
        UniqueConstraint("contract_id", "date", name="uq_contract_metrics_contract_date"),
    )


class Spread(Base):
    __tablename__ = "spreads"

    id = Column(BigInteger, primary_key=True)
    spread_name = Column(String(50), nullable=False)  # e.g. "wti_calendar"
    date = Column(Date, nullable=False)
    value = Column(Float, nullable=False)
    leg1_price = Column(Float)
    leg2_price = Column(Float)
    hedge_ratio = Column(Float, default=1.0)
    roll_window_flag = Column(Boolean, default=False)
    regime = Column(String(20))  # "roll_window" | "mid_cycle" | None

    __table_args__ = (UniqueConstraint("spread_name", "date", name="uq_spread_name_date"),)


class RollCalendarEntry(Base):
    __tablename__ = "roll_calendar"

    id = Column(Integer, primary_key=True)
    product = Column(String(10), nullable=False)  # "CL", "BZ"
    contract_month = Column(String(20), nullable=False)  # "2024-01" or "continuous"
    expiry = Column(Date, nullable=False)
    first_notice_date = Column(Date)
    last_trade_date = Column(Date)

    __table_args__ = (
        UniqueConstraint("product", "contract_month", name="uq_roll_product_month"),
    )


class Signal(Base):
    __tablename__ = "signals"

    id = Column(BigInteger, primary_key=True)
    spread_name = Column(String(50), nullable=False)
    date = Column(Date, nullable=False)
    zscore = Column(Float)
    lookback = Column(Integer)
    entry_flag = Column(Boolean, default=False)
    exit_flag = Column(Boolean, default=False)
    regime_flags = Column(Text)  # JSON-encoded dict of active regime flags

    __table_args__ = (
        UniqueConstraint("spread_name", "date", "lookback", name="uq_signal_spread_date_lookback"),
    )


class Order(Base):
    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True)
    spread_name = Column(String(50), nullable=False)
    backtest_run_id = Column(Integer, ForeignKey("backtest_runs.id"), nullable=True)
    entry_date = Column(Date, nullable=False)
    exit_date = Column(Date)
    direction = Column(String(5), nullable=False)  # "long" | "short"
    entry_price = Column(Float)
    exit_price = Column(Float)
    fill_price = Column(Float)
    fees = Column(Float, default=0.0)
    slippage = Column(Float, default=0.0)
    spread_cost = Column(Float, default=0.0)
    temp_impact_cost = Column(Float, default=0.0)
    perm_impact_cost = Column(Float, default=0.0)
    pnl = Column(Float)
    zscore_at_entry = Column(Float)
    regime_at_entry = Column(String(50))
    trade_duration_days = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True)
    params_hash = Column(String(64), nullable=False)
    spread_name = Column(String(50), nullable=False)
    start_date = Column(Date)
    end_date = Column(Date)
    sharpe = Column(Float)
    sortino = Column(Float)
    calmar = Column(Float)
    max_drawdown = Column(Float)
    total_trades = Column(Integer)
    win_rate = Column(Float)
    profit_factor = Column(Float)
    avg_trade_pnl = Column(Float)
    avg_trade_duration_days = Column(Float)
    params_json = Column(Text)  # full param dict serialised to JSON
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", backref="backtest_run", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("params_hash", name="uq_backtest_params_hash"),)
