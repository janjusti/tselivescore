from datetime import datetime
from zoneinfo import ZoneInfo

from extras import torequests
from extras.proporcional import apply_proporcional, infer_mat_def_proporcional
from extras.tse_client import (
    CARGOS_MAJORITARIOS,
    CARGOS_PROPORCIONAIS,
    CARGOS_SEGUNDO_TURNO,
    build_url,
    normalize_payload,
    parse_response,
    resolve_panel,
    tse_timezone_for_panel,
    TZ_BRASILIA,
)


FINGERPRINT_HEAD_CANDIDATOS = 50

CANDIDATO_TRACK_FIELDS = (
    "nome",
    "perc_votos",
    "sf_e",
    "garantido",
    "garantido_turno",
    "eliminado_mat",
    "eliminado_definitivo",
    "viavel",
    "dentro_proj",
    "em_perigo",
    "legenda_sigla",
    "partido_sg",
)


def _cand_get(cand, field: str):
    if isinstance(cand, dict):
        return cand.get(field)
    return getattr(cand, field, None)


def cand_is_track_relevant(cand) -> bool:
    if _cand_get(cand, "dentro_proj"):
        return True
    if _cand_get(cand, "em_perigo"):
        return True
    if _cand_get(cand, "garantido"):
        return True
    if _cand_get(cand, "garantido_turno"):
        return True
    if _cand_get(cand, "eliminado_mat"):
        return True
    if _cand_get(cand, "eliminado_definitivo"):
        return True
    sf_e = _cand_get(cand, "sf_e")
    if sf_e not in (None, "", "n"):
        return True
    if _cand_get(cand, "distancia_votos") is not None:
        return True
    return False


def candidatos_for_track(candidatos, printables: int) -> list:
    start = max(0, int(printables or 0))
    tail = list(candidatos or [])[start:]
    return [cand for cand in tail if cand_is_track_relevant(cand)]


def candidatos_track_payload(candidatos) -> list[dict]:
    rows = []
    for cand in candidatos or []:
        if isinstance(cand, dict):
            rows.append({field: cand.get(field) for field in CANDIDATO_TRACK_FIELDS})
        elif hasattr(cand, "to_dict"):
            data = cand.to_dict()
            rows.append({field: data.get(field) for field in CANDIDATO_TRACK_FIELDS})
        else:
            rows.append({field: getattr(cand, field, None) for field in CANDIDATO_TRACK_FIELDS})
    return rows


def cand_fingerprint_part(cand) -> str:
    return (
        f"{_cand_get(cand, 'nome')}:{_cand_get(cand, 'qtd_votos')}:"
        f"{_cand_get(cand, 'perc_votos')}:{_cand_get(cand, 'sf_e')}:"
        f"{_cand_get(cand, 'garantido')}:{_cand_get(cand, 'garantido_turno')}:"
        f"{_cand_get(cand, 'dentro_proj')}:{_cand_get(cand, 'em_perigo')}:"
        f"{_cand_get(cand, 'eliminado_mat')}:{_cand_get(cand, 'eliminado_definitivo')}"
    )


def entry_fingerprint(entry: dict | None) -> int:
    import zlib

    if not entry:
        return 0
    parts = [
        str(entry.get("perc_sec_totalizadas")),
        str(entry.get("aprox_votos_restantes")),
        str(entry.get("mat_def")),
        str(entry.get("mock_tick")),
        str(entry.get("latest_update_tse")),
        str(entry.get("error")),
        str(len(entry.get("candidatos") or [])),
    ]
    for leg in entry.get("legendas_resumo") or []:
        parts.append(f"{leg.get('sigla')}:{leg.get('cadeiras')}:{leg.get('votos')}")
    for idx, cand in enumerate(entry.get("candidatos") or []):
        if idx < FINGERPRINT_HEAD_CANDIDATOS or cand_is_track_relevant(cand):
            parts.append(cand_fingerprint_part(cand))
    return zlib.crc32("|".join(parts).encode()) & 0xFFFFFFFF


