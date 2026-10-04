import copy
import os
import threading
from datetime import datetime, timedelta

from extras.eleicao import (
    apply_garantido_segundo_turno,
    apply_mat_def,
    format_duration,
    infer_mat_def,
)
from extras.proporcional import apply_proporcional
from extras.tse_client import CARGOS_MAJORITARIOS, CARGOS_SEGUNDO_TURNO, panel_title, resolve_panel

MOCK_ENABLED = os.environ.get("TSELIVESCORE_MOCK", "").lower() in ("1", "true", "yes")

_lock = threading.Lock()
_state: dict[str, dict] = {}

_APURACAO_STEP = 2.8
_ELEITORADO = 120_000_000
_VV_BASE = 100_000_000

# Roteiro do mock (mock_tick global, sincronizado entre painéis):
#  8 — troca de cadeira no mesmo partido (PL 2 → PL 3)
# 14 — troca entre partidos + mudança no total de cadeiras (PSD → PL)
# 18 — eliminado (mat.) proporcional
# 22 — eleito (mat.) proporcional
# 26 — mat. definido: 2º turno (presidente)
# 27 — mat. definido: eleito (governador >50%)
# 30 — mat. definido: eleitos (senador, 2 vagas)
# 32 — fora da margem (mat.) proporcional (PL 4)
# 33 — eliminado (mat.) majoritário
# 37 — 100% apurado; congela até reset


def reset_mock_state() -> None:
    with _lock:
        _state.clear()


def _perc_apurado(mock_tick: int) -> float:
    if mock_tick <= 1:
        return 0.0
    return min(100.0, (mock_tick - 1) * _APURACAO_STEP)


def _dep_shares(mock_tick: int) -> dict[str, float]:
    base = {
        "Dep. PL 1": 0.058,
        "Dep. PL 2": 0.054,
        "Dep. PL 3": 0.052,
        "Dep. PL 4": 0.046,
        "Dep. PT 1": 0.066,
        "Dep. PT 2": 0.062,
        "Dep. PT 3": 0.060,
        "Dep. UNIÃO 1": 0.060,
        "Dep. UNIÃO 2": 0.057,
        "Dep. UNIÃO 3": 0.053,
        "Dep. PSD 1": 0.078,
        "Dep. PSD 2": 0.072,
    }
    if mock_tick < 8:
        return base
    if mock_tick < 14:
        return {
            **base,
            "Dep. PL 2": 0.050,
            "Dep. PL 3": 0.057,
        }
    if mock_tick < 18:
        return {
            **base,
            "Dep. PL 2": 0.061,
            "Dep. PL 3": 0.056,
            "Dep. PSD 1": 0.074,
            "Dep. PSD 2": 0.055,
        }
    if mock_tick < 22:
        return {
            **base,
            "Dep. PL 1": 0.072,
            "Dep. PL 2": 0.061,
            "Dep. PL 3": 0.056,
            "Dep. PL 4": 0.018,
            "Dep. PSD 1": 0.074,
            "Dep. PSD 2": 0.055,
        }
    return {
        **base,
        "Dep. PL 1": 0.080,
        "Dep. PL 2": 0.061,
        "Dep. PL 3": 0.056,
        "Dep. PL 4": 0.018,
        "Dep. PSD 1": 0.074,
        "Dep. PSD 2": 0.055,
    }


def _majoritario_candidates(cargo: str, uf: str, mock_tick: int) -> list[dict]:
    if cargo == "1":
        return [
            {"nome": "Candidato A", "share": 0.46, "sf_e": "n"},
            {"nome": "Candidato B", "share": 0.41, "sf_e": "n"},
            {"nome": "Candidato C", "share": 0.08, "sf_e": "n"},
            {"nome": "Candidato D", "share": 0.05, "sf_e": "n"},
        ]
    if cargo == "5":
        return [
            {"nome": f"Sen. {uf.upper()} A", "share": 0.34, "sf_e": "n"},
            {"nome": f"Sen. {uf.upper()} B", "share": 0.31, "sf_e": "n"},
            {"nome": f"Sen. {uf.upper()} C", "share": 0.20, "sf_e": "n"},
            {"nome": f"Sen. {uf.upper()} D", "share": 0.09, "sf_e": "n"},
            {"nome": f"Sen. {uf.upper()} E", "share": 0.06, "sf_e": "n"},
        ]
    if mock_tick < 27:
        return [
            {"nome": f"Gov. {uf.upper()} A", "share": 0.48, "sf_e": "n"},
            {"nome": f"Gov. {uf.upper()} B", "share": 0.40, "sf_e": "n"},
            {"nome": f"Gov. {uf.upper()} C", "share": 0.12, "sf_e": "n"},
        ]
    return [
        {"nome": f"Gov. {uf.upper()} A", "share": 0.52, "sf_e": "n"},
        {"nome": f"Gov. {uf.upper()} B", "share": 0.38, "sf_e": "n"},
        {"nome": f"Gov. {uf.upper()} C", "share": 0.10, "sf_e": "n"},
    ]


def _sf_e_overrides(cargo: str, mock_tick: int) -> dict[str, str]:
    return {}


def _apply_proporcional_mock(
    candidatos,
    agr_list,
    qtd_vagas: int,
    vv: int,
    aprox_votos_restantes: int,
    perc_apurado: float,
) -> list[dict]:
    """Em 100%, projeta antes e só então marca todos os eleitos com sf_e oficial."""
    if perc_apurado >= 100:
        apply_proporcional(
            candidatos,
            agr_list,
            qtd_vagas,
            vv,
            aprox_votos_restantes,
            99.0,
        )
        for cand in candidatos:
            if cand.get("dentro_proj"):
                cand["sf_e"] = "s"
        return apply_proporcional(
            candidatos,
            agr_list,
            qtd_vagas,
            vv,
            aprox_votos_restantes,
            perc_apurado,
        )
    return apply_proporcional(
        candidatos,
        agr_list,
        qtd_vagas,
        vv,
        aprox_votos_restantes,
        perc_apurado,
    )


