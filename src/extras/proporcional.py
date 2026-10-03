from datetime import datetime


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
    nome = agr.get("nm", "") or ""
    if " - " in nome:
        return nome.split(" - ", 1)[-1].strip()
    siglas = [partido.get("sg") for partido in partidos if partido.get("sg")]
    if siglas:
        return "+".join(siglas)
    nome = nome.removeprefix("FEDERAÇÃO ").strip()
    return nome[:20] if len(nome) > 20 else nome


def calc_quociente_eleitoral(vv: int, vagas: int) -> int:
    """Art. 9 Res.-TSE 23.677: fração > 0,5 arredonda para 1; senão despreza."""
    if vagas <= 0 or vv <= 0:
        return 0
    inteiro, resto = divmod(vv, vagas)
    if resto * 2 > vagas:
        return inteiro + 1
    return inteiro


def calc_quociente_partidario(votos_legenda: int, qe: int) -> int:
    """Art. 10: parte inteira de votos_legenda / QE."""
    if qe <= 0:
        return 0
    return votos_legenda // qe


def min_votos_frac(qe: int, numerador: int, denominador: int) -> int:
    """Menor inteiro v tal que v >= qe * numerador / denominador."""
    if qe <= 0 or denominador <= 0:
        return 0
    return (qe * numerador + denominador - 1) // denominador


def _parse_nascimento(value) -> datetime | None:
    if not value:
        return None
    texto = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


def _cand_sort_key(cand):
    """Mais votos primeiro; em empate, maior idade (art. 12 Res.-TSE 23.677)."""
    votos = _cand_votos(cand)
    nasc = _parse_nascimento(_cand_field(cand, "nascimento"))
    nasc_ord = nasc.timestamp() if nasc else float("inf")
    return (-votos, nasc_ord)


class _LegendaCalc:
    def __init__(self, legenda: dict, candidatos: list):
        self.legenda_id = legenda["id"]
        self.votos = legenda["votos"]
        self.candidatos = sorted(candidatos, key=_cand_sort_key)
        self.qp = 0
        self.lugares_obtidos = 0
        self.elected: list = []

    def _elected_ids(self) -> set:
        return {id(c) for c in self.elected}

    def unelected(self, min_votos: int = 0) -> list:
        elected_ids = self._elected_ids()
        return [
            cand
            for cand in self.candidatos
            if id(cand) not in elected_ids and _cand_votos(cand) >= min_votos
        ]

    def media(self) -> float:
        return self.votos / (self.lugares_obtidos + 1)

    def elect(self, cand) -> None:
        if id(cand) not in self._elected_ids():
            self.elected.append(cand)

    def allocate_qp_slots(self, qp: int, min_votos_candidato: int) -> None:
        self.qp = qp
        for _ in range(qp):
            self.lugares_obtidos += 1
            elegiveis = self.unelected(min_votos_candidato)
            if elegiveis:
                self.elect(elegiveis[0])


def _phase1_sobra_possible(calcs: list[_LegendaCalc], min80: int, min20: int) -> bool:
    for calc in calcs:
        if calc.votos < min80:
            continue
        if calc.unelected(min20):
            return True
    return False


def _top_unelected_votos(calc: _LegendaCalc, min_votos: int) -> int:
    elegiveis = calc.unelected(min_votos)
    return _cand_votos(elegiveis[0]) if elegiveis else -1


def _sobra_melhor_que(
    calc: _LegendaCalc,
    best: _LegendaCalc,
    media: float,
    best_media: float,
    min_votos_cand: int,
) -> bool:
    if media > best_media:
        return True
    if media < best_media:
        return False
    if calc.votos > best.votos:
        return True
    if calc.votos < best.votos:
        return False
    return _top_unelected_votos(calc, min_votos_cand) > _top_unelected_votos(
        best, min_votos_cand
    )


def _best_legenda_sobra(
    calcs: list[_LegendaCalc], strict: bool, min80: int, min20: int
) -> _LegendaCalc | None:
    best: _LegendaCalc | None = None
    best_media = -1.0
    min_votos_cand = min20 if strict else 0

    for calc in calcs:
        if strict:
            if calc.votos < min80 or not calc.unelected(min20):
                continue
        elif not calc.unelected(0):
            continue

        media = calc.media()
        if best is None or _sobra_melhor_que(calc, best, media, best_media, min_votos_cand):
            best_media = media
            best = calc

    return best