def format_duration(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None
    total = int(seconds)
    if total < 0:
        total = 0
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}min"
    return f"{total}s"


def _cand_votos(cand) -> int:
    return cand.qtd_votos if hasattr(cand, "qtd_votos") else cand["qtd_votos"]


def _cand_perc(cand) -> float:
    return cand.perc_votos if hasattr(cand, "perc_votos") else cand["perc_votos"]


def infer_mat_def_segundo_turno(
    candidatos, aprox_votos_restantes, vv: int = 0
) -> tuple[str, str | None]:
    """Presidente/governador: maioria absoluta ou 2º turno."""
    if not candidatos or len(candidatos) < 2:
        return "", None

    restantes = max(0, int(aprox_votos_restantes or 0))
    leader, second = candidatos[0], candidatos[1]
    vv = max(0, int(vv or 0))

    if vv > 0:
        min_perc_lider = _cand_votos(leader) * 100 / (vv + restantes)
        if min_perc_lider > 50:
            return "E", "Eleito"

    if len(candidatos) >= 3:
        third = candidatos[2]
        gap_2o_3o = _cand_votos(second) - _cand_votos(third)
        terceiro_nao_alcanca = gap_2o_3o > restantes
        perc_lider = _cand_perc(leader)
        if terceiro_nao_alcanca and perc_lider > 0:
            vv = int(_cand_votos(leader) * 100 / perc_lider)
            if vv > 0:
                max_perc_lider = (_cand_votos(leader) + restantes) * 100 / (vv + restantes)
                if max_perc_lider < 50:
                    return "S", "Segundo turno"

    return "", None


def infer_mat_def_plurality(
    candidatos, aprox_votos_restantes, qtd_vagas: int
) -> tuple[str, str | None]:
    """Senador: maioria relativa; os qtd_vagas mais votados, sem 2º turno."""
    if not candidatos or qtd_vagas <= 0:
        return "", None

    restantes = max(0, int(aprox_votos_restantes or 0))
    if len(candidatos) <= qtd_vagas:
        return "E", "Eleitos" if qtd_vagas > 1 else "Eleito"

    cand_lim = candidatos[qtd_vagas - 1]
    primeiro_fora = candidatos[qtd_vagas]
    gap = _cand_votos(cand_lim) - _cand_votos(primeiro_fora)
    if gap > restantes:
        return "E", "Eleitos" if qtd_vagas > 1 else "Eleito"

    return "", None


def infer_mat_def(
    candidatos,
    aprox_votos_restantes,
    cargo_cd: str,
    qtd_vagas: int,
    vv: int = 0,
) -> tuple[str, str | None]:
    if cargo_cd in CARGOS_SEGUNDO_TURNO:
        return infer_mat_def_segundo_turno(candidatos, aprox_votos_restantes, vv)
    if cargo_cd in CARGOS_MAJORITARIOS:
        return infer_mat_def_plurality(candidatos, aprox_votos_restantes, qtd_vagas)
    return "", None


# Compat: nome antigo usado em testes/fixtures legados.
infer_mat_def_majoritario = infer_mat_def_segundo_turno


def _cand_sf_e(cand) -> str:
    if hasattr(cand, "sf_e"):
        return cand.sf_e or "n"
    return cand.get("sf_e") or "n"


def _clear_eleito_mat(candidatos) -> None:
    for cand in candidatos:
        if hasattr(cand, "eleito_mat"):
            cand.eleito_mat = False
        elif isinstance(cand, dict):
            cand["eleito_mat"] = False


def _set_eleito_mat(cand, value: bool = True) -> None:
    if _cand_sf_e(cand) in ("e", "s"):
        return
    if hasattr(cand, "eleito_mat"):
        cand.eleito_mat = value
    elif isinstance(cand, dict):
        cand["eleito_mat"] = value


