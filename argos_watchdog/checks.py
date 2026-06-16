"""
Tipos de chequeo, pluggables y config-driven. Cada uno recibe el dict del check
(del YAML) y devuelve un Result. Agregar un tipo nuevo = una función + una entrada en CHECKS.

Los tipos commodity (file_fresh/process/http/port) los hace cualquier monitor.
El diferenciador de argos-watchdog son los de FALLO SILENCIOSO: 'loop' (produce-y-resuelve).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

from . import probes


class Status(str, Enum):
    OK = "OK"
    WARN = "WARN"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


@dataclass
class Result:
    name: str
    status: Status
    detail: str
    type: str = ""
    criticality: int = 3
    evidence: dict = field(default_factory=dict)


def _crit(c: dict) -> int:
    return int(c.get("criticality", 3))


# ---- commodity: ¿está vivo / responde? ----
def check_file_fresh(c: dict) -> Result:
    """El componente DEBE escribir un archivo de salida. Frío = FALLO SILENCIOSO."""
    age = probes.file_age(c["path"])
    if age is None:
        return Result(c["name"], Status.UNKNOWN, f"archivo ausente: {c['path']}",
                      "file_fresh", _crit(c))
    max_age = int(c.get("max_age", 300))
    if age <= max_age:
        return Result(c["name"], Status.OK, f"fresco (hace {int(age)}s)", "file_fresh", _crit(c),
                      {"age_s": int(age)})
    return Result(c["name"], Status.CRITICAL,
                  f"output FRÍO hace {int(age)}s (máx {max_age}s) — vivo pero no trabaja",
                  "file_fresh", _crit(c), {"age_s": int(age), "max_age": max_age})


def check_process(c: dict) -> Result:
    alive = probes.process_alive(c["needle"])
    if alive is None:
        return Result(c["name"], Status.UNKNOWN, "no verificable (instala psutil)", "process", _crit(c))
    return (Result(c["name"], Status.OK, "proceso vivo", "process", _crit(c))
            if alive else
            Result(c["name"], Status.CRITICAL, "PROCESO MUERTO", "process", _crit(c)))


def _check_endpoint(c: dict, ok: bool, target: str) -> Result:
    if ok:
        return Result(c["name"], Status.OK, "responde", c["type"], _crit(c), {"target": target})
    # on-demand: caído no es fallo (no se espera 24/7) -> UNKNOWN, evita falsos críticos
    if c.get("optional"):
        return Result(c["name"], Status.UNKNOWN, f"apagado (on-demand): {target}", c["type"], _crit(c))
    return Result(c["name"], Status.CRITICAL, f"NO RESPONDE: {target}", c["type"], _crit(c))


def check_http(c: dict) -> Result:
    return _check_endpoint(c, probes.http_ok(c["url"]), c["url"])


def check_port(c: dict) -> Result:
    return _check_endpoint(c, probes.port_listening(int(c["port"])), f"port {c['port']}")


# ---- EL DIFERENCIADOR: fallo silencioso de pipeline ----
def check_loop(c: dict) -> Result:
    """
    'produce-y-resuelve': el bug estrella. Un pipeline que PRODUCE registros pero nunca los
    RESUELVE/califica (ej: loguea predicciones y jamás las puntúa) se ve 'verde' mientras está roto.
    Config:
      produced: {path, field?}   # total producido (field opcional => cuenta con campo presente)
      resolved: {path, field}    # resuelto (cuenta líneas con `field` no nulo)
      max_lag:  N                # si producidos - resueltos > N => roto
    """
    p, r = c["produced"], c["resolved"]
    n_prod = probes.count_jsonl(p["path"], p.get("field"))
    n_res = probes.count_jsonl(r["path"], r["field"])
    if n_prod is None or n_res is None:
        return Result(c["name"], Status.UNKNOWN,
                      f"no verificable (falta {p['path']} o {r['path']})", "loop", _crit(c))
    lag = n_prod - n_res
    max_lag = int(c.get("max_lag", 0))
    if lag > max_lag:
        return Result(c["name"], Status.CRITICAL,
                      f"PRODUCE pero NO RESUELVE: {n_prod} producidos, {n_res} resueltos "
                      f"(lag {lag} > {max_lag}) — el lazo está roto y se ve verde",
                      "loop", _crit(c), {"produced": n_prod, "resolved": n_res, "lag": lag})
    return Result(c["name"], Status.OK, f"lazo cierra ({n_res}/{n_prod} resueltos)", "loop", _crit(c),
                  {"produced": n_prod, "resolved": n_res})


# Códigos de "no es fallo" del Task Scheduler: 0 OK · 267009 corriendo · 267011 aún no corrió.
_TASK_OK = {0, 267009, 267011}

def check_scheduled_task(c: dict) -> Result:
    """
    'validación fantasma' / infra: ¿la tarea existe, está HABILITADA y su último run fue OK?
    Caza el cron deshabilitado o el resolver sin tarea que se ve verde pero nunca corre. (Windows)
    """
    info = probes.scheduled_task(c["task"])
    if info is None:
        return Result(c["name"], Status.UNKNOWN, "no verificable (¿no es Windows?)", "scheduled_task", _crit(c))
    if not info.get("exists"):
        return Result(c["name"], Status.CRITICAL, f"tarea AUSENTE: '{c['task']}' no existe",
                      "scheduled_task", _crit(c))
    if info.get("state") == "Disabled":
        return Result(c["name"], Status.CRITICAL, f"tarea DESHABILITADA: '{c['task']}' no se ejecutará",
                      "scheduled_task", _crit(c), info)
    lr = info.get("last_result")
    if lr is not None and lr not in _TASK_OK:
        return Result(c["name"], Status.WARN,
                      f"última ejecución falló (código {lr})", "scheduled_task", _crit(c), info)
    return Result(c["name"], Status.OK, f"habilitada, último run OK ({info.get('state')})",
                  "scheduled_task", _crit(c), info)


def check_idempotency(c: dict) -> Result:
    """
    ¿La muestra está contaminada por duplicados? Append sin idempotencia infla métricas
    (accuracy/EV calculados sobre datos repetidos). Config: path + keys (campos que forman la clave).
    """
    dupes = probes.jsonl_duplicates(c["path"], c["keys"])
    if dupes is None:
        return Result(c["name"], Status.UNKNOWN, f"archivo ausente: {c['path']}", "idempotency", _crit(c))
    if dupes:
        return Result(c["name"], Status.WARN,
                      f"{len(dupes)} duplicado(s) por {c['keys']} — la muestra infla métricas",
                      "idempotency", _crit(c), {"dupes": dupes[:5]})
    return Result(c["name"], Status.OK, "sin duplicados (muestra limpia)", "idempotency", _crit(c))


def check_discovery(c: dict) -> Result:
    """
    ¿Hay procesos Python corriendo que NO están declarados? = 'sistema no vigilado' (corre
    sin que nadie sepa si trabaja). Config: expected = lista de needles que SÍ esperas ver.
    """
    procs = probes.python_processes()
    if procs is None:
        return Result(c["name"], Status.UNKNOWN, "no verificable (instala psutil)", "discovery", _crit(c))
    expected = c.get("expected", [])
    ignore = c.get("ignore", []) + ["argos_watchdog"]  # no se cuenta a sí mismo
    undeclared = []
    for cmd in procs:
        if any(ig in cmd for ig in ignore):
            continue
        if not any(exp in cmd for exp in expected):
            # recorta a un nombre de script legible
            tail = next((tok for tok in cmd.split() if tok.endswith(".py")), cmd[:60])
            undeclared.append(tail)
    if undeclared:
        uniq = sorted(set(undeclared))
        return Result(c["name"], Status.WARN,
                      f"{len(uniq)} proceso(s) Python NO declarado(s): {uniq[:6]}",
                      "discovery", _crit(c), {"undeclared": uniq})
    return Result(c["name"], Status.OK, "todo proceso Python está declarado", "discovery", _crit(c))


CHECKS = {
    "file_fresh": check_file_fresh,
    "process": check_process,
    "http": check_http,
    "port": check_port,
    "loop": check_loop,
    "scheduled_task": check_scheduled_task,
    "idempotency": check_idempotency,
    "discovery": check_discovery,
}


def run_check(c: dict) -> Result:
    fn = CHECKS.get(c.get("type"))
    if not fn:
        return Result(c.get("name", "?"), Status.UNKNOWN,
                      f"tipo de chequeo desconocido: {c.get('type')}", c.get("type", "?"))
    try:
        return fn(c)
    except KeyError as e:
        return Result(c.get("name", "?"), Status.UNKNOWN,
                      f"config incompleta, falta {e}", c.get("type", "?"))
