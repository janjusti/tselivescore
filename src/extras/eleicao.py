from datetime import datetime

from extras import torequests
from extras.proporcional import apply_proporcional
from extras.tse_client import (
    CARGOS_MAJORITARIOS,
    CARGOS_PROPORCIONAIS,
    CARGOS_SEGUNDO_TURNO,
    build_url,
    normalize_payload,
    parse_response,
    resolve_panel,
)


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


def infer_mat_def_segundo_turno(candidatos, aprox_votos_restantes) -> tuple[str, str | None]:
    """Presidente/governador: maioria absoluta ou 2º turno."""
    if not candidatos or len(candidatos) < 2:
        return "", None

    restantes = max(0, int(aprox_votos_restantes or 0))
    leader, second = candidatos[0], candidatos[1]
    gap_lider_2o = _cand_votos(leader) - _cand_votos(second)
    segundo_nao_alcanca = gap_lider_2o > restantes

    if _cand_perc(leader) > 50 and segundo_nao_alcanca:
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
    candidatos, aprox_votos_restantes, cargo_cd: str, qtd_vagas: int
) -> tuple[str, str | None]:
    if cargo_cd in CARGOS_SEGUNDO_TURNO:
        return infer_mat_def_segundo_turno(candidatos, aprox_votos_restantes)
    if cargo_cd in CARGOS_MAJORITARIOS:
        return infer_mat_def_plurality(candidatos, aprox_votos_restantes, qtd_vagas)
    return "", None


# Compat: nome antigo usado em testes/fixtures legados.
infer_mat_def_majoritario = infer_mat_def_segundo_turno


def _set_sf_e(cand, value: str) -> None:
    sf_e = cand.sf_e if hasattr(cand, "sf_e") else cand["sf_e"]
    if sf_e in ("n", "", None):
        if hasattr(cand, "sf_e"):
            cand.sf_e = value
        else:
            cand["sf_e"] = value


def apply_mat_def_segundo_turno(candidatos, mat_def: str) -> str:
    if not candidatos or not mat_def:
        return mat_def
    leader = candidatos[0]
    if mat_def == "E":
        _set_sf_e(leader, "e")
    elif mat_def == "S":
        _set_sf_e(leader, "s")
    return mat_def


def apply_mat_def_plurality(candidatos, mat_def: str, qtd_vagas: int) -> str:
    if not candidatos or not mat_def or mat_def != "E" or qtd_vagas <= 0:
        return mat_def
    for cand in candidatos[:qtd_vagas]:
        _set_sf_e(cand, "e")
    return mat_def


def apply_mat_def(candidatos, mat_def: str, cargo_cd: str, qtd_vagas: int) -> str:
    if cargo_cd in CARGOS_SEGUNDO_TURNO:
        return apply_mat_def_segundo_turno(candidatos, mat_def)
    if cargo_cd in CARGOS_MAJORITARIOS:
        return apply_mat_def_plurality(candidatos, mat_def, qtd_vagas)
    return mat_def


apply_mat_def_majoritario = apply_mat_def_segundo_turno


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
        self.eliminado_mat = False
        self.margem_corte = None
        self.margem_folga = None
        self.restantes_legenda = None
        self.em_perigo = False
        self.nascimento = ""

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
            "eliminado_mat": self.eliminado_mat,
            "margem_corte": self.margem_corte,
            "margem_folga": self.margem_folga,
            "restantes_legenda": self.restantes_legenda,
            "em_perigo": self.em_perigo,
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
        self._calc_distancia()
        self._calc_proporcional()
        self._infer_mat_def()

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
            return datetime.strptime(dt_str, "%d/%m/%Y %H:%M:%S")
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
        self.mat_def = self.get_stat("md")
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
        if not self.majoritario or not self.candidatos or not self.qtd_vagas:
            return
        cand_lim = self.candidatos[self.qtd_vagas - 1]
        for cand in self.candidatos[self.qtd_vagas :]:
            cand.distancia_votos = cand_lim.qtd_votos - cand.qtd_votos
            cand.viavel = cand.distancia_votos <= self.aprox_votos_restantes

    def _infer_mat_def(self):
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
            )
        apply_mat_def(
            self.candidatos,
            self.mat_def,
            self.cargo_cd,
            int(self.qtd_vagas or 0),
        )

    def _mat_def_label(self) -> str | None:
        if not self.mat_def or self.mat_def in ("N", "n"):
            return None
        if self.mat_def == "S":
            return "Segundo turno"
        if self.mat_def == "E":
            if not self.segundo_turno and (self.qtd_vagas or 0) > 1:
                return "Eleitos"
            return "Eleito"
        return None

    def to_dict(self) -> dict:
        tse_delay = None
        tse_delay_human = None
        if self.latest_update_tse is not None:
            tse_delay = int((datetime.now() - self.latest_update_tse).total_seconds())
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
            "legendas_resumo": self.legendas_resumo,
            "qtd_vagas": self.qtd_vagas,
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