def apply_mat_def_segundo_turno(candidatos, mat_def: str) -> str:
    if not candidatos or not mat_def:
        return mat_def
    leader = candidatos[0]
    if mat_def == "E":
        _set_eleito_mat(leader, True)
    elif mat_def == "S":
        for cand in candidatos[:2]:
            if hasattr(cand, "viavel"):
                cand.viavel = None
                cand.distancia_votos = None
            else:
                cand["viavel"] = None
                cand["distancia_votos"] = None
    return mat_def


def apply_mat_def_plurality(candidatos, mat_def: str, qtd_vagas: int) -> str:
    if not candidatos or not mat_def or mat_def != "E" or qtd_vagas <= 0:
        return mat_def
    for cand in candidatos[:qtd_vagas]:
        _set_eleito_mat(cand, True)
    return mat_def


def apply_mat_def(candidatos, mat_def: str, cargo_cd: str, qtd_vagas: int) -> str:
    _clear_eleito_mat(candidatos)
    if cargo_cd in CARGOS_SEGUNDO_TURNO:
        return apply_mat_def_segundo_turno(candidatos, mat_def)
    if cargo_cd in CARGOS_MAJORITARIOS:
        return apply_mat_def_plurality(candidatos, mat_def, qtd_vagas)
    return mat_def


apply_mat_def_majoritario = apply_mat_def_segundo_turno


def calc_maioria_1t(
    candidatos,
    aprox_votos_restantes,
    vv: int,
    *,
    segundo_turno: bool,
    mat_def: str,
    apuracao_iniciada: bool,
) -> dict | None:
    """Votos mínimos do líder nos pendentes para garantir >50% no total (pior caso)."""
    if not segundo_turno or not apuracao_iniciada or not candidatos:
        return None
    mat = (mat_def or "").upper()
    if mat == "E":
        return None
    leader = candidatos[0]
    if _cand_sf_e(leader) == "e":
        return None

    vv = max(0, int(vv or 0))
    restantes = max(0, int(aprox_votos_restantes or 0))
    if vv <= 0:
        return None

    vv_final = vv + restantes
    minimo = vv_final // 2 + 1
    votos_necessarios = max(0, minimo - _cand_votos(leader))
    percentual_minimo_final = _cand_votos(leader) * 100 / vv_final
    garantida = votos_necessarios == 0
    impossivel = votos_necessarios > restantes

    return {
        "votos_necessarios": votos_necessarios,
        "votos_restantes": restantes,
        "percentual_minimo_final": round(percentual_minimo_final, 2),
        "garantida": garantida,
        "impossivel": impossivel,
    }


def apply_garantido_segundo_turno(
    candidatos, aprox_votos_restantes, mat_def: str
) -> None:
    """Marca os dois primeiros quando o 3º não pode ultrapassá-los (vaga no 2º turno)."""
    if not candidatos or mat_def == "E" or len(candidatos) < 3:
        return
    restantes = max(0, int(aprox_votos_restantes or 0))
    third_votos = _cand_votos(candidatos[2])
    for cand in candidatos[:2]:
        if hasattr(cand, "garantido_turno"):
            cand.garantido_turno = False
        else:
            cand["garantido_turno"] = False
        sf_e = cand.sf_e if hasattr(cand, "sf_e") else cand.get("sf_e")
        if sf_e in ("s", "e"):
            continue
        if _cand_votos(cand) - third_votos > restantes:
            if hasattr(cand, "garantido_turno"):
                cand.garantido_turno = True
            else:
                cand["garantido_turno"] = True