def is_candidato_eleito_tse(cand, proporcional: bool = False) -> bool:
    sf_e = _cand_field(cand, "sf_e")
    if sf_e in (None, "", "n"):
        return False
    if proporcional:
        # Proporcional (ex. vereador Natal 2024): eleitos com sf_e == "s".
        return sf_e == "s"
    return sf_e != "s"


def tem_resultado_oficial_tse(candidatos, proporcional: bool = False) -> bool:
    return any(is_candidato_eleito_tse(cand, proporcional) for cand in candidatos)


def seats_from_oficial(
    legendas: list[dict],
    por_legenda: dict[str, list],
    candidatos,
    proporcional: bool = False,
) -> tuple[dict[str, int], set[int]]:
    seats = {legenda["id"]: 0 for legenda in legendas}
    elected_ids: set[int] = set()
    for cand in candidatos:
        if not is_candidato_eleito_tse(cand, proporcional):
            continue
        elected_ids.add(id(cand))
        agr_id = getattr(cand, "agr_id", None) or cand.get("agr_id")
        if agr_id in seats:
            seats[agr_id] += 1
    return seats, elected_ids


def distribute_cadeiras_tse(
    legendas: list[dict],
    por_legenda: dict[str, list],
    vagas: int,
    vv: int,
) -> tuple[dict[str, int], list[_LegendaCalc]]:
    """
    Distribuição proporcional conforme Res.-TSE 23.677 (arts. 8–12-A):
    QE → QP + cláusula 10% → sobras por média (80/20) → sobras finais abertas.
    """
    seats = {legenda["id"]: 0 for legenda in legendas}
    if not vagas or not vv or not legendas:
        return seats, []

    qe = calc_quociente_eleitoral(vv, vagas)
    if qe <= 0:
        return seats, []

    min10 = min_votos_frac(qe, 1, 10)
    min20 = min_votos_frac(qe, 1, 5)
    min80 = min_votos_frac(qe, 4, 5)

    calcs: list[_LegendaCalc] = []
    for legenda in legendas:
        grupo = por_legenda.get(legenda["id"], [])
        calcs.append(_LegendaCalc(legenda, grupo))

    algum_alcancou_qe = any(calc.votos >= qe for calc in calcs)

    if algum_alcancou_qe:
        for calc in calcs:
            qp = calc_quociente_partidario(calc.votos, qe)
            calc.allocate_qp_slots(qp, min10)

    def total_elected() -> int:
        return sum(len(calc.elected) for calc in calcs)

    while total_elected() < vagas:
        strict = _phase1_sobra_possible(calcs, min80, min20)
        calc = _best_legenda_sobra(calcs, strict, min80, min20)
        if calc is None:
            break

        min_votos_cand = min20 if strict else 0
        cand = calc.unelected(min_votos_cand)[0]
        calc.lugares_obtidos += 1
        calc.elect(cand)

    for calc in calcs:
        seats[calc.legenda_id] = len(calc.elected)

    return seats, calcs


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


# Folga até esta fração do pendente da legenda = corrida apertada (em perigo).
RISCO_FOLGA_RATIO = 0.1


def restantes_legenda(aprox_votos_restantes: int, legenda_votos: int, vv: int) -> int:
    if not vv or not aprox_votos_restantes or not legenda_votos:
        return 0
    return int(aprox_votos_restantes * legenda_votos / vv)


def _grupo_ordenado(grupo: list) -> list:
    return sorted(grupo, key=_cand_sort_key)


def _candidatos_dentro(grupo: list) -> list:
    return [cand for cand in _grupo_ordenado(grupo) if _cand_field(cand, "dentro_proj")]


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

        dentro = _candidatos_dentro(grupo)
        cadeiras = len(dentro)
        if cadeiras <= 0:
            continue

        legenda = legendas_por_id.get(agr_id)
        leg_votos = legenda["votos"] if legenda else 0
        rest_leg = restantes_legenda(aprox_votos_restantes, leg_votos, vv)
        dentro_ids = {id(c) for c in dentro}
        primeiro_fora = next(
            (c for c in _grupo_ordenado(grupo) if id(c) not in dentro_ids),
            None,
        )
        primeiro_fora_votos = _cand_votos(primeiro_fora) if primeiro_fora else 0

        for cand in dentro:
            if not primeiro_fora and rest_leg <= 0:
                _set_cand_field(cand, "garantido", True)
                continue
            if not primeiro_fora:
                continue
            gap = _cand_votos(cand) - primeiro_fora_votos
            _set_cand_field(cand, "garantido", gap > rest_leg)

        if not primeiro_fora:
            continue
        ultimo_dentro_votos = _cand_votos(dentro[-1])
        for cand in _grupo_ordenado(grupo):
            if id(cand) in dentro_ids:
                continue
            gap = ultimo_dentro_votos - _cand_votos(cand)
            _set_cand_field(cand, "eliminado_mat", gap > rest_leg)


