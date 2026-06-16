"""
Probes de bajo nivel: leen la REALIDAD (archivo, proceso, puerto, HTTP).
Degradan a None/False si no pueden verificar — jamás devuelven un OK inventado.
"""
from __future__ import annotations
import json
import os
import socket
import time
import urllib.request
from typing import Optional

try:
    import psutil
except Exception:
    psutil = None


def file_age(path: str) -> Optional[float]:
    """Edad en segundos del archivo. None si no existe (=> UNKNOWN, no OK)."""
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return None


def process_alive(needle: str) -> Optional[bool]:
    """True/False si hay un proceso con `needle` en su cmdline. None si no hay psutil."""
    if not psutil:
        return None
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cl = p.info.get("cmdline")
            if cl and any(needle in str(c) for c in cl):
                return True
        except Exception:
            continue
    return False


def port_listening(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def jsonl_duplicates(path: str, key_fields: list[str]) -> Optional[list[str]]:
    """Claves duplicadas en un JSONL append-only (patrón idempotencia). None si no existe."""
    if not os.path.exists(path):
        return None
    seen, dupes = set(), []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                k = "|".join(str(d.get(kf, "")) for kf in key_fields)
                if k in seen:
                    dupes.append(k)
                else:
                    seen.add(k)
    except OSError:
        return None
    return dupes


def python_processes() -> Optional[list[str]]:
    """cmdlines de procesos Python vivos (para 'discovery': qué corre sin estar declarado). None sin psutil."""
    if not psutil:
        return None
    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            nm = (p.info.get("name") or "").lower()
            if "python" not in nm:
                continue
            cl = p.info.get("cmdline") or []
            joined = " ".join(str(c) for c in cl)
            if joined:
                out.append(joined)
        except Exception:
            continue
    return out


def scheduled_task(name: str) -> Optional[dict]:
    """
    Estado de una tarea programada de Windows (Task Scheduler), sin depender del idioma
    del sistema. Devuelve {exists, state, last_result} o None si no se puede consultar.
    Caza el patrón 'validación fantasma' (un cron DESHABILITADO o que falla en silencio).
    """
    import subprocess
    try:
        ps = (f"$ErrorActionPreference='Stop'; "
              f"$t=Get-ScheduledTask -TaskName '{name}'; "
              f"$i=Get-ScheduledTaskInfo -TaskName '{name}'; "
              f"Write-Output ($t.State.ToString()+'|'+$i.LastTaskResult)")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    if out.returncode != 0 or "|" not in (out.stdout or ""):
        return {"exists": False}
    state, last = out.stdout.strip().split("|", 1)
    try:
        last_result = int(last)
    except ValueError:
        last_result = None
    return {"exists": True, "state": state, "last_result": last_result}


def count_jsonl(path: str, field: Optional[str] = None) -> Optional[int]:
    """
    Cuenta líneas de un JSONL. Si `field` se da, cuenta solo las que tienen ese campo
    NO nulo (= "resueltas"). None si el archivo no existe.
    Núcleo del chequeo de fallo silencioso 'loop' (produce-y-resuelve).
    """
    if not os.path.exists(path):
        return None
    n = 0
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if field is None:
                    n += 1
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get(field) is not None:
                    n += 1
    except OSError:
        return None
    return n
