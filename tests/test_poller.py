import unittest

from extras.poller import ElectionPoller, PanelConfig, _entry_fingerprint, _slice_entry


class TestPollerSnapshot(unittest.TestCase):
    def test_slice_track_somente_fora_do_printables(self):
        candidatos = [
            {"nome": "A", "perc_votos": 10.0, "sf_e": "n", "garantido": False},
            {"nome": "B", "perc_votos": 9.0, "sf_e": "n", "garantido": False},
            {"nome": "C", "perc_votos": 8.0, "sf_e": "n", "garantido": False},
        ]
        entry = {"candidatos": candidatos, "title": "Teste"}
        sliced = _slice_entry(entry, 2)
        self.assertEqual(len(sliced["candidatos"]), 2)
        self.assertEqual(sliced["candidatos"][0]["nome"], "A")
        self.assertEqual(len(sliced["candidatos_track"]), 1)
        self.assertEqual(sliced["candidatos_track"][0]["nome"], "C")
        self.assertEqual(_slice_entry(entry, 3)["candidatos_track"], [])

    def test_snapshot_omite_painel_inalterado(self):
        poller = ElectionPoller()
        panel = PanelConfig(key="br:1", printables=4)
        entry = {
            "key": "br:1",
            "perc_sec_totalizadas": 50.0,
            "candidatos": [{"nome": "A", "qtd_votos": 1, "perc_votos": 50.0, "sf_e": "n"}],
            "legendas_resumo": [],
        }
        entry["_rev"] = _entry_fingerprint(entry)
        poller._state.cache["br:1"] = entry

        full, _ = poller._snapshot_for([panel])
        self.assertIn("br:1", full)

        delta, revs = poller._snapshot_for([panel], {panel.key: entry["_rev"]})
        self.assertEqual(delta, {})
        self.assertEqual(revs["br:1"], entry["_rev"])

    def test_fingerprint_muda_com_votos(self):
        a = {
            "perc_sec_totalizadas": 50.0,
            "candidatos": [{"nome": "A", "qtd_votos": 100, "perc_votos": 50.0, "sf_e": "n"}],
        }
        b = {
            "perc_sec_totalizadas": 51.0,
            "candidatos": [{"nome": "A", "qtd_votos": 110, "perc_votos": 51.0, "sf_e": "n"}],
        }
        self.assertNotEqual(_entry_fingerprint(a), _entry_fingerprint(b))


if __name__ == "__main__":
    unittest.main()