def _scenario(panel_key: str) -> dict:
    _, uf, cargo = resolve_panel(panel_key)
    if cargo in ("6", "7", "8"):
        return {"qtd_vagas": 8, "proporcional": True}
    if cargo == "1":
        return {"qtd_vagas": 1, "proporcional": False}
    if cargo == "5":
        return {"qtd_vagas": 2, "proporcional": False}
    return {"qtd_vagas": 1, "proporcional": False}


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


def fetch_mock_panel(
    panel_key: str, prev_entry: dict | None, mock_tick: int = 1
) -> dict:
    panel_key, uf, cargo = resolve_panel(panel_key)
    title = panel_title(uf, cargo)
    scenario = _scenario(panel_key)

    with _lock:
        state = _state.setdefault(panel_key, {"prev_perc": {}, "frozen_entry": None})
        frozen = state.get("frozen_entry")
        if frozen is not None:
            return copy.deepcopy(frozen)

        perc_apurado = _perc_apurado(mock_tick)
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
        proporcional = scenario.get("proporcional", False)
        sf_e_map = _sf_e_overrides(cargo, mock_tick)

        prev_perc_map = dict(state["prev_perc"])
        candidatos = []
        agr_list = []

        if proporcional:
            shares = _dep_shares(mock_tick)
            parties: dict[str, list[tuple[str, float]]] = {}
            for nome, share in shares.items():
                partido = nome.split()[1]
                parties.setdefault(partido, []).append((nome, share))
            for partido, deps in parties.items():
                agr_list.append(
                    {
                        "nm": partido,
                        "tp": "i",
                        "par": [{"sg": partido, "tvan": "0", "cand": []}],
                    }
                )
                party_votes = 0
                for nome, share in deps:
                    if perc_apurado > 0:
                        perc = max(0.05, share * 100)
                        qtd_votos = int(vv * share)
                    else:
                        perc = 0.0
                        qtd_votos = 0
                    party_votes += qtd_votos
                    candidatos.append(
                        {
                            "nome": nome,
                            "qtd_votos": qtd_votos,
                            "perc_votos": round(perc, 2),
                            "delta_perc": None,
                            "garantido": False,
                            "eliminado_mat": False,
                            "eliminado_definitivo": False,
                            "margem_corte": None,
                            "margem_folga": None,
                            "restantes_legenda": None,
                            "em_perigo": False,
                            "sf_e": sf_e_map.get(nome, "n"),
                            "sf_st": "",
                            "distancia_votos": None,
                            "viavel": None,
                            "agr_id": partido,
                            "par_sg": partido,
                        }
                    )
                agr_list[-1]["par"][0]["tvan"] = str(party_votes)
        else:
            for spec in _majoritario_candidates(cargo, uf, mock_tick):
                if perc_apurado > 0:
                    perc = max(0.1, spec["share"] * 100)
                    qtd_votos = int(vv * perc / 100)
                    prev_p = prev_perc_map.get(spec["nome"], perc)
                    delta = round(perc - prev_p, 2)
                    if delta == 0:
                        delta = None
                    state["prev_perc"][spec["nome"]] = perc
                else:
                    perc = 0.0
                    qtd_votos = 0
                    delta = None
                candidatos.append(
                    {
                        "nome": spec["nome"],
                        "qtd_votos": qtd_votos,
                        "perc_votos": round(perc, 2),
                        "delta_perc": delta,
                        "sf_e": sf_e_map.get(spec["nome"], spec["sf_e"]),
                        "sf_st": "",
                        "distancia_votos": None,
                        "viavel": None,
                    }
                )

        if not proporcional:
            candidatos.sort(key=lambda c: c["perc_votos"], reverse=True)
        qtd_vagas = scenario["qtd_vagas"]
        if perc_apurado > 0:
            _calc_distancia(candidatos, qtd_vagas, aprox_votos_restantes, majoritario)

        legendas_resumo = []
        if proporcional and agr_list and perc_apurado > 0:
            legendas_resumo = _apply_proporcional_mock(
                candidatos,
                agr_list,
                qtd_vagas,
                vv if perc_apurado > 0 else 0,
                aprox_votos_restantes,
                perc_apurado,
            )

        mat_def, mat_def_label = "", None
        if majoritario and perc_apurado > 0:
            mat_def, mat_def_label = infer_mat_def(
                candidatos, aprox_votos_restantes, cargo, qtd_vagas
            )
            apply_mat_def(candidatos, mat_def, cargo, qtd_vagas)
            if cargo in CARGOS_SEGUNDO_TURNO:
                apply_garantido_segundo_turno(
                    candidatos, aprox_votos_restantes, mat_def or ""
                )

        now = datetime.now()
        tse_update = now - timedelta(seconds=2 + (mock_tick % 6))
        tse_delay = int((now - tse_update).total_seconds())

        entry = {
            "key": panel_key,
            "title": title,
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
            "proporcional": proporcional,
            "segundo_turno": cargo in CARGOS_SEGUNDO_TURNO,
            "legendas_resumo": legendas_resumo,
            "qtd_vagas": qtd_vagas,
            "candidatos": candidatos,
            "updated_at": now.isoformat(),
            "mock": True,
            "mock_tick": mock_tick,
        }

        if perc_apurado >= 100.0:
            state["frozen_entry"] = copy.deepcopy(entry)

        return entry
