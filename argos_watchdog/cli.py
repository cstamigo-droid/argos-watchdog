"""
CLI: argos-watchdog <config.yaml> [--watch N] [--notify] [--json]

Exit code 0 si no hay CRÍTICOS; 2 si los hay (para un cron externo que vigile al watchdog).
"""
from __future__ import annotations
import argparse
import io
import json
import sys
import time

from .checks import Status
from .engine import load_config, notify_telegram, ping_healthcheck, run_all

# stdout UTF-8 (Windows CP1252 rompe con emojis/acentos)
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

C = {"OK": "\033[92m", "WARN": "\033[93m", "CRITICAL": "\033[91m", "UNKNOWN": "\033[90m", "X": "\033[0m"}
ORDER = [Status.CRITICAL, Status.UNKNOWN, Status.WARN, Status.OK]


def one_pass(config: dict, do_notify: bool, as_json: bool) -> int:
    results = run_all(config)
    ping_healthcheck(config)

    crit = [r for r in results if r.status == Status.CRITICAL]

    if as_json:
        print(json.dumps([r.__dict__ for r in results], default=str, ensure_ascii=False, indent=2))
    else:
        name = config.get("name", "watchdog")
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"\n{'='*64}\n  argos-watchdog · {name} · {ts}\n{'='*64}")
        order = {s: i for i, s in enumerate(ORDER)}
        for r in sorted(results, key=lambda x: (order.get(x.status, 9), -x.criticality)):
            c = C.get(r.status.value, "")
            print(f"  {c}{r.status.value:<9}{C['X']} [{r.type}] {r.name}: {r.detail}")
        n = {s: sum(1 for r in results if r.status == s) for s in Status}
        print(f"{'='*64}")
        print(f"  {n[Status.OK]} OK · {n[Status.WARN]} WARN · "
              f"{n[Status.CRITICAL]} CRÍTICOS · {n[Status.UNKNOWN]} UNKNOWN")

    if do_notify and crit:
        msg = f"🛡️ {config.get('name','watchdog')}: {len(crit)} CRÍTICO(s)\n" + \
              "\n".join(f"• [{r.type}] {r.name}: {r.detail}" for r in crit[:8])
        sent = notify_telegram(config, msg)
        if not as_json:
            print(f"  Telegram: {'enviado' if sent else 'NO (sin credenciales)'}")

    return 2 if crit else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="argos-watchdog",
                                 description="Vigía de fallos silenciosos, config-driven.")
    ap.add_argument("config", help="ruta al YAML/JSON de configuración")
    ap.add_argument("--watch", type=int, metavar="SEGS", help="loop cada SEGS segundos")
    ap.add_argument("--notify", action="store_true", help="alerta CRÍTICOS por Telegram")
    ap.add_argument("--json", action="store_true", help="salida JSON (para otras herramientas)")
    args = ap.parse_args(argv)

    config = load_config(args.config)
    if args.watch:
        try:
            while True:
                one_pass(config, args.notify, args.json)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0
    return one_pass(config, args.notify, args.json)


if __name__ == "__main__":
    sys.exit(main())
