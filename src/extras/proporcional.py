def _int(value) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, str):
        value = value.replace(",", ".")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def legenda_votos(agr: dict) -> int:
    return sum(_int(partido.get("tvan")) for partido in agr.get("par", []))


def build_legendas(agr_list: list) -> list[dict]:
    legendas = []
    for agr in agr_list:
        agr_id = agr.get("nm") or agr.get("n") or ""
        if not agr_id:
            continue
        legendas.append(
            {
                "id": agr_id,
                "sigla": _legenda_sigla(agr),
                "votos": legenda_votos(agr),
                "tipo": agr.get("tp", ""),
            }
        )
    return legendas


def _legenda_sigla(agr: dict) -> str:
    partidos = agr.get("par", [])
    if len(partidos) == 1:
        return partidos[0].get("sg") or agr.get("nm", "")
    nome = agr.get("nm", "")
    if " - " in nome:
        return nome.split(" - ", 1)[-1].strip()
    return nome[:24]


def project_seats_dhondt(legendas: list[dict], vagas: int, vv: int) -> dict[str, int]:
    seats = {legenda["id"]: 0 for legenda in legendas}
    if not vagas or not vv or not legendas:
        return seats

    qe = vv // vagas
    if qe <= 0:
        return seats

    min_votos = int(qe * 0.8)
    eligible = [legenda for legenda in legendas if legenda["votos"] >= min_votos]
    if not eligible:
        return seats

    for legenda in legendas:
        if legenda["id"] not in seats:
            seats[legenda["id"]] = 0

    for _ in range(vagas):
        best_id = None
        best_avg = -1.0
        for legenda in eligible:
            atual = seats[legenda["id"]]
            media = legenda["votos"] / (atual + 1)
            if media > best_avg:
                best_avg = media
                best_id = legenda["id"]
        if best_id:
            seats[best_id] += 1

    return seats


def build_legendas_resumo(legendas: list[dict], seats: dict[str, int], limit: int = 5) -> list[dict]:
    resumo = []
    for legenda in sorted(legendas, key=lambda item: item["votos"], reverse=True):
        cadeiras = seats.get(legenda["id"], 0)
        if legenda["votos"] <= 0 and cadeiras <= 0:
            continue
        resumo.append(
            {
                "sigla": legenda["sigla"],
                "votos": legenda["votos"],
                "cadeiras": cadeiras,
            }
        )
        if len(resumo) >= limit:
            break
    return resumo


def restantes_legenda(aprox_votos_restantes: int, legenda_votos: int, vv: int) -> int:
    if not vv or not aprox_votos_restantes or not legenda_votos:
        return 0
    return int(aprox_votos_restantes * legenda_votos / vv)


def apply_garantia_matematica(
    por_legenda: dict[str, list],
    legendas_por_id: dict,
    aprox_votos_restantes: int,
    vv: int,
) -> None:
    for agr_id, grupo in por_legenda.items():
        for cand in grupo:
            _set_cand_field(cand, "garantido", False)
            _set_cand_field(cand, "eliminado_mat", False)

        cadeiras = _cand_field(grupo[0], "cadeiras_proj") or 0 if grupo else 0
        if cadeiras <= 0:
            continue

        legenda = legendas_por_id.get(agr_id)
        leg_votos = legenda["votos"] if legenda else 0
        rest_leg = restantes_legenda(aprox_votos_restantes, leg_votos, vv)
        primeiro_fora = _cand_votos(grupo[cadeiras]) if len(grupo) > cadeiras else 0

        for cand in grupo[:cadeiras]:
            if len(grupo) <= cadeiras and rest_leg <= 0:
                _set_cand_field(cand, "garantido", True)
                continue
            if len(grupo) <= cadeiras:
                continue
            gap = _cand_votos(cand) - primeiro_fora
            _set_cand_field(cand, "garantido", gap > rest_leg)

        if len(grupo) <= cadeiras:
            continue
        ultimo_dentro = _cand_votos(grupo[cadeiras - 1])
        for cand in grupo[cadeiras:]:
            gap = ultimo_dentro - _cand_votos(cand)
            _set_cand_field(cand, "eliminado_mat", gap > rest_leg)


