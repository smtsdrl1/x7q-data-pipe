"""
Monte Carlo Risk Simülasyonu
Geçmiş trade sonuçlarını kullanarak:
1. Beklenen max drawdown dağılımını hesapla
2. Ruin riski (% sermaye kaybı) simüle et
3. Güven aralıklarıyla gelecek performansı tahmin et
"""

import numpy as np
from dataclasses import dataclass
from utils.logger import setup_logger

logger = setup_logger("MonteCarlo")


@dataclass
class SimulationResult:
    """Monte Carlo simülasyon sonuçları."""
    n_simulations: int
    n_trades_per_sim: int
    
    # Drawdown istatistikleri
    median_max_dd: float
    p95_max_dd: float      # %95 güven ile max drawdown
    p99_max_dd: float      # %99 güven ile max drawdown
    
    # PnL istatistikleri
    median_final_pnl: float
    p5_final_pnl: float    # Kötü %5'lik senaryo
    p95_final_pnl: float   # İyi %95'lik senaryo
    
    # Ruin riski
    ruin_risk_pct: float   # Sermayenin %50'sini kaybetme olasılığı
    
    # Continuous compound return
    cagr_median: float
    
    # Kelly Criterion
    kelly_fraction: float
    
    # Genel yorum
    verdict: str


def run_monte_carlo(
    trade_returns: list[float],
    initial_capital: float = 1000.0,
    n_simulations: int = 5000,
    n_trades: int = 100,
    ruin_threshold: float = 0.50,
    confidence_interval: float = 0.95,
) -> SimulationResult:
    """
    Monte Carlo simülasyonu çalıştır.
    
    Args:
        trade_returns: Geçmiş trade PnL yüzdeleri [-0.05, +0.08, ...]
        initial_capital: Başlangıç sermayesi
        n_simulations: Simülasyon sayısı
        n_trades: Her simülasyonda trade sayısı
        ruin_threshold: Ruin tanımı (sermayenin bu kadarını kaybetmek ruin)
        confidence_interval: Güven aralığı
    
    Returns:
        SimulationResult
    """
    if not trade_returns or len(trade_returns) < 5:
        return _empty_simulation()
    
    try:
        returns_arr = np.array(trade_returns)
        mean_ret = float(np.mean(returns_arr))
        std_ret = float(np.std(returns_arr))
        
        # Bootstrap simülasyonu
        rng = np.random.default_rng(42)
        
        # n_simulations × n_trades matrix (bootstrap örnekleme)
        if len(returns_arr) >= n_trades:
            sim_returns = rng.choice(returns_arr, size=(n_simulations, n_trades), replace=True)
        else:
            # Yeterli trade yoksa normal dağılımdan üret
            sim_returns = rng.normal(mean_ret, std_ret, size=(n_simulations, n_trades))
            sim_returns = np.clip(sim_returns, -0.20, 0.50)  # Gerçekçi sınırlar
        
        # Kümülatif PnL hesapla
        cumulative = initial_capital * np.cumprod(1 + sim_returns, axis=1)
        
        # Max drawdown her simülasyon için
        max_drawdowns = np.zeros(n_simulations)
        for i in range(n_simulations):
            equity = cumulative[i]
            peak = np.maximum.accumulate(equity)
            dd = (peak - equity) / peak
            max_drawdowns[i] = float(np.max(dd))
        
        # Final PnL
        final_values = cumulative[:, -1]
        final_pnl_pcts = (final_values - initial_capital) / initial_capital * 100
        
        # Ruin riski
        ruin_count = np.sum(final_values < initial_capital * (1 - ruin_threshold))
        ruin_risk = float(ruin_count / n_simulations * 100)
        
        # Percentiles
        median_max_dd = float(np.percentile(max_drawdowns, 50))
        p95_max_dd = float(np.percentile(max_drawdowns, 95))
        p99_max_dd = float(np.percentile(max_drawdowns, 99))
        
        median_final_pnl = float(np.percentile(final_pnl_pcts, 50))
        p5_final_pnl = float(np.percentile(final_pnl_pcts, 5))
        p95_final_pnl = float(np.percentile(final_pnl_pcts, 95))
        
        # CAGR (annualized, 20 trade/ay varsayım)
        trades_per_year = 20 * 12
        years = n_trades / trades_per_year
        median_equity_ratio = float(np.percentile(final_values, 50)) / initial_capital
        cagr = (median_equity_ratio ** (1 / max(years, 0.1)) - 1) * 100 if median_equity_ratio > 0 else 0
        
        # Kelly Criterion
        win_rate = float(np.mean([1 if r > 0 else 0 for r in returns_arr]))
        avg_win = float(np.mean([r for r in returns_arr if r > 0])) if any(r > 0 for r in returns_arr) else 0
        avg_loss = float(abs(np.mean([r for r in returns_arr if r < 0]))) if any(r < 0 for r in returns_arr) else 0.01
        
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1
        kelly = win_rate - (1 - win_rate) / win_loss_ratio
        kelly_fraction = max(0.0, min(kelly * 0.5, 0.25))  # Half-Kelly, max %25
        
        # Verdict
        if ruin_risk > 20:
            verdict = "⚠️ YÜKSEK RİSK — Strateji tehlikeli, pozisyon boyutunu küçült"
        elif ruin_risk > 10:
            verdict = "🟡 ORTA RİSK — Dikkatli devam et, risk yönetimi şart"
        elif median_final_pnl > 50 and p95_max_dd < 0.30:
            verdict = "✅ DÜŞÜK RİSK — Strateji sağlıklı görünüyor"
        else:
            verdict = "ℹ️ KABUL EDİLEBİLİR — İzlemeye devam et"
        
        logger.info(
            f"MC Simülasyon: {n_simulations}x{n_trades} trade | "
            f"MedianMDD={median_max_dd:.1%} | P95MDD={p95_max_dd:.1%} | "
            f"RuinRisk={ruin_risk:.1f}% | Kelly={kelly_fraction:.1%}"
        )
        
        return SimulationResult(
            n_simulations=n_simulations,
            n_trades_per_sim=n_trades,
            median_max_dd=round(median_max_dd, 4),
            p95_max_dd=round(p95_max_dd, 4),
            p99_max_dd=round(p99_max_dd, 4),
            median_final_pnl=round(median_final_pnl, 2),
            p5_final_pnl=round(p5_final_pnl, 2),
            p95_final_pnl=round(p95_final_pnl, 2),
            ruin_risk_pct=round(ruin_risk, 2),
            cagr_median=round(cagr, 2),
            kelly_fraction=round(kelly_fraction, 4),
            verdict=verdict,
        )
    
    except Exception as e:
        logger.error(f"Monte Carlo simülasyon hatası: {e}")
        return _empty_simulation()


