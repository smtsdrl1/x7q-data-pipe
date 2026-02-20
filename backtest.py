"""
Backtest Engine — Kapsamlı Sinyal Analizi & Performans Raporu
Ölçer:  ✔ Tahmin doğruluğu (kaç doğru / kaç yanlış)
        ✔ Sinyal hunisi  (üretilen → filtreli → icra edilen → kazan/kaybet)
        ✔ Per-pair tablo
        ✔ Per-strateji katkısı
        ✔ Aylık P&L dökümü
        ✔ Sharpe / Sortino / Calmar / Profit Factor / Beklenti
"""

import asyncio
import sys
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

from strategies.multi_strategy import MultiStrategyEngine
from strategies.base_strategy import SignalType
from utils.data_fetcher import DataFetcher
from utils.indicators import TechnicalIndicators
from utils.logger import setup_logger
from utils.helpers import format_currency, format_pct
from config import (
    TRADING_PAIRS, BACKTEST_DAYS, BACKTEST_INITIAL_CAPITAL,
    PRIMARY_TIMEFRAME, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    MAKER_FEE, TAKER_FEE, SLIPPAGE_PCT, MAX_POSITION_PCT,
    TREND_FILTER_ENABLED, SIGNAL_ACCURACY_CANDLES,
)

logger = setup_logger("Backtest")

# ─── ANSI renk yardımcıları ─────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def clr(text, c): return f"{c}{text}{RESET}"
def green(t):  return clr(t, GREEN)
def red(t):    return clr(t, RED)
def yellow(t): return clr(t, YELLOW)
def bold(t):   return clr(t, BOLD)


# ─── Veri sınıfları ──────────────────────────────────────────────────────────
@dataclass
class TradeEntry:
    symbol: str
    side: str
    entry_idx: int
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    trailing_stop: float
    highest: float
    entry_time: datetime = None
    strategy_scores: dict = field(default_factory=dict)
    composite_score: float = 0.0


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    quantity: float
    gross_pnl: float
    fee: float
    net_pnl: float
    pnl_pct: float
    reason: str
    composite_score: float
    strategy_scores: dict = field(default_factory=dict)


@dataclass
class SignalRecord:
    symbol: str
    signal: str           # "BUY" | "SELL"
    idx: int
    price_at_signal: float
    price_after: float    # SIGNAL_ACCURACY_CANDLES mum sonraki fiyat
    composite_score: float
    correct: bool         # yön doğru mu?
    trend_filtered: bool
    strategy_scores: dict = field(default_factory=dict)


@dataclass
class BacktestResult:
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
    sortino_ratio: float
    calmar_ratio: float
    profit_factor: float
    expectancy: float
    avg_trades_per_day: float
    daily_returns: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    closed_trades: list = field(default_factory=list)
    signals_all: list = field(default_factory=list)
    per_pair: dict = field(default_factory=dict)
    per_strategy: dict = field(default_factory=dict)
    monthly_pnl: dict = field(default_factory=dict)
    signal_funnel: dict = field(default_factory=dict)