def apply_proporcional(
    candidatos,
    agr_list: list,
    vagas: int,
    vv: int,
    aprox_votos_restantes: int = 0,
) -> list[dict]:
    legendas = build_legendas(agr_list)
    seats = project_seats_dhondt(legendas, vagas, vv)
    legendas_por_id = {legenda["id"]: legenda for legenda in legendas}

    por_legenda: dict[str, list] = {}
    por_partido: dict[tuple[str, str], list] = {}

    for cand in candidatos:
        agr_id = getattr(cand, "agr_id", None) or cand.get("agr_id")
        par_sg = getattr(cand, "par_sg", None) or cand.get("par_sg")
        if not agr_id:
            continue
        por_legenda.setdefault(agr_id, []).append(cand)
        por_partido.setdefault((agr_id, par_sg or ""), []).append(cand)

    for grupo in por_legenda.values():
        grupo.sort(key=lambda item: _cand_votos(item), reverse=True)
        agr_id = getattr(grupo[0], "agr_id", None) or grupo[0].get("agr_id")
        cadeiras = seats.get(agr_id, 0)
        for posicao, cand in enumerate(grupo, start=1):
            _set_cand_field(cand, "posicao_legenda", posicao)
            _set_cand_field(cand, "cadeiras_proj", cadeiras)
            _set_cand_field(
                cand,
                "dentro_proj",
                posicao <= cadeiras if cadeiras > 0 else False,
            )

    for grupo in por_partido.values():
        grupo.sort(key=lambda item: _cand_votos(item), reverse=True)
        for posicao, cand in enumerate(grupo, start=1):
            _set_cand_field(cand, "posicao_partido", posicao)

    for cand in candidatos:
        agr_id = getattr(cand, "agr_id", None) or cand.get("agr_id")
        par_sg = getattr(cand, "par_sg", None) or cand.get("par_sg")
        legenda = legendas_por_id.get(agr_id or "")
        _set_cand_field(cand, "partido_sg", par_sg)
        _set_cand_field(cand, "legenda_sigla", legenda["sigla"] if legenda else par_sg)

    apply_garantia_matematica(
        por_legenda, legendas_por_id, aprox_votos_restantes, vv
    )
    apply_margem_corte(por_legenda, legendas_por_id, aprox_votos_restantes, vv)
    sort_candidatos_proporcional(candidatos)
    return build_legendas_resumo(legendas, seats)


def apply_margem_corte(
    por_legenda: dict[str, list],
    legendas_por_id: dict,
    aprox_votos_restantes: int,
    vv: int,
) -> None:
    for agr_id, grupo in por_legenda.items():
        if not grupo:
            continue
        cadeiras = _cand_field(grupo[0], "cadeiras_proj") or 0
        legenda = legendas_por_id.get(agr_id)
        leg_votos = legenda["votos"] if legenda else 0
        rest_leg = restantes_legenda(aprox_votos_restantes, leg_votos, vv)
        v_ultimo = _cand_votos(grupo[cadeiras - 1]) if cadeiras > 0 and len(grupo) >= cadeiras else 0
        v_fora = _cand_votos(grupo[cadeiras]) if cadeiras > 0 and len(grupo) > cadeiras else 0

        for posicao, cand in enumerate(grupo, start=1):
            v_p = _cand_votos(cand)
            _set_cand_field(cand, "restantes_legenda", rest_leg)
            if cadeiras <= 0:
                _set_cand_field(cand, "margem_corte", None)
                _set_cand_field(cand, "margem_folga", None)
                continue
            if posicao <= cadeiras:
                margem = v_p - v_fora if len(grupo) > cadeiras else v_p
                _set_cand_field(cand, "margem_corte", max(0, margem))
                _set_cand_field(cand, "margem_folga", True)
            else:
                _set_cand_field(cand, "margem_corte", max(0, v_ultimo - v_p))
                _set_cand_field(cand, "margem_folga", False)


def _cand_field(cand, name: str):
    if hasattr(cand, name):
        return getattr(cand, name)
    if isinstance(cand, dict):
        return cand.get(name)
    return None


def proporcional_sort_key(cand):
    sf_e = _cand_field(cand, "sf_e") or "n"
    pos = _cand_field(cand, "posicao_legenda") or 999
    seats = _cand_field(cand, "cadeiras_proj") or 0
    votos = _cand_votos(cand)

    if sf_e not in ("n", "", None) or _cand_field(cand, "garantido"):
        return (0, pos, -votos)

    if _cand_field(cand, "dentro_proj"):
        return (1, pos, -votos)

    gap = pos - seats if seats > 0 else pos
    return (2, gap, pos, -votos)


def sort_candidatos_proporcional(candidatos) -> None:
    candidatos.sort(key=proporcional_sort_key)


def _cand_votos(cand) -> int:
    return cand.qtd_votos if hasattr(cand, "qtd_votos") else _int(cand.get("qtd_votos"))


def _set_cand_field(cand, name: str, value):
    if hasattr(cand, name):
        setattr(cand, name, value)
    elif isinstance(cand, dict):
        cand[name] = value
