from datetime import datetime

from extras import torequests
from extras.tse_client import build_url, normalize_payload, parse_response, resolve_panel


def format_duration(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None
    total = int(seconds)
    if total < 0:
        total = 0
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d{hours}h{minutes}m{secs}s"
    if hours:
        return f"{hours}h{minutes}m{secs}s"
    if minutes:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


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
        self.hp = None

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
            "hp": self.hp,
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
        self._calc_hp()

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
        self.candidatos = [
            Candidato(
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
            for cand in self.get_stat("cand")
        ]
        self.candidatos.sort()
        self.qtd_vagas = self.get_stat("v")
        self.eleitorado = self.get_stat("e")
        self.qtd_sec_totalizadas = self.get_stat("st")
        self.perc_sec_totalizadas = self.get_stat("pst")
        self.perc_sec_pendentes = self.get_stat("psnt")
        self.latest_update_tse = self._gen_update_dt()
        self.mat_def = self.get_stat("md")
        self.qtd_votos_validos = self.get_stat("vv")

    def _calc_hp(self):
        self.perc_comparecimento = self.get_stat("pc")
        self.perc_voto_valido = self.get_stat("pvv")
        self.aprox_vv_hipot = int(
            self.perc_comparecimento
            / 100
            * self.perc_voto_valido
            / 100
            * self.eleitorado
        )
        self.aprox_votos_restantes = int(
            self.aprox_vv_hipot * self.perc_sec_pendentes / 100
        )
        if not self.candidatos or not self.qtd_vagas:
            return
        cand_lim = self.candidatos[self.qtd_vagas - 1]
        for cand in self.candidatos[self.qtd_vagas :]:
            cand.hp = (cand.qtd_votos - cand_lim.qtd_votos) + self.aprox_votos_restantes

    def to_dict(self) -> dict:
        mat_labels = {"E": "Eleito", "S": "Segundo turno"}
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
            "mat_def_label": mat_labels.get(self.mat_def),
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
