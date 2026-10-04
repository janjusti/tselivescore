import argparse
from datetime import datetime
import os
from time import sleep

from extras.eleicao import EleicaoStats, fetch_eleicao_stats, format_duration
from extras.tse_client import build_url, normalize_panel_key


def format_cli(stats: EleicaoStats, qtd_printable: int) -> str:
    os.system("clear")
    s = f"{stats._title} - {stats.perc_sec_totalizadas}% apurado\n"
    if stats.perc_sec_totalizadas != 0:
        s += (
            f"[Comparecimento: {stats.perc_comparecimento}% | "
            f"Votos restantes: ~{stats.aprox_votos_restantes:,}]\n"
        )
    if stats.latest_update_tse is not None:
        tse_delta_dt = datetime.now() - stats.latest_update_tse
        delay = format_duration(tse_delta_dt.total_seconds())
        s += f"Atualizado: {stats.latest_update_tse} (há {delay})\n"
    else:
        s += "Apuração ainda não iniciada.\n"
    if stats.mat_def != "" and stats.mat_def != "N":
        label = stats._mat_def_label()
        if label:
            s += f"\n[Matematicamente definido: {label}]\n\n"
    filtered_cands = (
        stats.candidatos[:qtd_printable]
        if qtd_printable != -1
        else stats.candidatos
    )
    for idx, cand in enumerate(filtered_cands):
        if idx == stats.qtd_vagas:
            s += "---------------\n"
        if cand.sf_e != "n":
            s += f"[E: {cand.sf_e}] "
        if cand.sf_st != "":
            s += f"[ST: {cand.sf_st}] "
        s += f"{cand.nome} -> {cand.qtd_votos:,} votos válidos ({cand.perc_votos}"
        delta_perc_votos = cand.perc_votos - cand.prev_perc_votos
        s += f"%{f' | {delta_perc_votos:+.2f}%' if delta_perc_votos != 0 else ''})"
        if stats.majoritario and cand.distancia_votos is not None:
            s += f" [Dist: {cand.distancia_votos:,}]"
            if cand.viavel is False:
                s += " (eliminado)"
        elif stats.proporcional and cand.par_sg and cand.posicao_partido is not None:
            s += f" [{cand.par_sg} {cand.posicao_partido}º"
            if cand.cadeiras_proj is not None:
                s += f", {cand.cadeiras_proj} proj."
            if cand.garantido:
                s += ", garantido"
            elif cand.eliminado_mat:
                s += ", eliminado"
            elif cand.dentro_proj is False:
                s += ", fora"
            if cand.margem_corte is not None:
                sign = "+" if cand.margem_folga else "-"
                s += f", margem {sign}{cand.margem_corte:,}"
            s += "]"
        s += "\n"
    return s


class Eleicao:
    def __init__(
        self,
        title: str,
        panel_key: str,
        wait_time: int,
        qtd_printable: int,
    ):
        self.title = title
        self.panel_key = panel_key
        self.wait_time = max(wait_time, 5)
        self.qtd_printable = qtd_printable
        self.eleicao_stats = None
        self.verificador()

    def verificador(self):
        while True:
            self.update_eleicao()
            sleep(self.wait_time)

    def update_eleicao(self):
        stats, error = fetch_eleicao_stats(
            self.eleicao_stats, self.panel_key, self.qtd_printable
        )
        if error:
            print(self.eleicao_stats)
            print(f"({datetime.now()}) Algo deu ruim: {error}")
            return
        if (
            stats.qtd_sec_totalizadas
            != getattr(self.eleicao_stats, "qtd_sec_totalizadas", 0)
            or stats.qtd_sec_totalizadas == 0
        ):
            print(format_cli(stats, self.qtd_printable))
            self.eleicao_stats = stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "cod",
        help="Digite 'br' para Presidência ou '<estado>' (e.g. sp) para Governo do Estado.",
    )
    parser.add_argument(
        "--wait",
        default=5,
        help="Tempo para aguardar entre requisições (mínimo 5).",
        type=int,
    )
    parser.add_argument(
        "--printables", default=5, help="Quantidade de candidatos a exibir.", type=int
    )
    args = parser.parse_args()
    panel_key = normalize_panel_key(args.cod.lower())
    titulo, _, _ = build_url(panel_key)
    print(f"Iniciando no modo '{titulo}'...")
    Eleicao(titulo, panel_key, args.wait, args.printables)
