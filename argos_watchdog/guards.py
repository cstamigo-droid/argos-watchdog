"""
guards — capa de PREVENCIÓN. Hacen ciertos errores IMPOSIBLES por construcción, en el punto
exacto del fallo. A diferencia de los checks (que detectan), un guard se interpone: si la
operación violaría la regla, no se ejecuta.

Cubre los patrones donde se PUEDE asegurar (no solo detectar):
  - size_position : sizing sin tope -> tope duro; si el mínimo no cabe, SKIP (no fuerza).
  - guard_schema  : schema drift -> falla RUIDOSO si la fuente externa cambió de forma.
  - safe_field    : un campo ausente nunca se interpreta como señal (0/None != dirección).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

# ---------- sizing con tope duro (mata el lote-mínimo que infla el riesgo) ----------
MAX_RISK_PCT_HARD = 4.0   # tope absoluto; nadie lo sube sin tocar este archivo


@dataclass
class RiskDecision:
    action: str          # "TRADE" | "SKIP"
    lot: float
    risk_pct_real: float
    reason: str
    capital_used: float

    @property
    def ok(self) -> bool:
        return self.action == "TRADE"


def size_position(*, real_capital: float, risk_pct: float, stop_distance_value: float,
                  min_lot: float, lot_step: float = 0.01, max_lot: float | None = None,
                  max_risk_pct: float = MAX_RISK_PCT_HARD) -> RiskDecision:
    """
    Dimensiona contra el CAPITAL REAL (no el balance demo inflado), con tope duro.
    NUNCA lanza por riesgo alto: devuelve SKIP (fail-safe). Si ni el lote mínimo cabe en el
    tope -> SKIP (la trampa del lote-mínimo, resuelta de raíz). stop_distance_value = pérdida
    en moneda de cuenta por 1 lote si salta el SL.
    """
    if real_capital <= 0 or stop_distance_value <= 0 or min_lot <= 0:
        return RiskDecision("SKIP", 0.0, 0.0, "inputs inválidos (capital/stop/min_lot)", real_capital)
    cap = min(risk_pct, max_risk_pct)
    risk_money = real_capital * cap / 100.0
    raw_lot = risk_money / stop_distance_value
    lot = int(raw_lot / lot_step) * lot_step   # redondea HACIA ABAJO, nunca infla
    risk_at_min = (min_lot * stop_distance_value) / real_capital * 100.0
    if lot < min_lot:
        if risk_at_min > max_risk_pct:
            return RiskDecision("SKIP", 0.0, round(risk_at_min, 2),
                                f"lote mínimo {min_lot} arriesga {risk_at_min:.1f}% > tope "
                                f"{max_risk_pct}% (capital ${real_capital:.0f}) -> NO operar aquí",
                                real_capital)
        lot = min_lot
    if max_lot:
        lot = min(lot, max_lot)
    risk_real = (lot * stop_distance_value) / real_capital * 100.0
    if risk_real > max_risk_pct + 1e-9:
        return RiskDecision("SKIP", 0.0, round(risk_real, 2),
                            f"riesgo resultante {risk_real:.1f}% > tope {max_risk_pct}%", real_capital)
    return RiskDecision("TRADE", round(lot, 4), round(risk_real, 2),
                        f"OK: {lot} lots = {risk_real:.2f}% de ${real_capital:.0f}", real_capital)


# ---------- contrato de esquema en la frontera externa (mata el schema drift) ----------
class SchemaDriftError(Exception):
    """Se lanza RUIDOSAMENTE cuando la fuente externa cambió de forma."""


def guard_schema(payload: dict, schema: dict, source: str = "external") -> dict:
    """
    schema = {campo: (tipo, requerido_bool)}. Lanza SchemaDriftError si falta un requerido o
    el tipo no calza -> el drift se VE en vez de corromper una señal en silencio.
    """
    if not isinstance(payload, dict):
        raise SchemaDriftError(f"[{source}] payload no es dict: {type(payload).__name__}")
    for field, (typ, required) in schema.items():
        if field not in payload:
            if required:
                raise SchemaDriftError(
                    f"[{source}] FALTA campo requerido '{field}'. ¿La fuente cambió de esquema? "
                    f"Campos vistos: {sorted(payload)[:8]}")
            continue
        val = payload[field]
        if val is None:
            continue
        if not isinstance(val, typ):
            try:
                payload[field] = typ(val)
            except Exception:
                raise SchemaDriftError(
                    f"[{source}] campo '{field}' tipo {type(val).__name__}, esperado {typ.__name__}")
    return payload


def safe_field(payload: dict, field: str, default: Any = None, neutral: Any = 0):
    """Lectura defensiva: si el campo falta o es None -> NEUTRAL explícito, nunca señal direccional."""
    v = payload.get(field, default)
    return neutral if v is None else v
