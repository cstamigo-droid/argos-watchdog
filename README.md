# 🛡️ argos-watchdog

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE) [![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org) [![Reliability](https://img.shields.io/badge/reliability-monitor-orange.svg)]()

**Detecta cuando un sistema está "arriba" pero dejó de hacer su trabajo.**

Los monitores normales (UptimeRobot, Datadog, healthchecks.io, cron pings) responden a una sola
pregunta: *¿el proceso respondió?* Pero un proceso puede estar vivo, sin errores, y aun así
**haber dejado de cumplir su propósito en silencio**:

- un bot loguea "OK" pero lleva días sin abrir una sola operación,
- un pipeline guarda predicciones pero **nunca las califica** (se ve verde, está roto hace semanas),
- un dato "diario" lleva 3 días congelado pero el monitor con TTL de 2h dice "fresco hace 1h" (falso),
- una API de desarrollo apagada dispara un CRÍTICO falso cada noche.

`argos-watchdog` llena el hueco entre **"el job disparó"** y **"el job cumplió su propósito"**.
Es **config-driven** (describes los chequeos en un YAML, cero código por sistema) y **solo-lectura**
(observa, nunca toca lo que vigila).

---

## El caso de estudio (por qué existe)

Nació vigilando un ecosistema real de **trading algorítmico**: ~20 servicios (bots con dinero,
agentes de datos, daemons) corriendo solos 24/7. Una auditoría encontró **18 fallos silenciosos**
que llevaban semanas sin detectarse — todos del tipo "se ve verde, está roto". El más caro: un bot
que forzaba el lote mínimo del bróker y arriesgaba 17% en vez de 4%. Ningún monitor de uptime lo
habría visto, porque el proceso **estaba vivo**.

---

## Instalación

```bash
pip install argos-watchdog            # núcleo
pip install argos-watchdog[process]   # + chequeos de "proceso vivo" (psutil)
```

## Uso en 30 segundos

```bash
# 1. copia el ejemplo y edita las rutas
cp examples/quickstart.yaml mi-config.yaml      # Windows: copy examples\quickstart.yaml mi-config.yaml

# 2. una pasada
argos-watchdog mi-config.yaml

# 3. vigilancia continua + alerta Telegram en CRÍTICOS
argos-watchdog mi-config.yaml --watch 300 --notify
```

> Verificado end-to-end en Python 3.14 (Windows): el check `loop` distingue un pipeline roto
> (CRÍTICO, exit 2) de uno sano (OK), `idempotency` caza duplicados reales y los `guards`
> rechazan el sizing que excede el tope. Probado contra el código, no contra el papel.

Sale con código `2` si hay CRÍTICOS (para que un cron externo vigile **al propio watchdog** —
el monitor que vigila al monitor).

## Las 3 capas

No todos los errores se "aseguran" igual. argos-watchdog los ataca en tres niveles, y es honesto
sobre cuál garantía da cada uno:

1. **PREVENIR** (`argos_watchdog.guards`) — hace ciertos errores **imposibles por construcción**.
2. **DETECTAR** (checks, config YAML) — el resto no lo evitas, pero lo **ves en minutos**.
3. **PROBAR** (roadmap) — la única forma de saber que un freno sirve es **ejercitarlo**.

### Capa 1 — Guards (prevención)

```python
from argos_watchdog.guards import size_position, guard_schema

# el lote mínimo del bróker arriesga 17% > tope 4% -> SKIP, no fuerza la operación
d = size_position(real_capital=390, risk_pct=5, stop_distance_value=6700, min_lot=0.01)
assert not d.ok  # el error que cuesta dinero es ahora IMPOSIBLE

# la fuente externa cambió de esquema -> falla RUIDOSO en vez de corromper una señal
guard_schema(payload, {"epsActual": (float, True)}, source="yfinance")
```

### Capa 2 — Checks (detección, config-driven)

| Tipo | Pregunta que responde | ¿Quién más lo hace? |
|------|----------------------|---------------------|
| `file_fresh` | ¿El componente sigue escribiendo su salida? (TTL según su cadencia real) | parcial |
| `process` | ¿El proceso está vivo? | sí |
| `http` / `port` | ¿El endpoint responde? (`optional: true` = on-demand, apagado ≠ crítico) | sí |
| **`loop`** | **¿El lazo CIERRA? Produce registros... ¿y los resuelve?** | **nadie** |
| **`scheduled_task`** | **¿El cron existe, está habilitado y su último run fue OK?** (Windows) | **casi nadie** |
| **`idempotency`** | **¿La muestra está contaminada por duplicados que inflan métricas?** | **nadie** |
| **`discovery`** | **¿Hay procesos corriendo que NADIE declaró vigilar?** | **nadie** |

Los 4 marcados son la salsa secreta: detectan fallos que ningún monitor de uptime ve, porque el
proceso **está vivo** — solo dejó de cumplir su propósito.

```yaml
- name: "Pipeline de validación"
  type: loop
  produced: { path: "predicciones.jsonl" }
  resolved: { path: "predicciones.jsonl", field: "resolved_at" }
  max_lag: 50   # si producidas - resueltas > 50 => CRÍTICO: el lazo está roto
```

## Filosofía

1. **Solo-lectura por contrato.** Observa, nunca muta. La seguridad ES el producto.
2. **Lo no verificable es `UNKNOWN`, jamás `OK`.** No se finge cobertura.
3. **Config-driven.** Portable a cualquier proyecto sin escribir código.
4. **Anti-ruido.** Servicios on-demand y cadencias reales no generan falsos críticos.

## Estado

`v0.1` — núcleo open-source (MIT). 2 guards de prevención + 8 tipos de check de detección.

**Roadmap:** `schema_canary` (drift de fuentes externas, automatizado) · `killswitch_test` (capa 3:
prueba activa de que el freno REALMENTE corta) · **incident ledger** (registro que demuestra con
datos que cada patrón dejó de repetirse) · dashboard hosteado.

## Licencia

MIT (núcleo). Contribuciones bienvenidas.