# ─── BacktestEngine ──────────────────────────────────────────────────────────
class BacktestEngine:

    def __init__(self, initial_capital: float = BACKTEST_INITIAL_CAPITAL):
        self.initial_capital = initial_capital
        self.strategy_engine = MultiStrategyEngine()
        self.data_fetcher = DataFetcher()
        self.indicators = TechnicalIndicators()

    # ── Ana giriş noktası ─────────────────────────────────────────────────
    async def run(self, pairs: list = None,
                  timeframe: str = PRIMARY_TIMEFRAME,
                  days: int = BACKTEST_DAYS,
                  silent: bool = False) -> BacktestResult:
        pairs = pairs or TRADING_PAIRS
        logger.info(f"Backtest başlıyor: {len(pairs)} pair, {days} gün, {timeframe}")

        await self.data_fetcher.initialize()
        all_data    = {}
        all_data_1h = {}
        candles_needed = self._estimate_candles(timeframe, days)
        candles_1h     = max(100, days * 24 + 50)  # 1h trend için yeterli mum

        for pair in pairs:
            try:
                df = await self.data_fetcher.fetch_ohlcv(pair, timeframe, limit=candles_needed)
                if not df.empty and len(df) >= 100:
                    all_data[pair] = df
                    logger.info(f"  ✓ {pair}: {len(df)} mum")
                    # 1h trend verisi aynı bağlantıda çek
                    df_1h = await self.data_fetcher.fetch_ohlcv(pair, "1h", limit=candles_1h)
                    if not df_1h.empty and len(df_1h) >= 55:
                        all_data_1h[pair] = df_1h
                else:
                    logger.warning(f"  ✗ {pair}: Yetersiz veri ({len(df)} mum)")
            except Exception as e:
                logger.error(f"  ✗ {pair}: {e}")

        await self.data_fetcher.close()

        if not all_data:
            logger.error("Hiç veri çekilemedi!")
            return self._empty_result()

        result = self._simulate(all_data, days, all_data_1h)
        if not silent:
            self._print_results(result)
            self._save_results(result)
        return result

    def _estimate_candles(self, timeframe: str, days: int) -> int:
        tf_minutes = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
        }
        minutes = tf_minutes.get(timeframe, 5)
        return min(int(1440 / minutes * days) + 200, 1000)

    # ── Simülasyon çekirdeği ──────────────────────────────────────────────
    def _simulate(self, all_data: dict, days: int,
                  all_data_1h: dict = None) -> BacktestResult:
        capital      = self.initial_capital
        peak_capital = capital
        total_fees   = 0.0
        closed_trades: list[ClosedTrade] = []
        signals_all:   list[SignalRecord] = []
        equity_curve  = []
        daily_returns = []

        # Göstergeleri hesapla
        processed = {}
        for pair, df in all_data.items():
            processed[pair] = self.indicators.calculate_all(df)

        # 1h trend lookup tabloları (EMA9 × EMA55)
        trend_dfs_1h = {}
        if all_data_1h:
            for pair, df1h in all_data_1h.items():
                d = df1h.copy()
                d["ema9_1h"]  = d["close"].ewm(span=9,  adjust=False).mean()
                d["ema55_1h"] = d["close"].ewm(span=55, adjust=False).mean()
                trend_dfs_1h[pair] = d
            logger.info(f"1h trend verisi hazır: {len(trend_dfs_1h)} pair")

        min_len   = min(len(df) for df in processed.values())
        start_idx = max(60, min_len - self._estimate_candles(PRIMARY_TIMEFRAME, days))

        open_pos: dict[str, TradeEntry] = {}
        prev_day     = None
        day_start    = capital

        # Sinyal hunisi sayaçları
        funnel = dict(
            scanned=0, generated=0, trend_filtered=0,
            score_filtered=0, executed=0, wins=0, losses=0,
        )

        for i in range(start_idx, min_len):
            for pair, df in processed.items():
                if i >= len(df):
                    continue

                current_price = float(df["close"].iloc[i])
                ts = df.index[i]
                current_time = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None

                # Günlük getiri takibi
                if current_time:
                    cur_day = current_time.date()
                    if prev_day and cur_day != prev_day:
                        daily_ret = (capital - day_start) / day_start * 100
                        daily_returns.append(daily_ret)
                        day_start = capital
                    prev_day = cur_day

                # ── Açık pozisyon yönetimi ────────────────────────────
                if pair in open_pos:
                    pos = open_pos[pair]

                    # Trailing stop güncelle
                    if pos.side == "buy" and current_price > pos.highest:
                        pos.highest = current_price
                        new_trail = current_price * 0.98
                        if new_trail > pos.trailing_stop:
                            pos.trailing_stop = new_trail

                    eff_sl = max(pos.stop_loss, pos.trailing_stop)
                    hit_sl = (pos.side == "buy" and current_price <= eff_sl)
                    hit_tp = (pos.side == "buy" and current_price >= pos.take_profit)

                    if hit_sl or hit_tp:
                        exit_price = eff_sl if hit_sl else pos.take_profit
                        pnl_pct    = (exit_price - pos.entry_price) / pos.entry_price * 100
                        pos_val    = pos.quantity * pos.entry_price
                        gross_pnl  = pos_val * pnl_pct / 100
                        fee        = pos_val * (TAKER_FEE + SLIPPAGE_PCT) * 2
                        net_pnl    = gross_pnl - fee
                        total_fees += fee
                        capital    += net_pnl
                        if capital > peak_capital:
                            peak_capital = capital

                        ct = ClosedTrade(
                            symbol=pair,
                            side=pos.side,
                            entry_price=pos.entry_price,
                            exit_price=exit_price,
                            entry_time=pos.entry_time or current_time,
                            exit_time=current_time,
                            quantity=pos.quantity,
                            gross_pnl=gross_pnl,
                            fee=fee,
                            net_pnl=net_pnl,
                            pnl_pct=pnl_pct,
                            reason="stop_loss" if hit_sl else "take_profit",
                            composite_score=pos.composite_score,
                            strategy_scores=pos.strategy_scores,
                        )
                        closed_trades.append(ct)
                        funnel["wins" if net_pnl > 0 else "losses"] += 1
                        del open_pos[pair]
                    continue

                # ── Yeni sinyal ara ───────────────────────────────────
                if len(open_pos) >= 5:
                    continue

                window = df.iloc[max(0, i - 100): i + 1]
                if len(window) < 60:
                    continue

                funnel["scanned"] += 1

                # 1h trend context: EMA9 vs EMA55 en son tamamlanan 1h barı
                trend_context = None
                if pair in trend_dfs_1h and current_time:
                    d1h = trend_dfs_1h[pair]
                    idx = d1h.index.searchsorted(current_time, side="right") - 1
                    if idx >= 55:
                        e9  = float(d1h["ema9_1h"].iloc[idx])
                        e55 = float(d1h["ema55_1h"].iloc[idx])
                        margin = e9 / e55 - 1.0
                        if margin > 0.001:
                            trend = "BULLISH"
                        elif margin < -0.001:
                            trend = "BEARISH"
                        else:
                            trend = "NEUTRAL"
                        trend_context = {"trend": trend}

                analysis = self.strategy_engine.analyze(
                    window, pair, trend_context=trend_context, backtest_dt=current_time
                )
                sig   = analysis["signal"]
                score = analysis["composite_score"]
                # Strateji güçleri Signal nesnelerinden çek (0-1 ölçekli)
                strat_scores: dict[str, float] = {}
                for sig_obj in analysis.get("signals", []):
                    name = sig_obj.strategy_name
                    if sig_obj.signal_type == SignalType.BUY:
                        strat_scores[name] = float(sig_obj.strength)
                    elif sig_obj.signal_type == SignalType.SELL:
                        strat_scores[name] = float(1.0 - sig_obj.strength)
                    else:
                        strat_scores[name] = 0.5

                if sig not in (SignalType.BUY, SignalType.SELL):
                    continue

                funnel["generated"] += 1

                # Trend filtresi (EMA9 vs EMA55 kullanılarak)
                trend_filtered = False
                if TREND_FILTER_ENABLED:
                    e9_col  = next((c for c in df.columns if "ema_9"  in c or "ema9"  in c), None)
                    e55_col = next((c for c in df.columns if "ema_55" in c or "ema55" in c), None)
                    if e9_col and e55_col:
                        e9  = float(df[e9_col].iloc[i])
                        e55 = float(df[e55_col].iloc[i])
                        if sig == SignalType.BUY  and e9 < e55:
                            trend_filtered = True
                        elif sig == SignalType.SELL and e9 > e55:
                            trend_filtered = True

                # Sinyal doğruluk kaydı (trend filtreden bağımsız, ham tahmin kalitesi)
                future_idx = i + SIGNAL_ACCURACY_CANDLES
                if future_idx < len(df):
                    future_price = float(df["close"].iloc[future_idx])
                    correct = (future_price > current_price if sig == SignalType.BUY
                               else future_price < current_price)
                    signals_all.append(SignalRecord(
                        symbol=pair,
                        signal="BUY" if sig == SignalType.BUY else "SELL",
                        idx=i,
                        price_at_signal=current_price,
                        price_after=future_price,
                        composite_score=score,
                        correct=correct,
                        trend_filtered=trend_filtered,
                        strategy_scores=strat_scores,
                    ))

                if trend_filtered:
                    funnel["trend_filtered"] += 1
                    continue

                # Skor filtresi
                if sig == SignalType.BUY and score < 0.55:
                    funnel["score_filtered"] += 1
                    continue
                if sig == SignalType.SELL and score > 0.45:
                    funnel["score_filtered"] += 1
                    continue

                # Yalnızca BUY pozisyon açıyoruz (spot mod)
                if sig == SignalType.BUY:
                    funnel["executed"] += 1
                    pos_val  = capital * MAX_POSITION_PCT
                    qty      = pos_val / current_price
                    atr      = analysis.get("atr", current_price * 0.01)
                    sl_dist  = max(atr * 1.5, current_price * STOP_LOSS_PCT)
                    tp_dist  = max(current_price * 0.04,
                                   min(sl_dist * 3.5, current_price * 0.08))
                    open_pos[pair] = TradeEntry(
                        symbol=pair,
                        side="buy",
                        entry_idx=i,
                        entry_price=current_price,
                        quantity=qty,
                        stop_loss=current_price - sl_dist,
                        take_profit=current_price + tp_dist,
                        trailing_stop=current_price - sl_dist,
                        highest=current_price,
                        entry_time=current_time,
                        strategy_scores=strat_scores,
                        composite_score=score,
                    )

            equity_curve.append(capital)

        # Kalan pozisyonları kapat (end-of-backtest)
        for pair, pos in list(open_pos.items()):
            if pair in processed:
                exit_price = float(processed[pair]["close"].iloc[-1])
                pnl_pct    = (exit_price - pos.entry_price) / pos.entry_price * 100
                pos_val    = pos.quantity * pos.entry_price
                gross_pnl  = pos_val * pnl_pct / 100
                fee        = pos_val * (TAKER_FEE + SLIPPAGE_PCT) * 2
                net_pnl    = gross_pnl - fee
                total_fees += fee
                capital    += net_pnl
                closed_trades.append(ClosedTrade(
                    symbol=pair, side=pos.side,
                    entry_price=pos.entry_price, exit_price=exit_price,
                    entry_time=pos.entry_time, exit_time=None,
                    quantity=pos.quantity, gross_pnl=gross_pnl, fee=fee,
                    net_pnl=net_pnl, pnl_pct=pnl_pct,
                    reason="end_of_backtest",
                    composite_score=pos.composite_score,
                    strategy_scores=pos.strategy_scores,
                ))
                funnel["wins" if net_pnl > 0 else "losses"] += 1

        # ── Temel metrikler ───────────────────────────────────────────────
        wins_t   = [t for t in closed_trades if t.net_pnl > 0]
        losses_t = [t for t in closed_trades if t.net_pnl <= 0]
        n        = len(closed_trades)

        net_pnl  = capital - self.initial_capital
        roi      = net_pnl / self.initial_capital * 100
        win_rate = len(wins_t) / n * 100 if n else 0
        avg_win  = float(np.mean([t.pnl_pct for t in wins_t]))   if wins_t   else 0.0
        avg_loss = float(np.mean([t.pnl_pct for t in losses_t])) if losses_t else 0.0

        gross_profit = sum(t.net_pnl for t in wins_t)
        gross_loss   = abs(sum(t.net_pnl for t in losses_t))
        pf           = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        expectancy   = ((win_rate / 100 * (avg_win / 100)) -
                        ((1 - win_rate / 100) * abs(avg_loss / 100))) * self.initial_capital

        # Max drawdown
        max_dd = 0.0
        peak   = self.initial_capital
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Sharpe
        sharpe = 0.0
        if len(daily_returns) > 1:
            std = float(np.std(daily_returns))
            if std > 0:
                sharpe = float(np.mean(daily_returns)) / std * np.sqrt(365)

        # Sortino (sadece negatif günler std'si)
        sortino = 0.0
        neg_rets = [r for r in daily_returns if r < 0]
        if neg_rets and np.std(neg_rets) > 0:
            sortino = float(np.mean(daily_returns)) / float(np.std(neg_rets)) * np.sqrt(365)

        # Calmar
        calmar = roi / max_dd if max_dd > 0 else float("inf")

        # ── Per-pair ─────────────────────────────────────────────────────
        per_pair: dict = defaultdict(lambda: {
            "trades": 0, "wins": 0, "losses": 0,
            "net_pnl": 0.0, "best_pct": -999.0, "worst_pct": 999.0,
            "total_pct": 0.0,
        })
        for t in closed_trades:
            d = per_pair[t.symbol]
            d["trades"]    += 1
            d["net_pnl"]   += t.net_pnl
            d["total_pct"] += t.pnl_pct
            d["wins"]      += 1 if t.net_pnl > 0 else 0
            d["losses"]    += 0 if t.net_pnl > 0 else 1
            if t.pnl_pct > d["best_pct"]:  d["best_pct"]  = t.pnl_pct
            if t.pnl_pct < d["worst_pct"]: d["worst_pct"] = t.pnl_pct
        for sym in per_pair:
            d = per_pair[sym]
            d["win_rate"] = d["wins"] / d["trades"] * 100 if d["trades"] else 0
            d["avg_pct"]  = d["total_pct"] / d["trades"] if d["trades"] else 0

        # ── Per-strateji katkısı ─────────────────────────────────────────
        strategy_names = self.strategy_engine.get_strategy_names()
        per_strategy: dict = {
            s: {"buy_fire": 0, "sell_fire": 0, "total_fire": 0,
                "win_contrib": 0, "loss_contrib": 0}
            for s in strategy_names
        }
        for sig in signals_all:
            for s in strategy_names:
                sc = sig.strategy_scores.get(s, 0.0)
                if sig.signal == "BUY"  and sc > 0.6:
                    per_strategy[s]["buy_fire"] += 1
                    per_strategy[s]["total_fire"] += 1
                elif sig.signal == "SELL" and sc < 0.4:
                    per_strategy[s]["sell_fire"] += 1
                    per_strategy[s]["total_fire"] += 1
        for t in closed_trades:
            for s in strategy_names:
                sc = t.strategy_scores.get(s, 0.0)
                if sc > 0.6:
                    if t.net_pnl > 0: per_strategy[s]["win_contrib"]  += 1
                    else:             per_strategy[s]["loss_contrib"] += 1

        # ── Aylık P&L ────────────────────────────────────────────────────
        monthly: dict = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
        for t in closed_trades:
            if t.exit_time:
                key = t.exit_time.strftime("%Y-%m")
                monthly[key]["pnl"]    += t.net_pnl
                monthly[key]["trades"] += 1
                if t.net_pnl > 0:
                    monthly[key]["wins"] += 1

        return BacktestResult(
            initial_capital=self.initial_capital,
            final_capital=capital,
            total_pnl=net_pnl + total_fees,
            total_fees=total_fees,
            net_pnl=net_pnl,
            roi=roi,
            total_trades=n,
            winning_trades=len(wins_t),
            losing_trades=len(losses_t),
            win_rate=win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            profit_factor=pf,
            expectancy=expectancy,
            avg_trades_per_day=n / max(days, 1),
            daily_returns=daily_returns,
            equity_curve=equity_curve,
            closed_trades=[t.__dict__ for t in closed_trades],
            signals_all=signals_all,
            per_pair=dict(per_pair),
            per_strategy=per_strategy,
            monthly_pnl=dict(monthly),
            signal_funnel=funnel,
        )

    # ── Konsol raporu ────────────────────────────────────────────────────
    def _print_results(self, r: BacktestResult):
        W = 66

        def section(title):
            bar = "═" * (W - 4)
            pad = W - 6 - len(title)
            print(f"\n  ╔{bar}╗")
            print(f"  ║  {bold(title)}{' ' * max(0, pad)}  ║")
            print(f"  ╚{bar}╝")

        def _pnl_str(val):
            s = format_currency(val)
            return green(s) if val >= 0 else red(s)

        def _pct_str(val):
            s = format_pct(val)
            return green(s) if val >= 0 else red(s)

        # ── 1. Sermaye & ROI ─────────────────────────────────────────────
        section("💰  SERMAYE & ROI")
        print(f"  Başlangıç Sermayesi : {format_currency(r.initial_capital)}")
        print(f"  Bitiş Sermayesi     : {format_currency(r.final_capital)}")
        print(f"  Net P&L             : {_pnl_str(r.net_pnl)}")
        print(f"  Toplam Ücret        : {format_currency(r.total_fees)}")
        print(f"  ROI                 : {_pct_str(r.roi)}")

        # ── 2. Trade İstatistikleri ──────────────────────────────────────
        section("📈  TRADE İSTATİSTİKLERİ")
        wr_s = green(f"{r.win_rate:.1f}%") if r.win_rate >= 50 else red(f"{r.win_rate:.1f}%")
        print(f"  Toplam Trade    : {r.total_trades}")
        print(f"  Günlük Ort.     : ~{r.avg_trades_per_day:.1f} trade/gün")
        print(f"  Win Rate        : {wr_s}  ({r.winning_trades}W / {r.losing_trades}L)")
        print(f"  Avg Win         : {green(format_pct(r.avg_win_pct))}")
        print(f"  Avg Loss        : {red(format_pct(r.avg_loss_pct))}")
        exp_s = format_currency(r.expectancy)
        print(f"  Beklenti ($/tr) : {green(exp_s) if r.expectancy >= 0 else red(exp_s)}")

        # ── 3. Risk Metrikleri ───────────────────────────────────────────
        section("🛡️   RİSK METRİKLERİ")
        pf_s = green(f"{r.profit_factor:.2f}") if r.profit_factor >= 1.5 else yellow(f"{r.profit_factor:.2f}")
        calmar_s = f"{r.calmar_ratio:.2f}" if r.calmar_ratio != float("inf") else "∞"
        print(f"  Max Drawdown    : {red(f'{r.max_drawdown:.2f}%')}")
        print(f"  Sharpe Ratio    : {r.sharpe_ratio:.3f}  (>1.0 iyi)")
        print(f"  Sortino Ratio   : {r.sortino_ratio:.3f}")
        print(f"  Calmar Ratio    : {calmar_s}")
        print(f"  Profit Factor   : {pf_s}  (>1.5 iyi)")

        # ── 4. Sinyal Hunisi ─────────────────────────────────────────────
        section("🔍  SİNYAL HUNİSİ")
        f = r.signal_funnel
        sc = max(f["scanned"], 1)
        ge = max(f["generated"], 1)
        print(f"  Taranan           : {f['scanned']:>6}")
        print(f"  Sinyal Üretilen   : {f['generated']:>6}  ({f['generated']/sc*100:.1f}%)")
        aft_trend = f["generated"] - f["trend_filtered"]
        print(f"  Trend Filtreli  - : {f['trend_filtered']:>6}  → kalan: {aft_trend}")
        aft_score = aft_trend - f["score_filtered"]
        print(f"  Skor Filtreli   - : {f['score_filtered']:>6}  → kalan: {aft_score}")
        print(f"  İcra Edilen       : {f['executed']:>6}  ({f['executed']/ge*100:.1f}%)")
        print(f"  ✅  Kazanan       : {f['wins']:>6}")
        print(f"  ❌  Kaybeden      : {f['losses']:>6}")

        # ── 5. Tahmin Doğruluğu ──────────────────────────────────────────
        section("🎯  TAHMİN DOĞRULUĞU  (ham yön isabeti)")
        sigs = r.signals_all
        if sigs:
            tot = len(sigs)
            cor = sum(1 for s in sigs if s.correct)
            acc = cor / tot * 100
            acc_s = (green(f"{acc:.1f}%") if acc >= 55
                     else yellow(f"{acc:.1f}%") if acc >= 45
                     else red(f"{acc:.1f}%"))

            buy_s  = [s for s in sigs if s.signal == "BUY"]
            sell_s = [s for s in sigs if s.signal == "SELL"]
            b_cor  = sum(1 for s in buy_s  if s.correct)
            s_cor  = sum(1 for s in sell_s if s.correct)
            b_acc  = b_cor / len(buy_s)  * 100 if buy_s  else 0
            s_acc  = s_cor / len(sell_s) * 100 if sell_s else 0
            tf_n   = sum(1 for s in sigs if s.trend_filtered)

            print(f"  Toplam Sinyal    : {tot}")
            print(f"  ✅  Doğru        : {cor}  ({acc_s})")
            print(f"  ❌  Yanlış       : {tot - cor}")
            print(f"  BUY  doğruluğu  : {green(f'{b_acc:.1f}%')}  ({len(buy_s)} sinyal)")
            print(f"  SELL doğruluğu  : {green(f'{s_acc:.1f}%')}  ({len(sell_s)} sinyal)")
            print(f"  Trend bloke     : {tf_n}")

            # Composite skor dilimlerine göre doğruluk
            print()
            print(f"  {'Skor Aralığı':<14} {'Sinyal':>7}  {'Doğru':>7}  {'Oran':>8}  İstogram")
            print(f"  {'─' * 58}")
            bins = [(0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 1.01)]
            for lo, hi in bins:
                bucket = [s for s in sigs if lo <= s.composite_score < hi]
                if bucket:
                    c    = sum(1 for s in bucket if s.correct)
                    acc_b = c / len(bucket) * 100
                    bar  = "█" * int(acc_b / 5)
                    acc_c = green(f"{acc_b:5.1f}%") if acc_b >= 55 else red(f"{acc_b:5.1f}%")
                    print(f"  {lo:.2f} – {hi:.2f}     {len(bucket):>7}  {c:>7}  {acc_c}  {bar}")
        else:
            print("  Sinyal kaydı bulunamadı.")

        # ── 6. Per-Pair Performans ────────────────────────────────────────
        section("📊  PER-PAIR PERFORMANS")
        print(f"  {'Pair':<12} {'Trade':>6}  {'Win%':>7}  {'P&L($)':>10}  {'Avg%':>7}  {'Best%':>7}  {'Worst%':>8}")
        print(f"  {'─' * 62}")
        for sym, d in sorted(r.per_pair.items(), key=lambda x: x[1]["net_pnl"], reverse=True):
            wr_c  = (green(f"{d['win_rate']:5.1f}%") if d["win_rate"] >= 50
                     else red(f"{d["win_rate"]:5.1f}%"))
            pnl_c = (green(f"{d['net_pnl']:9.2f}") if d["net_pnl"] >= 0
                     else red(f"{d["net_pnl"]:9.2f}"))
            best  = d["best_pct"]  if d["best_pct"]  != -999 else 0
            worst = d["worst_pct"] if d["worst_pct"] !=  999 else 0
            print(f"  {sym:<12} {d['trades']:>6}  {wr_c}  {pnl_c}  "
                  f"{d['avg_pct']:>6.2f}%  {best:>6.2f}%  {worst:>7.2f}%")

        # ── 7. Strateji Katkısı ───────────────────────────────────────────
        section("🧠  STRATEJİ KATKISI")
        print(f"  {'Strateji':<14} {'BUY fire':>9}  {'SELL fire':>10}  {'Win katkı':>10}  {'Loss katkı':>11}  {'İsabet':>8}")
        print(f"  {'─' * 68}")
        for s, d in sorted(r.per_strategy.items(),
                           key=lambda x: x[1]["total_fire"], reverse=True):
            tc   = d["win_contrib"] + d["loss_contrib"]
            wp   = d["win_contrib"] / tc * 100 if tc else 0
            wp_s = green(f"{wp:.0f}%") if wp >= 55 else red(f"{wp:.0f}%")
            print(f"  {s:<14} {d['buy_fire']:>9}  {d['sell_fire']:>10}  "
                  f"{d['win_contrib']:>10}  {d['loss_contrib']:>11}  {wp_s:>8}")

        # ── 8. Aylık P&L ─────────────────────────────────────────────────
        if r.monthly_pnl:
            section("📅  AYLIK P&L")
            max_abs = max(abs(v["pnl"]) for v in r.monthly_pnl.values()) or 1
            print(f"  {'Ay':<10} {'Trade':>7}  {'Win':>5}  {'Win%':>7}  {'P&L($)':>10}  İstogram")
            print(f"  {'─' * 60}")
            for month in sorted(r.monthly_pnl):
                d   = r.monthly_pnl[month]
                wpc = d["wins"] / max(d["trades"], 1) * 100
                bar = int(abs(d["pnl"]) / max_abs * 25)
                bar_s = (green("▮" * bar) if d["pnl"] >= 0 else red("▮" * bar))
                pnl_s = green(f"{d['pnl']:9.2f}") if d["pnl"] >= 0 else red(f"{d['pnl']:9.2f}")
                print(f"  {month:<10} {d['trades']:>7}  {d['wins']:>5}  "
                      f"{wpc:>6.1f}%  {pnl_s}  {bar_s}")

        # ── 9. Hedef Karşılaştırma ────────────────────────────────────────
        section("🎯  HEDEF KARŞILAŞTIRMA")
        def cmp_val(val, lo, hi, fmt):
            s = fmt(val)
            return green(s) if lo <= val <= hi else (yellow(s) if val > 0 else red(s))
        print(f"  ROI        : "
              f"{cmp_val(r.roi, 20, 50, lambda v: f'{v:.2f}%'):>14}   (Hedef: +20 – 50%)")
        print(f"  Trade/gün  : {r.avg_trades_per_day:>12.1f}   (Hedef: 10 – 30)")
        print(f"  Win Rate   : "
              f"{cmp_val(r.win_rate, 50, 70, lambda v: f'{v:.1f}%'):>14}   (Hedef: 50 – 70%)")
        print(f"  Sharpe     : {r.sharpe_ratio:>12.2f}   (Hedef: > 1.0)")
        print(f"  Max DD     : {r.max_drawdown:>11.2f}%   (Hedef: < 15%)")
        print()

    # ── JSON kayıt ────────────────────────────────────────────────────────
    def _save_results(self, r: BacktestResult):
        sigs = r.signals_all
        tot  = len(sigs)
        cor  = sum(1 for s in sigs if s.correct)

        output = {
            "timestamp":          datetime.now().isoformat(),
            "initial_capital":    r.initial_capital,
            "final_capital":      r.final_capital,
            "net_pnl":            r.net_pnl,
            "total_fees":         r.total_fees,
            "roi":                r.roi,
            "total_trades":       r.total_trades,
            "win_rate":           r.win_rate,
            "avg_win_pct":        r.avg_win_pct,
            "avg_loss_pct":       r.avg_loss_pct,
            "max_drawdown":       r.max_drawdown,
            "sharpe_ratio":       r.sharpe_ratio,
            "sortino_ratio":      r.sortino_ratio,
            "calmar_ratio":       r.calmar_ratio if r.calmar_ratio != float("inf") else None,
            "profit_factor":      r.profit_factor if r.profit_factor != float("inf") else None,
            "expectancy":         r.expectancy,
            "avg_trades_per_day": r.avg_trades_per_day,
            "signal_accuracy": {
                "total":        tot,
                "correct":      cor,
                "wrong":        tot - cor,
                "accuracy_pct": cor / tot * 100 if tot else 0,
            },
            "signal_funnel": r.signal_funnel,
            "per_pair":      r.per_pair,
            "monthly_pnl":   r.monthly_pnl,
        }

        os.makedirs("data", exist_ok=True)
        with open("data/backtest_results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, default=str)
        logger.info("Sonuçlar → data/backtest_results.json")

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            initial_capital=self.initial_capital,
            final_capital=self.initial_capital,
            total_pnl=0, total_fees=0, net_pnl=0, roi=0,
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0, avg_win_pct=0, avg_loss_pct=0,
            max_drawdown=0, sharpe_ratio=0, sortino_ratio=0,
            calmar_ratio=0, profit_factor=0, expectancy=0,
            avg_trades_per_day=0,
        )


