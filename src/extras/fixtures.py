import os
import threading
from datetime import datetime, timedelta

from extras.eleicao import (
    apply_mat_def_majoritario,
    format_duration,
    infer_mat_def_majoritario,
)
from extras.tse_client import CARGOS_MAJORITARIOS, panel_title, resolve_panel

MOCK_ENABLED = os.environ.get("TSELIVESCORE_MOCK", "").lower() in ("1", "true", "yes")

_lock = threading.Lock()
_state: dict[str, dict] = {}


def reset_mock_state() -> None:
    with _lock:
        _state.clear()

_ELEITORADO = 120_000_000
_VV_BASE = 100_000_000


def _scenario(panel_key: str) -> dict:
    _, uf, cargo = resolve_panel(panel_key)
    if cargo == "1":
        return {
            "qtd_vagas": 1,
            "candidates": [
                {"nome": "Candidato A", "share": 0.46, "drift": 0.0015, "sf_e": "n"},
                {"nome": "Candidato B", "share": 0.41, "drift": -0.001, "sf_e": "n"},
                {"nome": "Candidato C", "share": 0.08, "drift": 0.0, "sf_e": "n"},
                {"nome": "Candidato D", "share": 0.05, "drift": 0.0, "sf_e": "n"},
            ],
        }
    if cargo in ("6", "7", "8"):
        return {
            "qtd_vagas": 8,
            "candidates": [
                {"nome": f"Dep. {i + 1}", "share": 0.12 - i * 0.01, "drift": 0.0005, "sf_e": "n"}
                for i in range(12)
            ],
        }
    return {
        "qtd_vagas": 1,
        "candidates": [
            {"nome": f"Gov. {uf.upper()} A", "share": 0.52, "drift": 0.002, "sf_e": "n"},
            {"nome": f"Gov. {uf.upper()} B", "share": 0.38, "drift": -0.0015, "sf_e": "n"},
            {"nome": f"Gov. {uf.upper()} C", "share": 0.10, "drift": 0.0, "sf_e": "n"},
        ],
    }


def _calc_distancia(
    candidatos: list[dict],
    qtd_vagas: int,
    aprox_votos_restantes: int,
    majoritario: bool,
):
    if not majoritario or not candidatos or not qtd_vagas:
        return
    cand_lim = candidatos[qtd_vagas - 1]
    for cand in candidatos[qtd_vagas:]:
        dist = cand_lim["qtd_votos"] - cand["qtd_votos"]
        cand["distancia_votos"] = dist
        cand["viavel"] = dist <= aprox_votos_restantes


def fetch_mock_panel(panel_key: str, printables: int, prev_entry: dict | None) -> dict:
    panel_key, uf, cargo = resolve_panel(panel_key)
    title = panel_title(uf, cargo)
    scenario = _scenario(panel_key)

    with _lock:
        state = _state.setdefault(
            panel_key,
            {"tick": 0, "perc_apurado": 0.0, "prev_perc": {}},
        )
        state["tick"] += 1
        tick = state["tick"]

        if tick <= 1:
            state["perc_apurado"] = 0.0
        else:
            state["perc_apurado"] = min(100.0, state["perc_apurado"] + 2.8)

        perc_apurado = state["perc_apurado"]
        perc_pendente = max(0.0, 100.0 - perc_apurado)
        vv = int(_VV_BASE * perc_apurado / 100)
        comparecimento = 78.5
        pvv = 92.0
        if perc_apurado > 0:
            aprox_votos_restantes = int(vv * perc_pendente / perc_apurado)
        else:
            aprox_vv = int(_ELEITORADO * comparecimento / 100 * pvv / 100)
            aprox_votos_restantes = int(aprox_vv * perc_pendente / 100)
        majoritario = cargo in CARGOS_MAJORITARIOS

        prev_perc_map = dict(state["prev_perc"])
        candidatos = []
        for spec in scenario["candidates"]:
            drift = spec["drift"] * tick
            perc = max(0.1, (spec["share"] + drift) * 100)
            qtd_votos = int(vv * perc / 100) if perc_apurado > 0 else 0
            prev_p = prev_perc_map.get(spec["nome"], perc if perc_apurado > 0 else 0)
            delta = round(perc - prev_p, 2) if perc_apurado > 0 else None
            if delta == 0:
                delta = None
            candidatos.append(
                {
                    "nome": spec["nome"],
                    "qtd_votos": qtd_votos,
                    "perc_votos": round(perc, 2),
                    "delta_perc": delta,
                    "sf_e": spec["sf_e"],
                    "sf_st": "",
                    "distancia_votos": None,
                    "viavel": None,
                }
            )
            state["prev_perc"][spec["nome"]] = perc

        candidatos.sort(key=lambda c: c["perc_votos"], reverse=True)
        qtd_vagas = scenario["qtd_vagas"]
        _calc_distancia(candidatos, qtd_vagas, aprox_votos_restantes, majoritario)

        mat_def, mat_def_label = "", None
        if majoritario:
            mat_def, mat_def_label = infer_mat_def_majoritario(
                candidatos, aprox_votos_restantes
            )
            apply_mat_def_majoritario(candidatos, mat_def)

        now = datetime.now()
        tse_update = now - timedelta(seconds=45 + (tick % 20))
        tse_delay = int((now - tse_update).total_seconds())

        entry = {
            "key": panel_key,
            "title": title,
            "printables": printables,
            "error": None,
            "perc_sec_totalizadas": round(perc_apurado, 2),
            "perc_comparecimento": comparecimento,
            "aprox_votos_restantes": aprox_votos_restantes,
            "latest_update_tse": tse_update.isoformat(),
            "tse_delay_seconds": tse_delay,
            "tse_delay_human": format_duration(tse_delay),
            "apuracao_iniciada": perc_apurado > 0,
            "mat_def": mat_def,
            "mat_def_label": mat_def_label,
            "majoritario": majoritario,
            "qtd_vagas": qtd_vagas,
            "candidatos": candidatos[:printables],
            "updated_at": now.isoformat(),
            "mock": True,
        }
        return entry
