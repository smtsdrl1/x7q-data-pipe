"""
Performance Attribution Modülü
Her trade ve strateji için detaylı performans analizi yapar.

Yanıtladığı sorular:
- Hangi sembol en çok katkı sağladı?
- Hangi strateji en isabetli?
- Hangi piyasa rejimine en uyumlu?
- Kazanç mı kayıptan mı geliyor?
- Session bazında performans nasıl?
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from collections import defaultdict
from utils.logger import setup_logger

logger = setup_logger("Performance")

PERFORMANCE_FILE = "data/performance_attribution.json"


@dataclass
class TradeAttribution:
    """Tek trade için attribution verisi."""
    trade_id: str
    symbol: str
    side: str                     # buy/sell
    strategy: str                 # Ana strateji
    session: str                  # LONDON_KILLZONE etc.
    regime: str                   # TRENDING etc.
    entry_time: str
    exit_time: str
    pnl_pct: float
    pnl_usd: float
    holding_hours: float
    # Hangi faktörler en çok katkı sağladı?
    contributing_factors: dict    # {"fvg_fib": 15, "cvd": 5, "session": 3}
    score_at_entry: float
    
    # Sonuç
    outcome: str                  # WIN / LOSS / BREAKEVEN


@dataclass
class AttributionReport:
    """Bütünleşik attribution raporu."""
    period_start: str
    period_end: str
    total_trades: int
    total_pnl_pct: float
    
    # By symbol
    by_symbol: dict = field(default_factory=dict)
    
    # By strategy
    by_strategy: dict = field(default_factory=dict)
    
    # By session
    by_session: dict = field(default_factory=dict)
    
    # By regime
    by_regime: dict = field(default_factory=dict)
    
    # Factor contributions
    factor_contributions: dict = field(default_factory=dict)
    
    # Best/worst
    best_trade: dict = field(default_factory=dict)
    worst_trade: dict = field(default_factory=dict)
    
    # Time analysis
    best_hour: int = -1
    worst_hour: int = -1
    best_day: str = ""


class PerformanceAttributor:
    """Performance attribution motoru."""
    
    def __init__(self, filepath: str = PERFORMANCE_FILE):
        self.filepath = filepath
        self.trades: list[TradeAttribution] = []
        self._load()
    
    def record_trade(self, trade: TradeAttribution):
        """Yeni trade kaydı ekle."""
        self.trades.append(trade)
        self._save()
    
    def add_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        strategy: str,
        session: str,
        regime: str,
        entry_time: str,
        exit_time: str,
        pnl_pct: float,
        pnl_usd: float,
        score_at_entry: float = 0.0,
        contributing_factors: dict = None,
        holding_hours: float = 0.0,
    ):
        """Trade kayıt kısayolu."""
        if contributing_factors is None:
            contributing_factors = {}
        
        if pnl_pct > 0.005:
            outcome = "WIN"
        elif pnl_pct < -0.005:
            outcome = "LOSS"
        else:
            outcome = "BREAKEVEN"
        
        trade = TradeAttribution(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            strategy=strategy,
            session=session,
            regime=regime,
            entry_time=entry_time,
            exit_time=exit_time,
            pnl_pct=pnl_pct,
            pnl_usd=pnl_usd,
            holding_hours=holding_hours,
            contributing_factors=contributing_factors,
            score_at_entry=score_at_entry,
            outcome=outcome,
        )
        self.record_trade(trade)
        logger.debug(f"Trade kaydedildi: {trade_id} | {outcome} | {pnl_pct:+.2%}")
    
    def generate_report(self, last_n_trades: int = None) -> AttributionReport:
        """Attribution raporu üret."""
        trades = self.trades
        if last_n_trades:
            trades = trades[-last_n_trades:]
        
        if not trades:
            return AttributionReport(
                period_start="", period_end="",
                total_trades=0, total_pnl_pct=0.0
            )
        
        total_pnl = sum(t.pnl_pct for t in trades)
        
        # By symbol
        by_symbol: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        for t in trades:
            by_symbol[t.symbol]["count"] += 1
            by_symbol[t.symbol]["pnl"] += t.pnl_pct
            if t.outcome == "WIN":
                by_symbol[t.symbol]["wins"] += 1
        
        # Win rate ekle
        for sym, stats in by_symbol.items():
            stats["win_rate"] = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
        
        # By strategy
        by_strategy: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        for t in trades:
            by_strategy[t.strategy]["count"] += 1
            by_strategy[t.strategy]["pnl"] += t.pnl_pct
            if t.outcome == "WIN":
                by_strategy[t.strategy]["wins"] += 1
        
        for strat, stats in by_strategy.items():
            stats["win_rate"] = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
        
        # By session
        by_session: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        for t in trades:
            by_session[t.session]["count"] += 1
            by_session[t.session]["pnl"] += t.pnl_pct
            if t.outcome == "WIN":
                by_session[t.session]["wins"] += 1
        
        # By regime
        by_regime: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        for t in trades:
            by_regime[t.regime]["count"] += 1
            by_regime[t.regime]["pnl"] += t.pnl_pct
            if t.outcome == "WIN":
                by_regime[t.regime]["wins"] += 1
        
        # Factor contributions
        factor_contrib: dict[str, float] = defaultdict(float)
        for t in trades:
            if t.outcome == "WIN":
                for factor, score in t.contributing_factors.items():
                    factor_contrib[factor] += score
        
        # Best / worst trades
        sorted_trades = sorted(trades, key=lambda t: t.pnl_pct)
        best = asdict(sorted_trades[-1]) if sorted_trades else {}
        worst = asdict(sorted_trades[0]) if sorted_trades else {}
        
        period_start = trades[0].entry_time if trades else ""
        period_end = trades[-1].exit_time if trades else ""
        
        return AttributionReport(
            period_start=period_start,
            period_end=period_end,
            total_trades=len(trades),
            total_pnl_pct=total_pnl,
            by_symbol=dict(by_symbol),
            by_strategy=dict(by_strategy),
            by_session=dict(by_session),
            by_regime=dict(by_regime),
            factor_contributions=dict(factor_contrib),
            best_trade=best,
            worst_trade=worst,
        )
    
    def format_report_console(self, report: AttributionReport) -> str:
        """ASCII formatında rapor döndür."""
        lines = [
            "\n╔══════════════════════════════════════════════════╗",
            "║         📊 PERFORMANCE ATTRIBUTION RAPORU        ║",
            f"║  Toplam Trade: {report.total_trades:<5} | PnL: {report.total_pnl_pct:+.2f}%           ║",
            "╠══════════════════════════════════════════════════╣",
        ]
        
        # By Symbol (Top 5)
        lines.append("║  📌 SEMBOL BAZLI PERFORMANS                       ║")
        sorted_symbols = sorted(report.by_symbol.items(), key=lambda x: x[1]["pnl"], reverse=True)
        for sym, stats in sorted_symbols[:5]:
            bar = "+" if stats["pnl"] >= 0 else ""
            lines.append(
                f"║  {sym:<12} {bar}{stats['pnl']:.2f}% | WR:{stats['win_rate']:.0f}% | {stats['count']}T  "
                + " " * max(0, 50 - len(f"  {sym:<12} {bar}{stats['pnl']:.2f}% | WR:{stats['win_rate']:.0f}% | {stats['count']}T  ")) + "║"
            )
        
        lines.append("╠══════════════════════════════════════════════════╣")
        
        # By Strategy
        lines.append("║  🎯 STRATEJİ BAZLI PERFORMANS                     ║")
        sorted_strats = sorted(report.by_strategy.items(), key=lambda x: x[1]["pnl"], reverse=True)
        for strat, stats in sorted_strats[:5]:
            bar = "+" if stats["pnl"] >= 0 else ""
            lines.append(f"║  {strat[:12]:<12} {bar}{stats['pnl']:.2f}% | WR:{stats['win_rate']:.0f}%         ║")
        
        lines.append("╠══════════════════════════════════════════════════╣")
        
        # By Session
        lines.append("║  🕐 SESSION BAZLI PERFORMANS                      ║")
        for session, stats in sorted(report.by_session.items(), key=lambda x: x[1]["pnl"], reverse=True):
            bar = "+" if stats["pnl"] >= 0 else ""
            lines.append(f"║  {session[:20]:<20} {bar}{stats['pnl']:.2f}% | {stats['count']}T      ║")
        
        lines.append("╚══════════════════════════════════════════════════╝")
        return "\n".join(lines)
    
    def _load(self):
        """Kayıtlı attribution verilerini yükle."""
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.trades = [TradeAttribution(**t) for t in data.get("trades", [])]
                logger.debug(f"Attribution: {len(self.trades)} trade yüklendi")
        except Exception as e:
            logger.warning(f"Attribution yükleme hatası: {e}")
            self.trades = []
    
    def _save(self):
        """Attribution verilerini kaydet."""
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            data = {"trades": [asdict(t) for t in self.trades[-5000:]]}  # Son 5000 trade
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Attribution kayıt hatası: {e}")


# Global singleton
performance_attributor = PerformanceAttributor()
