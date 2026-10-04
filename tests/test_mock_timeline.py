import unittest

from extras.fixtures import fetch_mock_panel, reset_mock_state


def _track(cand, idx, qtd_vagas, is_majoritario):
    return {
        "sf_e": cand.get("sf_e") or "n",
        "garantido": bool(cand.get("garantido")),
        "eliminado_mat": bool(cand.get("eliminado_mat")),
        "eliminado_definitivo": bool(cand.get("eliminado_definitivo")),
        "viavel": cand.get("viavel"),
        "dentro_proj": cand.get("dentro_proj"),
        "below_cutoff": is_majoritario and idx >= qtd_vagas,
    }


def _detect_events(prev_entry, entry):
    events = []
    data = entry
    prev = prev_entry
    if not prev:
        return events

    is_prop = bool(data.get("proporcional"))
    is_maj = bool(data.get("majoritario"))
    segundo_turno = bool(data.get("segundo_turno"))
    qtd_vagas = int(data.get("qtd_vagas") or 1)

    md = data.get("mat_def") or ""
    prev_md = prev.get("mat_def") or ""
    if md and md != prev_md and data.get("mat_def_label"):
        events.append(("mat_def", data.get("title"), data.get("mat_def_label")))

    prev_map = {c["nome"]: _track(c, i, qtd_vagas, is_maj) for i, c in enumerate(prev["candidatos"])}
    saiu, entrou = [], []
    for idx, cand in enumerate(data["candidatos"]):
        snap = _track(cand, idx, qtd_vagas, is_maj)
        prev_snap = prev_map.get(cand["nome"])
        if not prev_snap:
            continue
        was_g = prev_snap["garantido"]
        now_g = snap["garantido"]
        was_e = (prev_snap["sf_e"] == "s" if is_prop else prev_snap["sf_e"] == "e")
        now_e = (snap["sf_e"] == "s" if is_prop else snap["sf_e"] == "e")
        if not was_g and now_g and not now_e:
            events.append(("eleito_mat", cand["nome"]))
        if not was_e and now_e:
            events.append(("eleito", cand["nome"]))
        if segundo_turno and prev_snap["sf_e"] != "s" and snap["sf_e"] == "s":
            events.append(("segundo_turno", cand["nome"]))
        was_elim = (
            (
                is_prop
                and prev_snap["sf_e"] == "n"
                and (prev_snap["eliminado_mat"] or prev_snap["eliminado_definitivo"])
            )
            or (is_maj and prev_snap["below_cutoff"] and prev_snap["viavel"] is False)
        )
        now_elim = (
            (
                is_prop
                and snap["sf_e"] == "n"
                and (snap["eliminado_mat"] or snap["eliminado_definitivo"])
            )
            or (is_maj and snap["below_cutoff"] and snap["viavel"] is False)
        )
        was_elim_def = is_prop and prev_snap["eliminado_definitivo"]
        now_elim_def = is_prop and snap["eliminado_definitivo"]
        if not was_elim_def and now_elim_def:
            events.append(("eliminado_def_prop", cand["nome"]))
        elif not was_elim and now_elim and is_prop and not now_elim_def:
            events.append(("eliminado_mat_prop", cand["nome"]))
        elif not was_elim and now_elim and not is_prop:
            events.append(("eliminado_mat_maj", cand["nome"]))
        if is_prop:
            leg = cand.get("legenda_sigla") or cand.get("par_sg") or ""
            if prev_snap["dentro_proj"] is True and snap["dentro_proj"] is False:
                saiu.append((cand["nome"], leg))
            elif prev_snap["dentro_proj"] is False and snap["dentro_proj"] is True:
                entrou.append((cand["nome"], leg))

    losers = list(saiu)
    winners = list(entrou)
    for i in range(len(losers) - 1, -1, -1):
        loser = losers[i]
        for j, winner in enumerate(winners):
            if loser[1] and loser[1] == winner[1]:
                events.append(("cadeira_troca", f"{loser[0]} → {winner[0]}"))
                winners.pop(j)
                losers.pop(i)
                break
    while losers and winners:
        loser = losers.pop(0)
        winner = winners.pop(0)
        events.append(("cadeira_troca", f"{loser[0]} → {winner[0]}"))

    return events


class TestMockTimeline(unittest.TestCase):
    PANELS = ("br:1", "rn:3", "rn:5", "rn:6")

    def setUp(self):
        reset_mock_state()

    def test_zero_porcento_tudo_zerado(self):
        for key in self.PANELS:
            entry = fetch_mock_panel(key, None, 1)
            self.assertEqual(entry["perc_sec_totalizadas"], 0.0)
            self.assertFalse(entry["apuracao_iniciada"])
            for cand in entry["candidatos"]:
                self.assertEqual(cand["qtd_votos"], 0)
                self.assertEqual(cand["perc_votos"], 0.0)
            if key == "rn:6":
                self.assertFalse(entry.get("legendas_resumo"))

    def test_nao_eleitos_em_100_tem_eliminado_definitivo(self):
        prev = None
        for tick in range(1, 38):
            prev = fetch_mock_panel("rn:6", prev, tick)
        for cand in prev["candidatos"]:
            if cand.get("sf_e") != "s":
                self.assertTrue(
                    cand.get("eliminado_definitivo"),
                    f"{cand['nome']} deveria estar eliminado_definitivo em 100%",
                )
                self.assertFalse(cand.get("eliminado_mat"))

    def test_congela_em_100_porcento(self):
        prev = None
        last_pct = None
        frozen_vv = None
        for tick in range(1, 45):
            entry = fetch_mock_panel("rn:6", prev, tick)
            prev = entry
            last_pct = entry["perc_sec_totalizadas"]
            if tick == 37:
                frozen_vv = entry["candidatos"][0]["qtd_votos"]
        self.assertEqual(last_pct, 100.0)
        entry38 = fetch_mock_panel("rn:6", prev, 38)
        self.assertEqual(entry38["candidatos"][0]["qtd_votos"], frozen_vv)
        self.assertEqual(entry38["mock_tick"], 37)

    def test_roteiro_cobre_todos_os_eventos(self):
        expected = {
            "cadeira_troca",
            "eleito_mat",
            "eleito",
            "segundo_turno",
            "eliminado_mat_prop",
            "eliminado_def_prop",
            "eliminado_mat_maj",
            "mat_def",
        }
        seen = set()
        prev_by_panel = {key: None for key in self.PANELS}
        for tick in range(2, 38):
            for key in self.PANELS:
                entry = fetch_mock_panel(key, prev_by_panel[key], tick)
                for ev in _detect_events(prev_by_panel[key], entry):
                    seen.add(ev[0])
                prev_by_panel[key] = entry

        missing = expected - seen
        self.assertFalse(
            missing,
            f"Eventos não disparados no roteiro: {missing}. Vistos: {sorted(seen)}",
        )


if __name__ == "__main__":
    unittest.main()