# ─── Walk-Forward Optimization ──────────────────────────────────────────────

class WalkForwardOptimizer:
    """In-sample eğit / out-of-sample test et (Walk-Forward Optimization)."""

    def __init__(self, pairs: list[str], n_windows: int = 5,
                 train_ratio: float = 0.7,
                 initial_capital: float = BACKTEST_INITIAL_CAPITAL):
        self.pairs = pairs
        self.n_windows = n_windows
        self.train_ratio = train_ratio
        self.initial_capital = initial_capital
        self.logger = setup_logger("WFO")

    async def run(self) -> list[dict]:
        """Her pencerede backtest çalıştır, OOS sonuçları topla."""
        self.logger.info(
            f"Walk-Forward başlıyor: {self.n_windows} pencere, "
            f"train={self.train_ratio:.0%}"
        )
        from utils.data_fetcher import DataFetcher
        fetcher = DataFetcher()

        # Toplam veri çekilecek gün = BACKTEST_DAYS
        total_days = BACKTEST_DAYS
        window_size = total_days // self.n_windows
        results = []

        async with fetcher:
            for w in range(self.n_windows):
                is_days = max(1, int(window_size * self.train_ratio))
                oos_days = window_size - is_days

                # IS/OOS zaman dilimlerini hesapla
                window_end = total_days - w * window_size
                is_start = window_end
                is_end   = window_end - is_days
                oos_end  = window_end - window_size

                self.logger.info(
                    f"Pencere {w+1}/{self.n_windows}: "
                    f"IS [-{is_start}d → -{is_end}d], "
                    f"OOS [-{is_end}d → -{oos_end}d]"
                )

                # IS backtest
                try:
                    is_engine = BacktestEngine(initial_capital=self.initial_capital)
                    is_result = await is_engine.run(silent=True, days=is_days)

                    # OOS backtest
                    oos_engine = BacktestEngine(initial_capital=self.initial_capital)
                    oos_result = await oos_engine.run(silent=True, days=oos_days)

                    window_data = {
                        "window": w + 1,
                        "is_days": is_days,
                        "oos_days": oos_days,
                        "is_roi": getattr(is_result, "roi", 0),
                        "oos_roi": getattr(oos_result, "roi", 0),
                        "is_sharpe": getattr(is_result, "sharpe_ratio", 0),
                        "oos_sharpe": getattr(oos_result, "sharpe_ratio", 0),
                        "is_win_rate": getattr(is_result, "win_rate", 0),
                        "oos_win_rate": getattr(oos_result, "win_rate", 0),
                        "is_drawdown": getattr(is_result, "max_drawdown", 0),
                        "oos_drawdown": getattr(oos_result, "max_drawdown", 0),
                        "degradation": getattr(is_result, "roi", 0) - getattr(oos_result, "roi", 0),
                    }
                    results.append(window_data)
                    self.logger.info(
                        f"  IS ROI: {window_data['is_roi']:.2f}% | "
                        f"OOS ROI: {window_data['oos_roi']:.2f}% | "
                        f"Degradation: {window_data['degradation']:.2f}%"
                    )
                except Exception as e:
                    self.logger.error(f"Pencere {w+1} hatası: {e}")

        self._print_summary(results)
        self._save_results(results)
        return results

    def _print_summary(self, results: list[dict]):
        if not results:
            return
        oos_rois = [r["oos_roi"] for r in results]
        avg_oos = sum(oos_rois) / len(oos_rois)
        degradations = [r["degradation"] for r in results]
        avg_deg = sum(degradations) / len(degradations)
        positive_oos = sum(1 for r in oos_rois if r > 0)

        print(f"\n{'─'*60}")
        print(bold("  WALK-FORWARD OPTİMİZASYON RAPORU"))
        print(f"{'─'*60}")
        print(f"  Pencereler: {len(results)}")
        print(f"  Ort. OOS ROI:      {avg_oos:.2f}%")
        print(f"  Ort. Degradasyon:  {avg_deg:.2f}%")
        print(f"  Karlı OOS pencere: {positive_oos}/{len(results)}")
        print(f"{'─'*60}\n")

        for r in results:
            is_roi  = green(f"{r['is_roi']:+.2f}%") if r['is_roi'] > 0 else red(f"{r['is_roi']:+.2f}%")
            oos_roi = green(f"{r['oos_roi']:+.2f}%") if r['oos_roi'] > 0 else red(f"{r['oos_roi']:+.2f}%")
            deg     = red(f"{r['degradation']:+.2f}%") if r['degradation'] > 2 else green(f"{r['degradation']:+.2f}%")
            print(f"  Pencere {r['window']}: IS={is_roi} | OOS={oos_roi} | Deg={deg}")

        assessment = (
            "✅ STRATEJİ TUTARLI — OOS performans kabul edilebilir"
            if avg_deg < 5 and positive_oos / len(results) >= 0.6
            else "⚠️  STRATEJİ AŞIRI UYUMU — Parametre optimizasyonu gerekebilir"
        )
        print(f"\n  {assessment}\n")

    def _save_results(self, results: list[dict]):
        os.makedirs("data", exist_ok=True)
        with open("data/walk_forward_results.json", "w") as f:
            json.dump(results, f, indent=2)
        self.logger.info("Walk-forward sonuçları → data/walk_forward_results.json")


