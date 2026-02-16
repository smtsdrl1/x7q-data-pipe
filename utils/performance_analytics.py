"""
Performans Analiz Motoru
Uzun vadeli performans takibi, doğruluk analizi, saatlik/günlük/haftalık kırılımlar.
Her bildirim ve trade'in gerçek sonucunu ölçer ve raporlar.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from utils.logger import setup_logger

logger = setup_logger("PerformanceAnalytics")

ANALYTICS_FILE = "data/performance_analytics.json"


class PerformanceAnalytics:
    """
    Uzun vadeli performans analiz motoru:
    - Saatlik / günlük / haftalık kırılımlar
    - Sinyal doğruluk oranları
    - Fiyat doğrulama başarı oranları
    - Trade sonuç trendleri
    - Bildirim güvenilirlik metrikleri
    - Pair bazlı performans
    - Strateji bazlı analiz
    """

    def __init__(self, trade_journal, notification_manager, signal_tracker):
        self.journal = trade_journal
        self.notifications = notification_manager
        self.signals = signal_tracker

    def generate_full_report(self) -> dict:
        """Tam kapsamlı performans raporu."""
        journal_stats = self.journal.get_statistics()
        notif_stats = self.notifications.get_statistics()
        signal_stats = self.signals.get_statistics()

        return {
            "generated_at": datetime.now(timezone.utc).strftime(
                "%d.%m.%Y %H:%M:%S UTC"
            ),
            "summary": self._generate_summary(journal_stats, notif_stats, signal_stats),
            "signal_accuracy": self._analyze_signal_accuracy(),
            "pair_performance": self._analyze_pair_performance(),
            "hourly_breakdown": self._analyze_hourly_performance(),
            "daily_breakdown": self._analyze_daily_performance(),
            "weekly_breakdown": self._analyze_weekly_performance(),
            "price_verification": self._analyze_price_verification(),
            "notification_reliability": self._analyze_notification_reliability(),
            "strategy_effectiveness": self._analyze_strategy_effectiveness(),
            "risk_analysis": self._analyze_risk_metrics(),
            "execution_quality": self._analyze_execution_quality(),
        }

    def _generate_summary(self, journal_stats, notif_stats, signal_stats) -> dict:
        """Genel özet."""
        return {
            "total_signals_detected": signal_stats.get("total_signals", 0),
            "signals_executed": journal_stats.get("closed", 0) + journal_stats.get("active", 0),
            "signals_rejected": journal_stats.get("rejected", 0),
            "execution_rate": (
                (journal_stats.get("closed", 0) + journal_stats.get("active", 0))
                / max(signal_stats.get("total_signals", 1), 1) * 100
            ),
            "total_trades_closed": journal_stats.get("closed", 0),
            "win_rate": journal_stats.get("win_rate", 0),
            "profit_factor": journal_stats.get("profit_factor", 0),
            "total_pnl": journal_stats.get("total_pnl", 0),
            "total_fees": journal_stats.get("total_fees", 0),
            "avg_data_integrity": journal_stats.get("avg_data_integrity", 0),
            "notifications_sent": notif_stats.get("sent", 0),
            "notification_delivery_rate": notif_stats.get("delivery_rate", 0),
        }

    def _analyze_signal_accuracy(self) -> dict:
        """Sinyal doğruluk analizi."""
        closed_entries = [e for e in self.journal.entries if e.status == "CLOSED"]

        if not closed_entries:
            return {"message": "Henüz kapalı işlem yok"}

        # Skor aralıklarına göre doğruluk
        score_ranges = {
            "0.60-0.70": {"wins": 0, "losses": 0, "total": 0},
            "0.70-0.80": {"wins": 0, "losses": 0, "total": 0},
            "0.80-0.90": {"wins": 0, "losses": 0, "total": 0},
            "0.90-1.00": {"wins": 0, "losses": 0, "total": 0},
        }

        for e in closed_entries:
            score = e.composite_score
            if 0.60 <= score < 0.70:
                bucket = "0.60-0.70"
            elif 0.70 <= score < 0.80:
                bucket = "0.70-0.80"
            elif 0.80 <= score < 0.90:
                bucket = "0.80-0.90"
            else:
                bucket = "0.90-1.00"

            score_ranges[bucket]["total"] += 1
            if e.result == "WIN":
                score_ranges[bucket]["wins"] += 1
            else:
                score_ranges[bucket]["losses"] += 1

        for key, val in score_ranges.items():
            val["win_rate"] = (
                val["wins"] / val["total"] * 100
            ) if val["total"] > 0 else 0

        # RSI bazlı doğruluk
        rsi_ranges = {
            "oversold_20-30": {"wins": 0, "losses": 0, "total": 0},
            "neutral_30-50": {"wins": 0, "losses": 0, "total": 0},
            "mid_50-70": {"wins": 0, "losses": 0, "total": 0},
        }

        for e in closed_entries:
            rsi = e.rsi_at_entry
            if rsi <= 30:
                bucket = "oversold_20-30"
            elif rsi <= 50:
                bucket = "neutral_30-50"
            else:
                bucket = "mid_50-70"

            rsi_ranges[bucket]["total"] += 1
            if e.result == "WIN":
                rsi_ranges[bucket]["wins"] += 1
            else:
                rsi_ranges[bucket]["losses"] += 1

        for key, val in rsi_ranges.items():
            val["win_rate"] = (
                val["wins"] / val["total"] * 100
            ) if val["total"] > 0 else 0

        return {
            "by_composite_score": score_ranges,
            "by_rsi_range": rsi_ranges,
            "optimal_score_range": max(
                score_ranges.items(),
                key=lambda x: x[1]["win_rate"],
            )[0] if any(v["total"] > 0 for v in score_ranges.values()) else "N/A",
        }

    def _analyze_pair_performance(self) -> dict:
        """Pair bazlı performans analizi."""
        closed = [e for e in self.journal.entries if e.status == "CLOSED"]
        pair_stats = defaultdict(lambda: {
            "trades": 0, "wins": 0, "losses": 0,
            "total_pnl": 0.0, "avg_pnl_pct": 0.0,
            "best_pnl": 0.0, "worst_pnl": 0.0,
            "avg_duration_s": 0.0,
        })

        for e in closed:
            p = pair_stats[e.symbol]
            p["trades"] += 1
            p["total_pnl"] += e.net_pnl
            if e.result == "WIN":
                p["wins"] += 1
            else:
                p["losses"] += 1
            p["best_pnl"] = max(p["best_pnl"], e.net_pnl)
            p["worst_pnl"] = min(p["worst_pnl"], e.net_pnl)

        for symbol, p in pair_stats.items():
            p["win_rate"] = (p["wins"] / p["trades"] * 100) if p["trades"] > 0 else 0
            p["avg_pnl"] = p["total_pnl"] / p["trades"] if p["trades"] > 0 else 0

        # En iyi ve en kötü pair
        sorted_pairs = sorted(
            pair_stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True
        )
        best_pair = sorted_pairs[0] if sorted_pairs else None
        worst_pair = sorted_pairs[-1] if sorted_pairs else None

        return {
            "pairs": dict(pair_stats),
            "best_pair": {
                "symbol": best_pair[0],
                "pnl": best_pair[1]["total_pnl"],
                "win_rate": best_pair[1]["win_rate"],
            } if best_pair else None,
            "worst_pair": {
                "symbol": worst_pair[0],
                "pnl": worst_pair[1]["total_pnl"],
                "win_rate": worst_pair[1]["win_rate"],
            } if worst_pair else None,
            "total_pairs_traded": len(pair_stats),
        }

    def _analyze_hourly_performance(self) -> dict:
        """Saatlik performans kırılımı."""
        closed = [e for e in self.journal.entries if e.status == "CLOSED"]
        hourly = defaultdict(lambda: {
            "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0
        })

        for e in closed:
            try:
                hour = datetime.fromisoformat(e.trade_opened_at).hour
                h = hourly[hour]
                h["trades"] += 1
                h["pnl"] += e.net_pnl
                if e.result == "WIN":
                    h["wins"] += 1
                else:
                    h["losses"] += 1
            except Exception:
                continue

        for hour, h in hourly.items():
            h["win_rate"] = (h["wins"] / h["trades"] * 100) if h["trades"] > 0 else 0

        # En iyi saat
        sorted_hours = sorted(
            hourly.items(), key=lambda x: x[1]["pnl"], reverse=True
        )
        best_hour = sorted_hours[0] if sorted_hours else None

        return {
            "hours": dict(sorted(hourly.items())),
            "best_hour": {
                "hour": f"{best_hour[0]:02d}:00 UTC",
                "pnl": best_hour[1]["pnl"],
                "trades": best_hour[1]["trades"],
                "win_rate": best_hour[1]["win_rate"],
            } if best_hour else None,
            "most_active_hour": max(
                hourly.items(), key=lambda x: x[1]["trades"]
            )[0] if hourly else None,
        }

    def _analyze_daily_performance(self) -> dict:
        """Günlük performans kırılımı."""
        closed = [e for e in self.journal.entries if e.status == "CLOSED"]
        daily = defaultdict(lambda: {
            "trades": 0, "wins": 0, "losses": 0,
            "pnl": 0.0, "fees": 0.0,
        })

        for e in closed:
            try:
                day = datetime.fromisoformat(e.trade_closed_at).strftime("%Y-%m-%d")
                d = daily[day]
                d["trades"] += 1
                d["pnl"] += e.net_pnl
                d["fees"] += e.fee_total
                if e.result == "WIN":
                    d["wins"] += 1
                else:
                    d["losses"] += 1
            except Exception:
                continue

        for day, d in daily.items():
            d["win_rate"] = (d["wins"] / d["trades"] * 100) if d["trades"] > 0 else 0
            d["net_pnl"] = d["pnl"] - d["fees"]

        # Kazançlı / Zararlı günler
        profitable_days = sum(1 for d in daily.values() if d["pnl"] > 0)
        losing_days = sum(1 for d in daily.values() if d["pnl"] < 0)

        return {
            "days": dict(sorted(daily.items())),
            "total_days": len(daily),
            "profitable_days": profitable_days,
            "losing_days": losing_days,
            "best_day": max(
                daily.items(), key=lambda x: x[1]["pnl"]
            ) if daily else None,
            "worst_day": min(
                daily.items(), key=lambda x: x[1]["pnl"]
            ) if daily else None,
        }

    def _analyze_weekly_performance(self) -> dict:
        """Haftalık performans kırılımı."""
        closed = [e for e in self.journal.entries if e.status == "CLOSED"]
        weekly = defaultdict(lambda: {
            "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0,
        })

        for e in closed:
            try:
                dt = datetime.fromisoformat(e.trade_closed_at)
                week_key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
                w = weekly[week_key]
                w["trades"] += 1
                w["pnl"] += e.net_pnl
                if e.result == "WIN":
                    w["wins"] += 1
                else:
                    w["losses"] += 1
            except Exception:
                continue

        for week, w in weekly.items():
            w["win_rate"] = (w["wins"] / w["trades"] * 100) if w["trades"] > 0 else 0

        return {
            "weeks": dict(sorted(weekly.items())),
            "total_weeks": len(weekly),
        }

    def _analyze_price_verification(self) -> dict:
        """Fiyat doğrulama analizi."""
        all_entries = self.journal.entries

        total = len(all_entries)
        good_quality = [e for e in all_entries if e.signal_data_quality == "GOOD"]
        warning_quality = [e for e in all_entries if e.signal_data_quality == "WARNING"]
        fail_quality = [e for e in all_entries if e.signal_data_quality == "FAIL"]

        # Sapma analizi
        deviations = [
            e.signal_price_deviation_pct for e in all_entries
            if e.signal_price_deviation_pct != 0
        ]
        avg_deviation = (
            sum(abs(d) for d in deviations) / len(deviations)
        ) if deviations else 0
        max_deviation = max((abs(d) for d in deviations), default=0)

        # Slippage analizi
        slippages = [
            e.entry_slippage_pct for e in all_entries
            if e.entry_slippage_pct != 0
        ]
        avg_slippage = (
            sum(abs(s) for s in slippages) / len(slippages)
        ) if slippages else 0

        # Spread analizi (fiyat snapshot'larından)
        spreads = []
        for e in all_entries:
            for s in e.price_snapshots:
                sp = s.get("spread_pct", 0)
                if sp > 0:
                    spreads.append(sp)
        avg_spread = sum(spreads) / len(spreads) if spreads else 0

        return {
            "total_signals": total,
            "data_quality": {
                "good": len(good_quality),
                "warning": len(warning_quality),
                "fail": len(fail_quality),
                "good_pct": (len(good_quality) / total * 100) if total > 0 else 0,
            },
            "price_deviation": {
                "avg_pct": avg_deviation,
                "max_pct": max_deviation,
            },
            "slippage": {
                "avg_pct": avg_slippage,
                "total_entries_with_slippage": len(slippages),
            },
            "spread": {
                "avg_pct": avg_spread,
                "total_measurements": len(spreads),
            },
        }

    def _analyze_notification_reliability(self) -> dict:
        """Bildirim güvenilirlik analizi."""
        notif_stats = self.notifications.get_statistics()

        # Trade bildirimlerinin zamanlaması
        trade_notifs = [
            n for n in self.notifications.notifications
            if n.notification_type in ("TRADE_OPENED", "TRADE_CLOSED")
        ]

        latencies = [
            n.delivery_latency_ms for n in trade_notifs
            if n.delivery_latency_ms > 0
        ]
        avg_trade_latency = sum(latencies) / len(latencies) if latencies else 0

        # Fiyat doğrulama oranı (trade bildirimlerinde)
        price_verified_count = sum(1 for n in trade_notifs if n.price_verified)
        price_verify_rate = (
            price_verified_count / len(trade_notifs) * 100
        ) if trade_notifs else 0

        return {
            "total_notifications": notif_stats.get("total_notifications", 0),
            "delivery_rate": notif_stats.get("delivery_rate", 0),
            "trade_notifications": len(trade_notifs),
            "avg_trade_notification_latency_ms": avg_trade_latency,
            "price_verified_in_notifications": price_verify_rate,
            "failed_notifications": notif_stats.get("failed", 0),
            "latency_stats": notif_stats.get("latency", {}),
        }

    def _analyze_strategy_effectiveness(self) -> dict:
        """Strateji etkinlik analizi."""
        closed = [e for e in self.journal.entries if e.status == "CLOSED"]

        if not closed:
            return {"message": "Henüz kapalı işlem yok"}

        # Strateji bazlı sayım
        strategy_stats = defaultdict(lambda: {
            "appearances": 0, "wins": 0, "losses": 0,
        })

        for e in closed:
            for reason in e.signal_reasons:
                s = strategy_stats[reason]
                s["appearances"] += 1
                if e.result == "WIN":
                    s["wins"] += 1
                else:
                    s["losses"] += 1

        for key, s in strategy_stats.items():
            s["win_rate"] = (
                s["wins"] / s["appearances"] * 100
            ) if s["appearances"] > 0 else 0

        # En etkili strateji
        sorted_strategies = sorted(
            strategy_stats.items(),
            key=lambda x: x[1]["win_rate"],
            reverse=True,
        )

        return {
            "strategies": dict(strategy_stats),
            "most_effective": sorted_strategies[0][0] if sorted_strategies else "N/A",
            "least_effective": sorted_strategies[-1][0] if sorted_strategies else "N/A",
        }

    def _analyze_risk_metrics(self) -> dict:
        """Risk metrikleri analizi."""
        closed = [e for e in self.journal.entries if e.status == "CLOSED"]

        if not closed:
            return {"message": "Henüz kapalı işlem yok"}

        # Ardışık kazanç/kayıp serisi
        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for e in closed:
            if e.result == "WIN":
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        # Drawdown analizi
        cumulative_pnl = []
        running_pnl = 0
        peak_pnl = 0
        max_drawdown = 0

        for e in closed:
            running_pnl += e.net_pnl
            cumulative_pnl.append(running_pnl)
            if running_pnl > peak_pnl:
                peak_pnl = running_pnl
            dd = peak_pnl - running_pnl
            if dd > max_drawdown:
                max_drawdown = dd

        # Çıkış nedeni analizi
        exit_analysis = defaultdict(lambda: {"count": 0, "pnl": 0.0, "avg_pnl": 0.0})
        for e in closed:
            ea = exit_analysis[e.exit_reason]
            ea["count"] += 1
            ea["pnl"] += e.net_pnl

        for key, ea in exit_analysis.items():
            ea["avg_pnl"] = ea["pnl"] / ea["count"] if ea["count"] > 0 else 0

        return {
            "max_consecutive_wins": max_wins,
            "max_consecutive_losses": max_losses,
            "current_streak_wins": current_wins,
            "current_streak_losses": current_losses,
            "max_drawdown_usd": max_drawdown,
            "exit_analysis": dict(exit_analysis),
        }

    def _analyze_execution_quality(self) -> dict:
        """İşlem kalitesi analizi."""
        all_entries = self.journal.entries

        # Veri bütünlük skoru dağılımı
        integrity_scores = [
            e.data_integrity_score for e in all_entries
            if e.data_integrity_score > 0
        ]

        excellent = sum(1 for s in integrity_scores if s >= 90)
        good = sum(1 for s in integrity_scores if 70 <= s < 90)
        fair = sum(1 for s in integrity_scores if 50 <= s < 70)
        poor = sum(1 for s in integrity_scores if s < 50)

        # Fiyat snapshot sayıları
        total_snapshots = sum(len(e.price_snapshots) for e in all_entries)
        verified_snapshots = sum(
            sum(1 for s in e.price_snapshots if s.get("verified", False))
            for e in all_entries
        )

        return {
            "total_entries": len(all_entries),
            "avg_integrity_score": (
                sum(integrity_scores) / len(integrity_scores)
            ) if integrity_scores else 0,
            "integrity_distribution": {
                "excellent_90_100": excellent,
                "good_70_90": good,
                "fair_50_70": fair,
                "poor_0_50": poor,
            },
            "price_snapshots": {
                "total": total_snapshots,
                "verified": verified_snapshots,
                "verification_rate": (
                    verified_snapshots / total_snapshots * 100
                ) if total_snapshots > 0 else 0,
            },
        }

    def format_telegram_summary(self) -> str:
        """Telegram için formatlanmış özet rapor."""
        report = self.generate_full_report()
        summary = report["summary"]
        accuracy = report["signal_accuracy"]
        pairs = report["pair_performance"]
        notif = report["notification_reliability"]
        risk = report["risk_analysis"]
        quality = report["execution_quality"]

        text = (
            f"📊 <b>PERFORMANS ANALİZ RAPORU</b>\n"
            f"{'─' * 32}\n"
            f"📅 {report['generated_at']}\n\n"
            f"📈 <b>Genel Özet</b>\n"
            f"  Toplam Sinyal: {summary['total_signals_detected']}\n"
            f"  İşleme Alınan: {summary['signals_executed']}\n"
            f"  Reddedilen: {summary['signals_rejected']}\n"
            f"  İşleme Oranı: %{summary['execution_rate']:.1f}\n"
            f"  Kapatılan Trade: {summary['total_trades_closed']}\n"
            f"  Win Rate: %{summary['win_rate']:.1f}\n"
            f"  Profit Factor: {summary['profit_factor']:.2f}\n"
            f"  Net P&L: ${summary['total_pnl']:.2f}\n"
            f"  Toplam Fee: ${summary['total_fees']:.2f}\n\n"
        )

        # Pair performans
        if pairs.get("best_pair"):
            text += (
                f"🏆 <b>Pair Performans</b>\n"
                f"  Toplam Pair: {pairs['total_pairs_traded']}\n"
                f"  En İyi: {pairs['best_pair']['symbol']} "
                f"(${pairs['best_pair']['pnl']:.2f})\n"
            )
            if pairs.get("worst_pair"):
                text += (
                    f"  En Kötü: {pairs['worst_pair']['symbol']} "
                    f"(${pairs['worst_pair']['pnl']:.2f})\n"
                )
            text += "\n"

        # Risk
        if isinstance(risk, dict) and "max_consecutive_wins" in risk:
            text += (
                f"⚠️ <b>Risk Metrikleri</b>\n"
                f"  Max Seri Win: {risk['max_consecutive_wins']}\n"
                f"  Max Seri Loss: {risk['max_consecutive_losses']}\n"
                f"  Max Drawdown: ${risk['max_drawdown_usd']:.2f}\n\n"
            )

        # Bildirim güvenilirliği
        text += (
            f"📱 <b>Bildirim Güvenilirliği</b>\n"
            f"  Toplam Bildirim: {notif['total_notifications']}\n"
            f"  Teslimat Oranı: %{notif['delivery_rate']:.1f}\n"
            f"  Başarısız: {notif['failed_notifications']}\n"
            f"  Ort. Gecikme: {notif['avg_trade_notification_latency_ms']:.0f}ms\n"
            f"  Fiyat Doğrulama: %{notif['price_verified_in_notifications']:.1f}\n\n"
        )

        # Veri Kalitesi
        text += (
            f"🔍 <b>Veri Kalitesi</b>\n"
            f"  Ort. Bütünlük Skoru: {quality['avg_integrity_score']:.0f}/100\n"
            f"  Mükemmel (90+): {quality['integrity_distribution']['excellent_90_100']}\n"
            f"  İyi (70-90): {quality['integrity_distribution']['good_70_90']}\n"
            f"  Orta (50-70): {quality['integrity_distribution']['fair_50_70']}\n"
            f"  Zayıf (<50): {quality['integrity_distribution']['poor_0_50']}\n"
            f"  Fiyat Snapshot: {quality['price_snapshots']['total']} "
            f"(%{quality['price_snapshots']['verification_rate']:.1f} doğrulanmış)"
        )

        return text

    def format_telegram_pair_report(self) -> str:
        """Pair bazlı Telegram raporu."""
        pairs = self._analyze_pair_performance()
        if not pairs.get("pairs"):
            return "📊 Henüz pair performans verisi yok."

        text = (
            f"📊 <b>PAIR PERFORMANS RAPORU</b>\n"
            f"{'─' * 32}\n\n"
        )

        sorted_pairs = sorted(
            pairs["pairs"].items(),
            key=lambda x: x[1]["total_pnl"],
            reverse=True,
        )

        for symbol, p in sorted_pairs:
            emoji = "🟢" if p["total_pnl"] >= 0 else "🔴"
            text += (
                f"{emoji} <b>{symbol}</b>\n"
                f"  Trade: {p['trades']} | "
                f"Win: {p['wins']} | Loss: {p['losses']}\n"
                f"  Win Rate: %{p['win_rate']:.1f} | "
                f"P&L: ${p['total_pnl']:.2f}\n\n"
            )

        return text

    def format_telegram_hourly_report(self) -> str:
        """Saatlik Telegram raporu."""
        hourly = self._analyze_hourly_performance()
        if not hourly.get("hours"):
            return "📊 Henüz saatlik performans verisi yok."

        text = (
            f"🕐 <b>SAATLİK PERFORMANS RAPORU</b>\n"
            f"{'─' * 32}\n\n"
        )

        for hour in sorted(hourly["hours"].keys()):
            h = hourly["hours"][hour]
            emoji = "🟢" if h["pnl"] >= 0 else "🔴"
            bar = "█" * min(h["trades"], 10)
            text += (
                f"{emoji} {int(hour):02d}:00 UTC | "
                f"T:{h['trades']} W:{h['wins']} L:{h['losses']} | "
                f"${h['pnl']:.2f} | {bar}\n"
            )

        if hourly.get("best_hour"):
            text += (
                f"\n🏆 En İyi Saat: {hourly['best_hour']['hour']} "
                f"(${hourly['best_hour']['pnl']:.2f})"
            )

        return text

    def save_full_report(self):
        """Tam raporu dosyaya kaydet."""
        try:
            report = self.generate_full_report()
            os.makedirs(os.path.dirname(ANALYTICS_FILE), exist_ok=True)
            with open(ANALYTICS_FILE, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
            logger.info("Performans raporu kaydedildi")
        except Exception as e:
            logger.error(f"Performans raporu kaydetme hatası: {e}")
