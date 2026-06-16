"""
Motor: carga un YAML de config, corre todos los chequeos, clasifica y notifica.
Solo-lectura por contrato: observa, nunca muta el sistema vigilado.
"""
from __future__ import annotations
import json
import os
import urllib.request

from .checks import Result, Status, run_check


def load_config(path: str) -> dict:
    """Carga config YAML (o JSON como fallback si no hay pyyaml)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml
            return yaml.safe_load(text)
        except ImportError:
            raise SystemExit("Falta pyyaml para configs .yaml: pip install pyyaml "
                             "(o usa una config .json)")
    return json.loads(text)


def run_all(config: dict) -> list[Result]:
    return [run_check(c) for c in config.get("checks", [])]


def _env(config: dict, key: str) -> str:
    """Lee el nombre de la variable de entorno declarada en notify.* y devuelve su valor."""
    name = config.get("notify", {}).get(key, "")
    return os.environ.get(name, "") if name else ""


def notify_telegram(config: dict, text: str) -> bool:
    token = _env(config, "telegram_token_env")
    chat = _env(config, "telegram_chat_env")
    if not token or not chat:
        return False
    try:
        data = json.dumps({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def ping_healthcheck(config: dict) -> None:
    """Dead Man's Switch: pinga una URL externa. Si el watchdog muere, el servicio externo avisa."""
    url = _env(config, "healthcheck_url_env")
    if not url:
        return
    try:
        urllib.request.urlopen(url, timeout=5)
    except Exception:
        pass