# ─── A/B Strategy Testing ────────────────────────────────────────────────────

class ABStrategyTester:
    """İki farklı konfigürasyonu A/B test et."""

    def __init__(self, config_a: dict, config_b: dict,
                 initial_capital: float = BACKTEST_INITIAL_CAPITAL):
        """
        Args:
            config_a: A varyantı için geçici config overrides {key: value}
            config_b: B varyantı için geçici config overrides {key: value}
            initial_capital: Başlangıç sermayesi
        """
        import config as _cfg
        self.config_a = config_a
        self.config_b = config_b
        self.initial_capital = initial_capital
        self._cfg = _cfg
        self.logger = setup_logger("ABTest")

    def _apply_config(self, overrides: dict):
        """Geçici olarak config değerlerini override et."""
        original = {}
        for k, v in overrides.items():
            if hasattr(self._cfg, k):
                original[k] = getattr(self._cfg, k)
                setattr(self._cfg, k, v)
        return original

    def _restore_config(self, original: dict):
        """Config değerlerini geri yükle."""
        for k, v in original.items():
            setattr(self._cfg, k, v)

    async def run(self) -> dict:
        """A ve B varyantlarını çalıştır, karşılaştır."""
        self.logger.info("A/B Test başlıyor...")
        self.logger.info(f"  A: {self.config_a}")
        self.logger.info(f"  B: {self.config_b}")

        # A varyantı
        orig_a = self._apply_config(self.config_a)
        try:
            engine_a = BacktestEngine(initial_capital=self.initial_capital)
            result_a = await engine_a.run(silent=True)
        finally:
            self._restore_config(orig_a)

        # B varyantı
        orig_b = self._apply_config(self.config_b)
        try:
            engine_b = BacktestEngine(initial_capital=self.initial_capital)
            result_b = await engine_b.run(silent=True)
        finally:
            self._restore_config(orig_b)

        comparison = self._compare(result_a, result_b)
        self._print_comparison(comparison)
        self._save_comparison(comparison)
        return comparison

    def _compare(self, a, b) -> dict:
        def safe(result, attr):
            return getattr(result, attr, 0) if result else 0

        metrics = ["roi", "win_rate", "sharpe_ratio", "max_drawdown",
                   "profit_factor", "expectancy", "total_trades"]
        comp = {"config_a": self.config_a, "config_b": self.config_b}
        score_a, score_b = 0, 0

        for m in metrics:
            va, vb = safe(a, m), safe(b, m)
            comp[m] = {"a": round(va, 4), "b": round(vb, 4),
                       "diff": round(vb - va, 4)}
            # Drawdown: daha düşük iyidir
            if m == "max_drawdown":
                if va < vb:
                    score_a += 1
                elif vb < va:
                    score_b += 1
            else:
                if va > vb:
                    score_a += 1
                elif vb > va:
                    score_b += 1

        comp["score_a"] = score_a
        comp["score_b"] = score_b
        comp["winner"] = "A" if score_a > score_b else ("B" if score_b > score_a else "TIE")
        return comp

    def _print_comparison(self, comp: dict):
        print(f"\n{'─'*70}")
        print(bold("  A/B STRATEJİ TEST RAPORU"))
        print(f"{'─'*70}")
        print(f"  A Konfigürasyonu: {comp['config_a']}")
        print(f"  B Konfigürasyonu: {comp['config_b']}")
        print(f"{'─'*70}")
        print(f"  {'Metrik':<22} {'A':>10} {'B':>10} {'Fark (B-A)':>12}")
        print(f"  {'-'*56}")
        color_map = {
            "roi": (True, green, red), "win_rate": (True, green, red),
            "sharpe_ratio": (True, green, red), "max_drawdown": (False, red, green),
            "profit_factor": (True, green, red), "expectancy": (True, green, red),
            "total_trades": (True, green, red),
        }
        for m, v in comp.items():
            if not isinstance(v, dict) or "a" not in v:
                continue
            higher_better, better_fn, worse_fn = color_map.get(m, (True, green, red))
            diff = v["diff"]
            if higher_better:
                diff_str = f"+{diff:.4f}" if diff > 0 else f"{diff:.4f}"
                diff_colored = green(diff_str) if diff > 0 else (red(diff_str) if diff < 0 else diff_str)
            else:
                diff_str = f"+{diff:.4f}" if diff > 0 else f"{diff:.4f}"
                diff_colored = red(diff_str) if diff > 0 else (green(diff_str) if diff < 0 else diff_str)
            print(f"  {m:<22} {v['a']:>10.4f} {v['b']:>10.4f} {diff_colored:>20}")

        print(f"{'─'*70}")
        winner = comp["winner"]
        print(f"  Puan: A={comp['score_a']} | B={comp['score_b']} | "
              f"Kazanan: {bold(winner)}\n")

    def _save_comparison(self, comp: dict):
        os.makedirs("data", exist_ok=True)
        with open("data/ab_test_results.json", "w") as f:
            json.dump(comp, f, indent=2, default=str)
        self.logger.info("A/B test sonuçları → data/ab_test_results.json")


# ─── Giriş noktası ──────────────────────────────────────────────────────────
async def main():
    import sys
    args = sys.argv[1:]

    if "walkforward" in args or "--wfo" in args:
        # Walk-forward optimization
        wfo = WalkForwardOptimizer(pairs=TRADING_PAIRS, n_windows=5)
        await wfo.run()
    elif "abtest" in args or "--ab" in args:
        # A/B Test örneği: trend filter açık vs kapalı
        tester = ABStrategyTester(
            config_a={"TREND_FILTER_ENABLED": True},
            config_b={"TREND_FILTER_ENABLED": False},
        )
        await tester.run()
    else:
        engine = BacktestEngine(initial_capital=BACKTEST_INITIAL_CAPITAL)
        await engine.run()


if __name__ == "__main__":
    asyncio.run(main())

