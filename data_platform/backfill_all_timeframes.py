from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Binance API limits: klines can go back ~2-3 years max
# We'll try to get maximum historical data
MAX_HISTORICAL_DAYS = 1095  # 3 years (conservative, Binance may allow more)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill ALL timeframes with maximum historical data from Binance"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=MAX_HISTORICAL_DAYS,
        help=f"Days to backfill (default: {MAX_HISTORICAL_DAYS} = 3 years)",
    )
    parser.add_argument(
        "--intervals",
        nargs="+",
        default=["1h", "4h", "1d"],
        help="Time intervals to backfill (default: 1h 4h 1d)",
    )
    args = parser.parse_args()

    script_path = Path(__file__).parent / "backfill_historical.py"
    
    print("=" * 80)
    print("📊 BACKFILL COMPLETO - MÚLTIPLES TIMEFRAMES")
    print("=" * 80)
    print(f"Intervalos: {args.intervals}")
    print(f"Días históricos: {args.days} ({args.days/365.25:.2f} años)")
    print(f"Fuente: APIs REALES de Binance (no datos sintéticos)")
    print("=" * 80)
    print()

    total_rows = 0
    for interval in args.intervals:
        print(f"\n🔄 Backfilling {interval} interval...")
        print("-" * 80)
        
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--days",
                str(args.days),
                "--interval",
                interval,
            ],
            capture_output=True,
            text=True,
        )
        
        print(result.stdout)
        if result.stderr:
            print("WARNINGS:", result.stderr, file=sys.stderr)
        
        if result.returncode != 0:
            print(f"❌ Error en {interval}: {result.returncode}")
        else:
            # Extract row count from output
            for line in result.stdout.split("\n"):
                if "total rows=" in line:
                    try:
                        count = int(line.split("total rows=")[1].split(",")[0])
                        total_rows += count
                        print(f"✅ {interval}: {count:,} filas")
                    except:
                        pass
    
    print()
    print("=" * 80)
    print(f"✅ BACKFILL COMPLETO")
    print(f"   Total filas: {total_rows:,}")
    print(f"   Intervalos: {', '.join(args.intervals)}")
    print(f"   Período: {args.days} días ({args.days/365.25:.2f} años)")
    print("=" * 80)


if __name__ == "__main__":
    main()