class Candidato:
    def __init__(
        self,
        nome: str,
        qtd_votos: int,
        perc_votos: float,
        sf_e: str,
        sf_st: str,
        prev_perc_votos: float,
    ):
        self.nome = nome.replace("&apos;", "'")
        self.qtd_votos = qtd_votos
        self.perc_votos = perc_votos
        self.sf_e = sf_e
        self.sf_st = sf_st
        self.prev_perc_votos = prev_perc_votos
        self.distancia_votos = None
        self.viavel = None
        self.agr_id = None
        self.par_sg = None
        self.posicao_partido = None
        self.posicao_legenda = None
        self.cadeiras_proj = None
        self.dentro_proj = None
        self.legenda_sigla = None
        self.garantido = False
        self.eleito_mat = False
        self.garantido_turno = False
        self.eliminado_mat = False
        self.eliminado_definitivo = False
        self.margem_corte = None
        self.margem_folga = None
        self.restantes_legenda = None
        self.em_perigo = False
        self.nascimento = ""
        self.votos_para_maioria_1t = None

    def __gt__(self, other):
        return self.perc_votos < other.perc_votos

    def to_dict(self) -> dict:
        delta = self.perc_votos - self.prev_perc_votos
        return {
            "nome": self.nome,
            "qtd_votos": self.qtd_votos,
            "perc_votos": self.perc_votos,
            "delta_perc": delta if delta != 0 else None,
            "sf_e": self.sf_e,
            "sf_st": self.sf_st,
            "distancia_votos": self.distancia_votos,
            "viavel": self.viavel,
            "partido_sg": self.par_sg,
            "posicao_partido": self.posicao_partido,
            "posicao_legenda": self.posicao_legenda,
            "cadeiras_proj": self.cadeiras_proj,
            "dentro_proj": self.dentro_proj,
            "legenda_sigla": self.legenda_sigla,
            "garantido": self.garantido,
            "eleito_mat": self.eleito_mat,
            "garantido_turno": self.garantido_turno,
            "eliminado_mat": self.eliminado_mat,
            "eliminado_definitivo": self.eliminado_definitivo,
            "margem_corte": self.margem_corte,
            "margem_folga": self.margem_folga,
            "restantes_legenda": self.restantes_legenda,
            "em_perigo": self.em_perigo,
            "votos_para_maioria_1t": self.votos_para_maioria_1t,
        }


