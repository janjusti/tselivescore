import argparse
from datetime import datetime
import json
import os
from time import sleep

from extras import torequests


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


class EleicaoStats:
    def __init__(self, prev_stats, raw_data: dict, qtd_printable: int, title: str):
        self._prev_stats = prev_stats
        self._raw_data = raw_data
        self._qtd_printable = qtd_printable
        self._title = title
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

    def _gen_update_dt(self) -> datetime:
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
        cand_lim = self.candidatos[self.qtd_vagas - 1]
        for cand in self.candidatos[self.qtd_vagas :]:
            cand.hp = (cand.qtd_votos - cand_lim.qtd_votos) + self.aprox_votos_restantes

    def __repr__(self) -> str:
        os.system("clear")
        s = f"{self._title} - {self.perc_sec_totalizadas}% apurado\n"
        if self.perc_sec_totalizadas != 0:
            s += f"[Comparecimento: {self.perc_comparecimento}% | Votos restantes: ~{self.aprox_votos_restantes:,}]\n"
        if self.latest_update_tse is not None:
            tse_delta_dt = datetime.now() - self.latest_update_tse
            s += f"Atualizado: {self.latest_update_tse} (atraso de {tse_delta_dt.seconds} segundos)\n"
        else:
            s += "Apuração ainda não iniciada.\n"
        if self.mat_def != "" and self.mat_def != "N":
            msg = {"E": "Eleito", "S": "Segundo turno"}
            s += f"\n[Matematicamente definido: {msg[self.mat_def]}]\n\n"
        filtered_cands = (
            self.candidatos[: self._qtd_printable]
            if self._qtd_printable != -1
            else self.candidatos
        )
        for idx, cand in enumerate(filtered_cands):
            if idx == self.qtd_vagas:
                s += "---------------\n"
            if cand.sf_e != "n":
                s += f"[E: {cand.sf_e}] "
            if cand.sf_st != "":
                s += f"[ST: {cand.sf_st}] "
            s += f"{cand.nome} -> {cand.qtd_votos:,} votos válidos ({cand.perc_votos}"
            delta_perc_votos = cand.perc_votos - cand.prev_perc_votos
            s += f"%{f' | {delta_perc_votos:+.2f}%' if delta_perc_votos != 0 else ''})"
            if cand.hp is not None and cand.hp >= 0:
                s += f" [HP: {f'{cand.hp:,}'}]"
            s += "\n"
        return s


class Eleicao:
    def __init__(self, title: str, url: str, wait_time: int, qtd_printable: int):
        self.title = title
        self.url = url
        self.wait_time = wait_time
        self.qtd_printable = qtd_printable
        self.eleicao_stats = None
        self.verificador()

    def verificador(self):
        while True:
            self.update_eleicao()
            sleep(self.wait_time)

    def update_eleicao(self):
        req = torequests.execute(self.url, "GET")
        if req["status"] == "ok":
            try:
                raw_data = json.loads(req["req"].text)
            except Exception:
                print(self.eleicao_stats)
                print(f"({datetime.now()}) Algo deu ruim: {req['req'].text[:100]}")
                return
            if (
                raw_data["st"]
                != str(getattr(self.eleicao_stats, "qtd_sec_totalizadas", 0))
                or raw_data["st"] == "0"
            ):
                curr_elec_stats = EleicaoStats(
                    self.eleicao_stats, raw_data, self.qtd_printable, self.title
                )
                print(curr_elec_stats)
                self.eleicao_stats = curr_elec_stats
        else:
            print(self.eleicao_stats)
            print(f"({datetime.now()}) Req deu ruim: {req['status']}")
            return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "cod",
        help="Digite 'br' para Presidência ou '<estado>' (e.g. sp) para Governo do Estado.",
    )
    parser.add_argument(
        "--wait", default=5, help="Tempo para aguardar entre requisições.", type=int
    )
    parser.add_argument(
        "--printables", default=5, help="Quantidade de candidatos a exibir.", type=int
    )
    args = parser.parse_args()
    selected_code = args.cod
    if selected_code == "br":
        titulo = "Presidência"
        url = "https://resultados.tse.jus.br/oficial/ele2022/545/dados-simplificados/br/br-c0001-e000545-r.json"
    else:
        titulo = f"Governo {selected_code.upper()}"
        url = f"https://resultados.tse.jus.br/oficial/ele2022/547/dados-simplificados/{selected_code}/{selected_code}-c0003-e000547-r.json"
    print(f"Iniciando no modo '{titulo}'...")
    Eleicao(titulo, url, args.wait, args.printables)
