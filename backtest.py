"""
Backtest Engine
Geçmiş veriler üzerinde strateji performansını test eder.
Hedef: 30 günde ~%28.57 ROI, ~29 trade/gün, %50-60 win rate
"""

import asyncio
import sys
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

from strategies.multi_strategy import MultiStrategyEngine
from strategies.base_strategy import SignalType
from utils.data_fetcher import DataFetcher
from utils.risk_manager import RiskManager, TradeRecord
from utils.indicators import TechnicalIndicators
from utils.logger import setup_logger
from utils.helpers import format_currency, format_pct
from config import (
    TRADING_PAIRS, BACKTEST_DAYS, BACKTEST_INITIAL_CAPITAL,
    PRIMARY_TIMEFRAME, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    MAKER_FEE, TAKER_FEE, SLIPPAGE_PCT, MAX_POSITION_PCT
)

logger = setup_logger("Backtest")


@dataclass
class BacktestResult:
    """Backtest sonuçları."""
    initial_capital: float
    final_capital: float
    total_pnl: float
    total_fees: float
    net_pnl: float
    roi: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    max_drawdown: float
    sharpe_ratio: float
    profit_factor: float
    avg_trades_per_day: float
    daily_returns: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    trade_log: list = field(default_factory=list)


class BacktestEngine:
    """Backtest motoru."""

    def __init__(self, initial_capital: float = BACKTEST_INITIAL_CAPITAL):
        self.initial_capital = initial_capital
        self.strategy_engine = MultiStrategyEngine()
        self.data_fetcher = DataFetcher()
        self.indicators = TechnicalIndicators()

    async def run(self, pairs: list[str] = None,
                  timeframe: str = PRIMARY_TIMEFRAME,
                  days: int = BACKTEST_DAYS) -> BacktestResult:
        """Backtest çalıştır."""
        pairs = pairs or TRADING_PAIRS
        logger.info(f"Backtest başlıyor: {len(pairs)} pair, {days} gün, {timeframe} timeframe")

        # Veri çek
        await self.data_fetcher.initialize()
        all_data = {}

        # Her pair için yeterli geçmiş veri çek
        candles_needed = self._estimate_candles(timeframe, days)

        for pair in pairs:
            try:
                df = await self.data_fetcher.fetch_ohlcv(pair, timeframe, limit=candles_needed)
                if not df.empty and len(df) >= 100:
                    all_data[pair] = df
                    logger.info(f"  ✓ {pair}: {len(df)} mum yüklendi")
                else:
                    logger.warning(f"  ✗ {pair}: Yetersiz veri ({len(df)} mum)")
            except Exception as e:
                logger.error(f"  ✗ {pair}: Hata - {e}")

        await self.data_fetcher.close()

        if not all_data:
            logger.error("Hiç veri çekilemedi!")
            return self._empty_result()

        # Backtest simülasyonu
        result = self._simulate(all_data, days)
        self._print_results(result)
        self._save_results(result)

        return result

    def _estimate_candles(self, timeframe: str, days: int) -> int:
        """Timeframe'e göre gerekli mum sayısını hesapla."""
        tf_minutes = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
        }
        minutes = tf_minutes.get(timeframe, 5)
        candles_per_day = 1440 / minutes
        # Ekstra mum (gösterge hesabı için)
        return min(int(candles_per_day * days) + 200, 1000)

    def _simulate(self, all_data: dict, days: int) -> BacktestResult:
        """Backtest simülasyonu çalıştır."""
        capital = self.initial_capital
        peak_capital = capital
        total_fees = 0.0
        trades = []
        equity_curve = []
        daily_returns = []

        # Her pair için göstergeleri hesapla
        processed_data = {}
        for pair, df in all_data.items():
            processed_data[pair] = self.indicators.calculate_all(df)

        # Zaman serisi üzerinde ilerle
        # Tüm pair'lerin ortak zaman aralığını bul
        min_len = min(len(df) for df in processed_data.values())
        start_idx = max(60, min_len - self._estimate_candles(PRIMARY_TIMEFRAME, days))

        open_positions = {}  # {symbol: {entry_price, quantity, stop_loss, take_profit, side}}
        prev_day = None
        day_start_capital = capital

        for i in range(start_idx, min_len):
            # Her pair'i kontrol et
            for pair, df in processed_data.items():
                if i >= len(df):
                    continue

                current_price = df["close"].iloc[i]
                current_time = df.index[i] if hasattr(df.index[i], 'date') else None

                # Gün değişimi kontrolü
                if current_time and hasattr(current_time, 'date'):
                    current_day = current_time.date()
                    if prev_day and current_day != prev_day:
                        daily_ret = ((capital - day_start_capital) / day_start_capital) * 100
                        daily_returns.append(daily_ret)
                        day_start_capital = capital
                    prev_day = current_day

                # Açık pozisyon kontrol et
                if pair in open_positions:
                    pos = open_positions[pair]

                    # Trailing stop güncelle
                    if pos["side"] == "buy" and current_price > pos.get("highest", pos["entry_price"]):
                        pos["highest"] = current_price
                        new_trail = current_price * (1 - 0.02)  # %2 trailing
                        pos["trailing_stop"] = max(pos.get("trailing_stop", pos["stop_loss"]), new_trail)

                    # Stop-loss kontrolü
                    hit_sl = (pos["side"] == "buy" and current_price <= pos["stop_loss"]) or \
                             (pos["side"] == "buy" and current_price <= pos.get("trailing_stop", 0))

                    # Take-profit kontrolü
                    hit_tp = pos["side"] == "buy" and current_price >= pos["take_profit"]

                    if hit_sl or hit_tp:
                        exit_price = pos["stop_loss"] if hit_sl else pos["take_profit"]
                        if hit_sl and pos.get("trailing_stop", 0) > pos["stop_loss"]:
                            exit_price = pos["trailing_stop"]

                        # P&L hesapla
                        pnl_pct = ((exit_price - pos["entry_price"]) / pos["entry_price"]) * 100
                        position_value = pos["quantity"] * pos["entry_price"]
                        pnl = position_value * (pnl_pct / 100)

                        # Fee
                        fee = position_value * (TAKER_FEE + SLIPPAGE_PCT) * 2  # Entry + exit
                        net_pnl = pnl - fee
                        total_fees += fee
                        capital += net_pnl

                        trades.append({
                            "symbol": pair,
                            "side": pos["side"],
                            "entry_price": pos["entry_price"],
                            "exit_price": exit_price,
                            "pnl": net_pnl,
                            "pnl_pct": pnl_pct,
                            "fee": fee,
                            "reason": "stop_loss" if hit_sl else "take_profit",
                        })

                        del open_positions[pair]

                        if capital > peak_capital:
                            peak_capital = capital

                    continue

                # Yeni sinyal ara (sadece açık pozisyon yoksa)
                if len(open_positions) >= 5:
                    continue

                # Strateji analizi (son 100 mum ile)
                window = df.iloc[max(0, i - 100):i + 1]
                if len(window) < 60:
                    continue

                analysis = self.strategy_engine.analyze(window, pair)

                if analysis["signal"] == SignalType.BUY and analysis["composite_score"] >= 0.60:
                    # Pozisyon aç
                    position_value = capital * MAX_POSITION_PCT
                    quantity = position_value / current_price

                    atr = analysis.get("atr", current_price * 0.01)
                    sl_distance = max(atr * 1.5, current_price * STOP_LOSS_PCT)
                    stop_loss = current_price - sl_distance
                    tp_distance = sl_distance * 3.5  # ~3.5:1 R:R
                    tp_distance = max(current_price * 0.04, min(tp_distance, current_price * 0.08))
                    take_profit = current_price + tp_distance

                    open_positions[pair] = {
                        "side": "buy",
                        "entry_price": current_price,
                        "quantity": quantity,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "trailing_stop": stop_loss,
                        "highest": current_price,
                    }

            # Equity curve
            equity_curve.append(capital)

        # Kalan açık pozisyonları kapat
        for pair, pos in list(open_positions.items()):
            if pair in processed_data:
                exit_price = processed_data[pair]["close"].iloc[-1]
                pnl_pct = ((exit_price - pos["entry_price"]) / pos["entry_price"]) * 100
                position_value = pos["quantity"] * pos["entry_price"]
                pnl = position_value * (pnl_pct / 100)
                fee = position_value * (TAKER_FEE + SLIPPAGE_PCT) * 2
                capital += pnl - fee
                total_fees += fee
                trades.append({
                    "symbol": pair, "side": pos["side"],
                    "entry_price": pos["entry_price"], "exit_price": exit_price,
                    "pnl": pnl - fee, "pnl_pct": pnl_pct, "fee": fee, "reason": "end_of_backtest",
                })

        # Sonuçları hesapla
        winning = [t for t in trades if t["pnl"] > 0]
        losing = [t for t in trades if t["pnl"] <= 0]

        avg_win = np.mean([t["pnl_pct"] for t in winning]) if winning else 0
        avg_loss = np.mean([t["pnl_pct"] for t in losing]) if losing else 0

        total_pnl = capital - self.initial_capital
        roi = (total_pnl / self.initial_capital) * 100
        win_rate = (len(winning) / len(trades) * 100) if trades else 0

        max_dd = 0
        peak = self.initial_capital
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio
        if daily_returns:
            daily_std = np.std(daily_returns)
            daily_mean = np.mean(daily_returns)
            sharpe = (daily_mean / daily_std * np.sqrt(365)) if daily_std > 0 else 0
        else:
            sharpe = 0

        # Profit factor
        gross_profit = sum(t["pnl"] for t in winning)
        gross_loss = abs(sum(t["pnl"] for t in losing))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        return BacktestResult(
            initial_capital=self.initial_capital,
            final_capital=capital,
            total_pnl=total_pnl + total_fees,
            total_fees=total_fees,
            net_pnl=total_pnl,
            roi=roi,
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            avg_trades_per_day=len(trades) / max(days, 1),
            daily_returns=daily_returns,
            equity_curve=equity_curve,
            trade_log=trades,
        )

    def _print_results(self, result: BacktestResult):
        """Sonuçları terminale yazdır."""
        print("\n" + "=" * 60)
        print("  📊 BACKTEST SONUÇLARI")
        print("=" * 60)

        print(f"\n  💰 Sermaye & ROI")
        print(f"  ─────────────────────────────────────")
        print(f"  Başlangıç Sermayesi : {format_currency(result.initial_capital)}")
        print(f"  Bitiş Sermayesi     : {format_currency(result.final_capital)}")
        print(f"  Net P&L             : {format_currency(result.net_pnl)}")
        print(f"  Toplam Fee          : {format_currency(result.total_fees)}")
        print(f"  ROI                 : {format_pct(result.roi)}")

        print(f"\n  📈 Trade İstatistikleri")
        print(f"  ─────────────────────────────────────")
        print(f"  Toplam Trade        : {result.total_trades}")
        print(f"  Günlük Ortalama     : ~{result.avg_trades_per_day:.0f} trade/gün")
        print(f"  Win Rate            : {result.win_rate:.1f}%")
        print(f"  Avg Win             : {format_pct(result.avg_win_pct)}")
        print(f"  Avg Loss            : {format_pct(result.avg_loss_pct)}")

        print(f"\n  🛡️  Risk Metrikleri")
        print(f"  ─────────────────────────────────────")
        print(f"  Max Drawdown        : {result.max_drawdown:.2f}%")
        print(f"  Sharpe Ratio        : {result.sharpe_ratio:.2f}")
        print(f"  Profit Factor       : {result.profit_factor:.2f}")

        print(f"\n  {'Kazanan':15} : {result.winning_trades}")
        print(f"  {'Kaybeden':15} : {result.losing_trades}")

        print("\n" + "=" * 60)

        # Hedef karşılaştırma
        print("\n  🎯 Hedef Karşılaştırma")
        print(f"  ─────────────────────────────────────")
        print(f"  ROI       : {format_pct(result.roi):>10} (Hedef: ~+28.57%)")
        print(f"  Trade/gün : {result.avg_trades_per_day:>10.0f} (Hedef: ~29)")
        print(f"  Win Rate  : {result.win_rate:>10.1f}% (Hedef: 50-60%)")
        print(f"  Avg Win   : {format_pct(result.avg_win_pct):>10} (Hedef: +4-8%)")
        print(f"  Avg Loss  : {format_pct(result.avg_loss_pct):>10} (Hedef: -1.2%)")
        print("=" * 60 + "\n")

    def _save_results(self, result: BacktestResult):
        """Sonuçları dosyaya kaydet."""
        output = {
            "timestamp": datetime.now().isoformat(),
            "initial_capital": result.initial_capital,
            "final_capital": result.final_capital,
            "net_pnl": result.net_pnl,
            "total_fees": result.total_fees,
            "roi": result.roi,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "avg_win_pct": result.avg_win_pct,
            "avg_loss_pct": result.avg_loss_pct,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
            "profit_factor": result.profit_factor,
            "avg_trades_per_day": result.avg_trades_per_day,
            "trade_count": len(result.trade_log),
        }

        with open("data/backtest_results.json", "w") as f:
            json.dump(output, f, indent=2, default=str)
        logger.info("Sonuçlar data/backtest_results.json dosyasına kaydedildi")

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            initial_capital=self.initial_capital,
            final_capital=self.initial_capital,
            total_pnl=0, total_fees=0, net_pnl=0, roi=0,
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0, avg_win_pct=0, avg_loss_pct=0,
            max_drawdown=0, sharpe_ratio=0, profit_factor=0,
            avg_trades_per_day=0,
        )


async def main():
    """Backtest'i çalıştır."""
    engine = BacktestEngine(initial_capital=BACKTEST_INITIAL_CAPITAL)
    result = await engine.run()
    return result


if __name__ == "__main__":
    asyncio.run(main())
