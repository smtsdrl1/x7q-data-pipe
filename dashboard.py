"""
Terminal Dashboard
Canli performans takibi icin terminal tabanli goruntuleyici.
"""

import asyncio
import os
import sys
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.text import Text

from main import TradingEngine
from utils.helpers import format_currency, format_pct
from config import INITIAL_CAPITAL

console = Console()


def create_header(engine: TradingEngine) -> Panel:
    """Baslik paneli olustur."""
    status = engine.get_status()
    is_running = status["is_running"]

    title = Text()
    title.append("CRYPTO TRADING BOT", style="bold cyan")
    title.append(" | ", style="dim")
    title.append("AKTIF" if is_running else "DURDURULDU",
                 style="bold green" if is_running else "bold red")
    title.append(f" | Tarama #{status['scan_count']}", style="dim")
    title.append(f" | Uptime: {status['uptime']}", style="dim")

    return Panel(title, style="cyan")


def create_performance_table(engine: TradingEngine) -> Table:
    """Performans tablosu olustur."""
    stats = engine.get_status()["stats"]

    table = Table(title="Performans", show_header=True, header_style="bold magenta")
    table.add_column("Metrik", style="cyan", width=20)
    table.add_column("Deger", style="white", width=20)

    roi = stats["roi"]
    roi_style = "green" if roi > 0 else "red"

    table.add_row("Baslangic", format_currency(stats["initial_capital"]))
    table.add_row("Mevcut Sermaye", format_currency(stats["current_capital"]))
    table.add_row("Net P&L", format_currency(stats["net_pnl"]))
    table.add_row("ROI", Text(format_pct(roi), style=roi_style))
    table.add_row("Toplam Fee", format_currency(stats["total_fees"]))
    table.add_row("Max Drawdown", f"{stats['max_drawdown']:.2f}%")

    return table


def create_trade_stats_table(engine: TradingEngine) -> Table:
    """Trade istatistikleri tablosu."""
    stats = engine.get_status()["stats"]

    table = Table(title="Trade Istatistikleri", show_header=True, header_style="bold yellow")
    table.add_column("Metrik", style="cyan", width=20)
    table.add_column("Deger", style="white", width=20)

    table.add_row("Toplam Trade", str(stats["total_trades"]))
    table.add_row("Kazanan", str(stats["winning_trades"]))
    table.add_row("Kaybeden", str(stats["losing_trades"]))
    table.add_row("Win Rate", f"{stats['win_rate']:.1f}%")
    table.add_row("Avg Win", format_pct(stats["avg_win"]))
    table.add_row("Avg Loss", format_pct(stats["avg_loss"]))
    table.add_row("Bugun Trade", str(stats["daily_trades"]))
    table.add_row("Bugun P&L", format_currency(stats["daily_pnl"]))
    table.add_row("Ardisik Kayip", str(stats["consecutive_losses"]))

    return table


def create_positions_table(engine: TradingEngine) -> Table:
    """Acik pozisyonlar tablosu."""
    positions = engine.get_status()["open_positions"]

    table = Table(title="Acik Pozisyonlar", show_header=True, header_style="bold green")
    table.add_column("Symbol", style="cyan", width=12)
    table.add_column("Yon", width=6)
    table.add_column("Giris", width=14)
    table.add_column("Stop-Loss", width=14)
    table.add_column("Take-Profit", width=14)
    table.add_column("Trail Stop", width=14)

    if not positions:
        table.add_row("--", "--", "--", "--", "--", "--")
    else:
        for pos in positions:
            table.add_row(
                pos["symbol"],
                Text(pos["side"].upper(), style="green" if pos["side"] == "buy" else "red"),
                format_currency(pos["entry_price"]),
                format_currency(pos["stop_loss"]),
                format_currency(pos["take_profit"]),
                format_currency(pos["trailing_stop"]),
            )

    return table


def create_recent_trades_table(engine: TradingEngine) -> Table:
    """Son trade'ler tablosu."""
    closed = [t for t in engine.risk_manager.trade_history if t.status == "closed"][-5:]

    table = Table(title="Son Trade'ler", show_header=True, header_style="bold blue")
    table.add_column("Symbol", width=12)
    table.add_column("P&L", width=14)
    table.add_column("P&L%", width=10)
    table.add_column("Sebep", width=14)

    if not closed:
        table.add_row("--", "--", "--", "--")
    else:
        for t in reversed(closed):
            pnl_style = "green" if t.pnl > 0 else "red"
            table.add_row(
                t.symbol,
                Text(format_currency(t.pnl), style=pnl_style),
                Text(format_pct(t.pnl_pct), style=pnl_style),
                t.status,
            )

    return table


async def run_dashboard():
    """Dashboard'u calistir."""
    engine = TradingEngine()

    # Engine'i arka planda baslat
    engine_task = asyncio.create_task(engine.start())

    console.clear()
    console.print("[bold cyan]Dashboard baslatiliyor...[/bold cyan]")

    try:
        while True:
            console.clear()
            console.print(create_header(engine))
            console.print()

            # Tablolari yan yana goster
            perf = create_performance_table(engine)
            trade_stats = create_trade_stats_table(engine)
            console.print(perf)
            console.print()
            console.print(trade_stats)
            console.print()
            console.print(create_positions_table(engine))
            console.print()
            console.print(create_recent_trades_table(engine))
            console.print()
            console.print("[dim]Ctrl+C ile cikis | Her 5 saniyede yenilenir[/dim]")

            await asyncio.sleep(5)
    except (KeyboardInterrupt, asyncio.CancelledError):
        engine.is_running = False
        console.print("[bold red]Dashboard kapatiliyor...[/bold red]")


if __name__ == "__main__":
    asyncio.run(run_dashboard())