def apply_proporcional(
    candidatos,
    agr_list: list,
    vagas: int,
    vv: int,
    aprox_votos_restantes: int = 0,
    perc_apurado: float = 0,
) -> list[dict]:
    legendas = build_legendas(agr_list)
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

    usar_oficial = perc_apurado >= 100 and tem_resultado_oficial_tse(candidatos, True)
    if usar_oficial:
        seats, elected_ids = seats_from_oficial(
            legendas, por_legenda, candidatos, True
        )
    else:
        _, calcs = distribute_cadeiras_tse(legendas, por_legenda, vagas, vv)
        seats = {calc.legenda_id: len(calc.elected) for calc in calcs}
        elected_ids = {id(cand) for calc in calcs for cand in calc.elected}

    for grupo in por_legenda.values():
        grupo.sort(key=_cand_sort_key)
        agr_id = getattr(grupo[0], "agr_id", None) or grupo[0].get("agr_id")
        cadeiras = seats.get(agr_id, 0)
        for posicao, cand in enumerate(grupo, start=1):
            dentro = id(cand) in elected_ids
            _set_cand_field(cand, "posicao_legenda", posicao)
            _set_cand_field(cand, "cadeiras_proj", cadeiras)
            _set_cand_field(cand, "dentro_proj", dentro)

    for grupo in por_partido.values():
        grupo.sort(key=_cand_sort_key)
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
    apply_perigo_vaga(por_legenda)
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

        dentro = _candidatos_dentro(grupo)
        cadeiras = len(dentro)
        legenda = legendas_por_id.get(agr_id)
        leg_votos = legenda["votos"] if legenda else 0
        rest_leg = restantes_legenda(aprox_votos_restantes, leg_votos, vv)
        dentro_ids = {id(c) for c in dentro}
        v_ultimo = _cand_votos(dentro[-1]) if dentro else 0
        primeiro_fora = next(
            (c for c in _grupo_ordenado(grupo) if id(c) not in dentro_ids),
            None,
        )
        v_fora = _cand_votos(primeiro_fora) if primeiro_fora else 0

        for cand in _grupo_ordenado(grupo):
            v_p = _cand_votos(cand)
            _set_cand_field(cand, "restantes_legenda", rest_leg)
            if cadeiras <= 0:
                _set_cand_field(cand, "margem_corte", None)
                _set_cand_field(cand, "margem_folga", None)
                continue
            if id(cand) in dentro_ids:
                margem = v_p - v_fora if primeiro_fora else v_p
                _set_cand_field(cand, "margem_corte", max(0, margem))
                _set_cand_field(cand, "margem_folga", True)
            else:
                _set_cand_field(cand, "margem_corte", max(0, v_ultimo - v_p))
                _set_cand_field(cand, "margem_folga", False)


def apply_perigo_vaga(por_legenda: dict[str, list]) -> None:
    for _agr_id, grupo in por_legenda.items():
        for cand in grupo:
            _set_cand_field(cand, "em_perigo", False)

        dentro = _candidatos_dentro(grupo)
        if len(dentro) <= 0:
            continue

        primeiro_fora = next(
            (c for c in _grupo_ordenado(grupo) if not _cand_field(c, "dentro_proj")),
            None,
        )
        if primeiro_fora is None:
            continue

        cand = dentro[-1]
        if _cand_field(cand, "garantido") or _cand_field(cand, "eliminado_mat"):
            continue

        margem = _cand_field(cand, "margem_corte")
        rest = _cand_field(cand, "restantes_legenda") or 0
        if margem is None or rest <= 0 or margem > rest:
            continue

        if margem <= rest * RISCO_FOLGA_RATIO:
            _set_cand_field(cand, "em_perigo", True)


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
