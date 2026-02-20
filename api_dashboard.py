"""
FastAPI Canlı REST API Dashboard
Paper trading motorunun durumunu HTTP API olarak sunar.

Başlatma:
    uvicorn api_dashboard:app --host 0.0.0.0 --port 8080 --reload

Endpointler:
    GET /           — HTML ana sayfa
    GET /health     — Bot sağlık durumu
    GET /positions  — Açık pozisyonlar
    GET /signals    — Son sinyaller
    GET /stats      — Performans istatistikleri
    GET /circuit    — Circuit breaker durumu
    GET /session    — Güncel session bilgisi
    GET /regime/{symbol} — Market regime
    GET /mc         — Monte Carlo risk simülasyonu
    POST /stop      — Circuit breaker tetikle
    POST /resume    — Circuit breaker sıfırla
"""

from datetime import datetime

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    print("FastAPI bulunamadı. Kurmak için: pip install fastapi uvicorn")

from utils.logger import setup_logger
from config import INITIAL_CAPITAL, TRADING_PAIRS

logger = setup_logger("APIDashboard")

_engine_ref = None
_start_time = datetime.now()


def set_engine(engine):
    """Paper trading engine'i dashboard'a bağla."""
    global _engine_ref
    _engine_ref = engine


if FASTAPI_AVAILABLE:
    app = FastAPI(
        title="Crypto Trading Bot API",
        description="Paper trading motorunun gerçek zamanlı REST API paneli",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── HTML Ana Sayfa ───────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return HTMLResponse(content="""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/>
<meta http-equiv="refresh" content="15"/>
<title>Crypto Bot API</title>
<style>
body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:24px}
h1{color:#58a6ff} a{color:#58a6ff;margin-right:14px;text-decoration:none}
.card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;margin:12px 0}
pre{background:#21262d;padding:12px;border-radius:4px;overflow:auto}
</style></head><body>
<h1>🤖 Crypto Bot — REST API</h1>
<div class="card">
  <a href="/health">Health</a>
  <a href="/positions">Positions</a>
  <a href="/stats">Stats</a>
  <a href="/signals">Signals</a>
  <a href="/circuit">Circuit</a>
  <a href="/session">Session</a>
  <a href="/mc">Monte Carlo</a>
  <a href="/docs">📖 API Docs</a>
</div>
<div class="card">
  <p>Her 15 saniyede otomatik yenileme aktif.</p>
  <p>Tüm endpoint'ler JSON döner. 
  <a href="/docs">Swagger UI</a> üzerinden interaktif test edebilirsiniz.</p>
</div>
<script>
fetch('/stats').then(r=>r.json()).then(d=>{
  document.body.innerHTML += '<div class="card"><h2>Anlık Özet</h2><pre>'
    + JSON.stringify(d, null, 2) + '</pre></div>';
});
</script>
</body></html>""")

    # ─── Health ──────────────────────────────────────────────────────────────

    @app.get("/health", tags=["Sistem"])
    async def health():
        uptime = int((datetime.now() - _start_time).total_seconds())
        h, r = divmod(uptime, 3600); m, s = divmod(r, 60)
        return {
            "status": "ok" if getattr(_engine_ref, "is_running", False) else "idle",
            "engine_running": getattr(_engine_ref, "is_running", False),
            "uptime": f"{h:02d}:{m:02d}:{s:02d}",
            "pairs": TRADING_PAIRS,
            "timestamp": datetime.now().isoformat(),
        }

    # ─── Pozisyonlar ─────────────────────────────────────────────────────────

    @app.get("/positions", tags=["Trading"])
    async def positions():
        if not _engine_ref:
            return {"positions": [], "count": 0}
        pm = getattr(_engine_ref, "position_manager", None)
        if not pm:
            return {"positions": [], "count": 0}
        result = []
        for sym, pos in pm.open_positions.items():
            age = int((datetime.now() - pos.entry_time).total_seconds())
            result.append({
                "symbol": sym, "side": pos.side,
                "entry_price": pos.entry_price, "quantity": pos.quantity,
                "stop_loss": pos.stop_loss, "take_profit": pos.take_profit,
                "tp1_triggered": getattr(pos, "tp1_triggered", False),
                "scale_ins": getattr(pos, "scale_ins", 0),
                "age_secs": age,
            })
        return {"positions": result, "count": len(result)}

    # ─── Sinyaller ───────────────────────────────────────────────────────────

    @app.get("/signals", tags=["Trading"])
    async def signals(limit: int = 20):
        if not _engine_ref:
            return {"signals": [], "count": 0}
        tracker = getattr(_engine_ref, "signal_tracker", None)
        if not tracker:
            return {"signals": [], "note": "signal_tracker yok"}
        history = getattr(tracker, "signal_history", [])[-limit:]
        return {
            "signals": [
                {"symbol": s.get("symbol"), "signal": str(s.get("signal", "")),
                 "score": s.get("composite_score"), "timestamp": s.get("timestamp", "")}
                for s in history
            ],
            "count": len(history),
        }

    # ─── İstatistikler ───────────────────────────────────────────────────────

    @app.get("/stats", tags=["Performans"])
    async def stats():
        if not _engine_ref:
            return {"note": "engine bağlı değil"}
        risk = getattr(_engine_ref, "risk_manager", None)
        if not risk:
            return {"error": "risk_manager yok"}
        s = risk.get_stats()
        pm = getattr(_engine_ref, "position_manager", None)
        open_count = len(getattr(pm, "open_positions", {}))
        return {**s, "open_positions": open_count,
                "timestamp": datetime.now().isoformat()}

    # ─── Circuit Breaker ─────────────────────────────────────────────────────

    @app.get("/circuit", tags=["Risk"])
    async def circuit():
        try:
            from utils.circuit_breaker import circuit_breaker
            ok, reason = circuit_breaker.check()
            return {
                "can_trade": ok, "reason": reason,
                "consecutive_losses": circuit_breaker.consecutive_losses,
                "hourly_pnl_pct": circuit_breaker.hourly_pnl_pct,
                "daily_pnl_pct": circuit_breaker.daily_pnl_pct,
                "manual_stopped": circuit_breaker.manual_stopped,
                "news_kill_active": circuit_breaker.news_kill_active,
            }
        except ImportError:
            raise HTTPException(status_code=500, detail="circuit_breaker modülü yok")

    @app.post("/stop", tags=["Risk"])
    async def stop_trading():
        try:
            from utils.circuit_breaker import circuit_breaker
            circuit_breaker.manual_stop()
            return {"status": "stopped"}
        except ImportError:
            raise HTTPException(status_code=500, detail="circuit_breaker modülü yok")

    @app.post("/resume", tags=["Risk"])
    async def resume_trading():
        try:
            from utils.circuit_breaker import circuit_breaker
            circuit_breaker.manual_resume()
            return {"status": "resumed"}
        except ImportError:
            raise HTTPException(status_code=500, detail="circuit_breaker modülü yok")

    # ─── Session ─────────────────────────────────────────────────────────────

    @app.get("/session", tags=["Analiz"])
    async def session():
        try:
            from utils.session_killzone import get_current_session, is_tradeable_session
            sess = get_current_session()
            tradeable, _ = is_tradeable_session()
            return {
                "session": sess.get("session"),
                "quality": sess.get("quality"),
                "description": sess.get("description", ""),
                "tradeable": tradeable,
                "utc_time": datetime.utcnow().strftime("%H:%M UTC"),
            }
        except ImportError:
            raise HTTPException(status_code=500, detail="session_killzone modülü yok")

    # ─── Market Regime ───────────────────────────────────────────────────────

    @app.get("/regime/{symbol}", tags=["Analiz"])
    async def regime(symbol: str):
        try:
            from utils.market_regime import market_regime_detector
            cache = getattr(market_regime_detector, "cache", {})
            sym = symbol.upper()
            if sym in cache:
                return cache[sym]
            return {"regime": "UNKNOWN", "note": f"{sym} için cache yok"}
        except ImportError:
            raise HTTPException(status_code=500, detail="market_regime modülü yok")

    # ─── Monte Carlo ─────────────────────────────────────────────────────────

    @app.get("/mc", tags=["Risk"])
    async def monte_carlo(n_simulations: int = 2000):
        if not _engine_ref:
            raise HTTPException(status_code=503, detail="Engine bağlı değil")
        risk = getattr(_engine_ref, "risk_manager", None)
        if not risk:
            raise HTTPException(status_code=503, detail="risk_manager yok")
        closed = [t for t in risk.trade_history if t.status == "closed"]
        if len(closed) < 20:
            raise HTTPException(
                status_code=400,
                detail=f"Yeterli trade yok (gerekli≥20, mevcut={len(closed)})"
            )
        try:
            from utils.monte_carlo import run_monte_carlo
            returns = [t.pnl_pct / 100 for t in closed]
            r = run_monte_carlo(returns, risk.current_capital, n_simulations, 50)
            return {
                "median_max_drawdown": r.median_max_dd,
                "p95_max_drawdown": r.p95_max_dd,
                "p99_max_drawdown": r.p99_max_dd,
                "ruin_risk_pct": r.ruin_risk_pct,
                "kelly_fraction": r.kelly_fraction,
                "cagr_median": r.cagr_median,
                "verdict": r.verdict,
                "n_simulations": n_simulations,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


def run(host: str = "0.0.0.0", port: int = 8080):
    """API sunucusunu başlat."""
    if not FASTAPI_AVAILABLE:
        logger.error("pip install fastapi uvicorn")
        return
    import uvicorn
    logger.info(f"API Dashboard → http://{host}:{port}")
    uvicorn.run("api_dashboard:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run()