def format_monte_carlo_report(result: SimulationResult) -> str:
    """Console/Telegram için MC raporu formatla."""
    lines = [
        "═══════════════════════════════════════",
        "      🎲 MONTE CARLO SİMÜLASYONU",
        f"  ({result.n_simulations:,} simülasyon × {result.n_trades_per_sim} trade)",
        "═══════════════════════════════════════",
        f"  Max Drawdown (Median):  {result.median_max_dd:.1%}",
        f"  Max Drawdown (P95):     {result.p95_max_dd:.1%}  ← planlama için",
        f"  Max Drawdown (P99):     {result.p99_max_dd:.1%}  ← worst case",
        "───────────────────────────────────────",
        f"  Final PnL (Median):  +{result.median_final_pnl:.1f}%",
        f"  Final PnL (P5):       {result.p5_final_pnl:+.1f}%  ← kötü senaryo",
        f"  Final PnL (P95):     +{result.p95_final_pnl:.1f}%  ← iyi senaryo",
        "───────────────────────────────────────",
        f"  💀 Ruin Riski:     {result.ruin_risk_pct:.1f}%",
        f"  📈 CAGR (median):  {result.cagr_median:+.1f}%",
        f"  🎯 Kelly Fraction: {result.kelly_fraction:.1%}",
        "───────────────────────────────────────",
        f"  {result.verdict}",
        "═══════════════════════════════════════",
    ]
    return "\n".join(lines)


def _empty_simulation() -> SimulationResult:
    return SimulationResult(
        n_simulations=0, n_trades_per_sim=0,
        median_max_dd=0, p95_max_dd=0, p99_max_dd=0,
        median_final_pnl=0, p5_final_pnl=0, p95_final_pnl=0,
        ruin_risk_pct=0, cagr_median=0, kelly_fraction=0.02,
        verdict="Yeterli veri yok",
    )