class EleicaoStats:
    def __init__(
        self,
        prev_stats,
        raw_data: dict,
        qtd_printable: int,
        title: str,
        panel_key: str,
    ):
        self._prev_stats = prev_stats
        self._raw_data = raw_data
        self._qtd_printable = qtd_printable
        self._title = title
        self._panel_key = panel_key
        self._filter_data()
        self._calc_aprox_votos_restantes()
        self._calc_proporcional()
        self._infer_mat_def()
        if self.segundo_turno:
            apply_garantido_segundo_turno(
                self.candidatos, self.aprox_votos_restantes, self.mat_def or ""
            )
        self._calc_distancia()
        self._calc_maioria_1t()

    def get_stat(self, key: str, custom_base: dict = None):
        base = self._raw_data if custom_base is None else custom_base
        value = base.get(key, "")
        if type(value) == str:
            value = value.replace(",", ".")
            try:
                value = float(value)
                if value == int(value):
                    value = int(value)
            except ValueError:
                return value
        return value

    def _gen_update_dt(self) -> datetime | None:
        dt_str = f"{self.get_stat('dt')} {self.get_stat('ht')}"
        try:
            naive = datetime.strptime(dt_str, "%d/%m/%Y %H:%M:%S")
            tz = tse_timezone_for_panel(self._panel_key)
            return naive.replace(tzinfo=tz)
        except Exception:
            return None

    def _filter_data(self):
        self.candidatos = []
        for cand in self.get_stat("cand"):
            item = Candidato(
                self.get_stat("nm", cand),
                self.get_stat("vap", cand),
                self.get_stat("pvap", cand),
                self.get_stat("e", cand),
                self.get_stat("st", cand),
                next(
                    (
                        prev_cand.perc_votos
                        for prev_cand in getattr(self._prev_stats, "candidatos", [])
                        if prev_cand.nome == self.get_stat("nm", cand)
                    ),
                    self.get_stat("pvap", cand),
                ),
            )
            item.agr_id = cand.get("_agr_id") or cand.get("agr_id")
            item.par_sg = cand.get("_par_sg") or cand.get("par_sg")
            item.nascimento = cand.get("dna") or cand.get("dn") or ""
            self.candidatos.append(item)
        self._agr_list = self.get_stat("agr") or []
        _, _, self.cargo_cd = resolve_panel(self._panel_key)
        if self.cargo_cd not in CARGOS_PROPORCIONAIS:
            self.candidatos.sort()
        self.qtd_vagas = self.get_stat("v")
        self.eleitorado = self.get_stat("e")
        self.qtd_sec_totalizadas = self.get_stat("st")
        self.perc_sec_totalizadas = self.get_stat("pst")
        self.perc_sec_pendentes = self.get_stat("psnt")
        self.latest_update_tse = self._gen_update_dt()
        mat_def = self.get_stat("md")
        self.mat_def = mat_def.upper() if isinstance(mat_def, str) and mat_def else mat_def
        self.qtd_votos_validos = self.get_stat("vv")
        self.majoritario = self.cargo_cd in CARGOS_MAJORITARIOS
        self.proporcional = self.cargo_cd in CARGOS_PROPORCIONAIS
        self.segundo_turno = self.cargo_cd in CARGOS_SEGUNDO_TURNO
        self.legendas_resumo = []

    def _calc_proporcional(self):
        if not self.proporcional or not self.candidatos:
            return
        self.legendas_resumo = apply_proporcional(
            self.candidatos,
            self._agr_list,
            int(self.qtd_vagas or 0),
            int(self.qtd_votos_validos or 0),
            self.aprox_votos_restantes,
            float(self.perc_sec_totalizadas or 0),
        )

    def _calc_aprox_votos_restantes(self):
        self.perc_comparecimento = self.get_stat("pc")
        if self.perc_sec_totalizadas and self.qtd_votos_validos:
            self.aprox_votos_restantes = int(
                self.qtd_votos_validos
                * self.perc_sec_pendentes
                / self.perc_sec_totalizadas
            )
        else:
            perc_voto_valido = self.get_stat("pvv")
            aprox_vv = int(
                self.perc_comparecimento
                / 100
                * perc_voto_valido
                / 100
                * self.eleitorado
            )
            self.aprox_votos_restantes = int(
                aprox_vv * self.perc_sec_pendentes / 100
            )

    def _calc_distancia(self):
        if not self.majoritario or not self.candidatos:
            return
        if self.segundo_turno:
            self._calc_distancia_segundo_turno()
            return
        if not self.qtd_vagas:
            return
        cand_lim = self.candidatos[self.qtd_vagas - 1]
        for cand in self.candidatos[self.qtd_vagas :]:
            cand.distancia_votos = cand_lim.qtd_votos - cand.qtd_votos
            cand.viavel = cand.distancia_votos <= self.aprox_votos_restantes

    def _calc_distancia_segundo_turno(self):
        if len(self.candidatos) < 2:
            return
        leader = self.candidatos[0]
        second = self.candidatos[1]
        restantes = max(0, int(self.aprox_votos_restantes or 0))
        mat_def = (self.mat_def or "").upper()

        leader.distancia_votos = None
        leader.viavel = None

        if mat_def == "S":
            second.distancia_votos = None
            second.viavel = None
        else:
            second.distancia_votos = leader.qtd_votos - second.qtd_votos
            second.viavel = second.distancia_votos <= restantes

        for cand in self.candidatos[2:]:
            cand.distancia_votos = second.qtd_votos - cand.qtd_votos
            cand.viavel = cand.distancia_votos <= restantes

        if mat_def == "S":
            for cand in self.candidatos[:2]:
                cand.distancia_votos = None
                cand.viavel = None

    def _calc_maioria_1t(self):
        self.maioria_1t = calc_maioria_1t(
            self.candidatos,
            self.aprox_votos_restantes,
            int(self.qtd_votos_validos or 0),
            segundo_turno=self.segundo_turno,
            mat_def=self.mat_def or "",
            apuracao_iniciada=self.perc_sec_totalizadas != 0,
        )
        if self.candidatos:
            self.candidatos[0].votos_para_maioria_1t = (
                self.maioria_1t["votos_necessarios"] if self.maioria_1t else None
            )

    def _infer_mat_def(self):
        if self.proporcional:
            if self.mat_def in ("", "N", "n", None):
                self.mat_def, _ = infer_mat_def_proporcional(
                    self.candidatos, int(self.qtd_vagas or 0)
                )
            return
        if not self.majoritario:
            return
        if not self.segundo_turno and self.mat_def in ("S", "s"):
            self.mat_def = ""
        if self.mat_def in ("", "N", "n", None):
            self.mat_def, _ = infer_mat_def(
                self.candidatos,
                self.aprox_votos_restantes,
                self.cargo_cd,
                int(self.qtd_vagas or 0),
                int(self.qtd_votos_validos or 0),
            )
        apply_mat_def(
            self.candidatos,
            self.mat_def,
            self.cargo_cd,
            int(self.qtd_vagas or 0),
        )

    def _mat_def_eleito_oficial(self) -> bool:
        if self.mat_def != "E" or not self.candidatos:
            return False
        if self.segundo_turno:
            return self.candidatos[0].sf_e == "e"
        qtd = int(self.qtd_vagas or 1)
        return all(cand.sf_e == "e" for cand in self.candidatos[:qtd])

    def _mat_def_label(self) -> str | None:
        if not self.mat_def or self.mat_def in ("N", "n"):
            return None
        if self.mat_def == "S":
            return "Segundo turno"
        if self.mat_def == "E":
            plural = not self.segundo_turno and (self.qtd_vagas or 0) > 1
            base = "Eleitos" if plural else "Eleito"
            if self._mat_def_eleito_oficial():
                return base
            return f"{base} (mat.)"
        return None

    def to_dict(self) -> dict:
        tse_delay = None
        tse_delay_human = None
        if self.latest_update_tse is not None:
            now = datetime.now(ZoneInfo(TZ_BRASILIA))
            ts = self.latest_update_tse
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=ZoneInfo(TZ_BRASILIA))
            tse_delay = int((now - ts).total_seconds())
            tse_delay_human = format_duration(tse_delay)

        filtered = (
            self.candidatos[: self._qtd_printable]
            if self._qtd_printable != -1
            else self.candidatos
        )

        return {
            "key": self._panel_key,
            "title": self._title,
            "perc_sec_totalizadas": self.perc_sec_totalizadas,
            "perc_comparecimento": self.perc_comparecimento,
            "aprox_votos_restantes": self.aprox_votos_restantes,
            "qtd_votos_validos": self.qtd_votos_validos,
            "latest_update_tse": (
                self.latest_update_tse.isoformat() if self.latest_update_tse else None
            ),
            "tse_delay_seconds": tse_delay,
            "tse_delay_human": tse_delay_human,
            "apuracao_iniciada": self.perc_sec_totalizadas != 0,
            "mat_def": self.mat_def,
            "mat_def_label": self._mat_def_label(),
            "majoritario": self.majoritario,
            "proporcional": self.proporcional,
            "segundo_turno": self.segundo_turno,
            "maioria_1t": self.maioria_1t,
            "legendas_resumo": self.legendas_resumo,
            "qtd_vagas": self.qtd_vagas,
            "qtd_candidatos": len(self.candidatos),
            "candidatos": [c.to_dict() for c in filtered],
            "updated_at": datetime.now().isoformat(),
        }


def fetch_eleicao_stats(prev_stats, panel_key: str, qtd_printable: int = 5):
    panel_key, _, cargo_cd = resolve_panel(panel_key)
    titulo, url, _ = build_url(panel_key)
    req = torequests.execute(url, "GET")
    if req["status"] != "ok":
        return None, f"requisição falhou: {req['status']}"
    try:
        payload = parse_response(req["req"].text)
        raw_data = normalize_payload(payload, cargo_cd)
    except Exception as exc:
        return None, f"erro ao processar resposta: {exc}"

    stats = EleicaoStats(prev_stats, raw_data, qtd_printable, titulo, panel_key)
    return stats, None
