import threading
import time
import unittest

from extras.eleicao import (
    candidatos_for_track,
    entry_fingerprint,
)
from extras.poller import ElectionPoller, PanelConfig, _slice_entry


class TestPollerSnapshot(unittest.TestCase):
    def test_slice_track_somente_relevantes_fora_do_printables(self):
        candidatos = [
            {"nome": "A", "perc_votos": 10.0, "sf_e": "n"},
            {"nome": "B", "perc_votos": 9.0, "sf_e": "n"},
            {"nome": "C", "perc_votos": 8.0, "sf_e": "n"},
            {"nome": "D", "perc_votos": 1.0, "sf_e": "n", "dentro_proj": True},
        ]
        entry = {"candidatos": candidatos, "title": "Teste"}
        sliced = _slice_entry(entry, 2)
        self.assertEqual(len(sliced["candidatos"]), 2)
        self.assertEqual(len(sliced["candidatos_track"]), 1)
        self.assertEqual(sliced["candidatos_track"][0]["nome"], "D")
        self.assertTrue(sliced["candidatos_track"][0]["dentro_proj"])

    def test_track_ignora_rabo_irrelevante_em_lista_grande(self):
        candidatos = [
            {"nome": f"Cand {i}", "perc_votos": 0.01, "sf_e": "n"}
            for i in range(200)
        ]
        candidatos[150]["dentro_proj"] = True
        track = candidatos_for_track(candidatos, 12)
        self.assertEqual(len(track), 1)
        self.assertEqual(track[0]["nome"], "Cand 150")

    def test_eliminado_so_nao_entra_no_track(self):
        candidatos = [
            {"nome": f"Cand {i}", "perc_votos": 0.01, "sf_e": "n"}
            for i in range(100)
        ]
        candidatos[50]["eliminado_mat"] = True
        candidatos[50]["eliminado_definitivo"] = True
        track = candidatos_for_track(candidatos, 5)
        self.assertEqual(track, [])

    def test_snapshot_omite_painel_inalterado(self):
        poller = ElectionPoller()
        panel = PanelConfig(key="br:1", printables=4)
        entry = {
            "key": "br:1",
            "perc_sec_totalizadas": 50.0,
            "candidatos": [{"nome": "A", "qtd_votos": 1, "perc_votos": 50.0, "sf_e": "n"}],
            "legendas_resumo": [],
        }
        entry["_rev"] = entry_fingerprint(entry)
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
        self.assertNotEqual(entry_fingerprint(a), entry_fingerprint(b))

    def test_touch_session_nao_bloqueia_com_cache_fresco(self):
        poller = ElectionPoller()
        panel = PanelConfig(key="br:1", printables=4)
        entry = {
            "key": "br:1",
            "perc_sec_totalizadas": 50.0,
            "candidatos": [{"nome": "A", "qtd_votos": 1, "perc_votos": 50.0, "sf_e": "n"}],
            "legendas_resumo": [],
        }
        entry["_rev"] = entry_fingerprint(entry)
        poller._state.cache["br:1"] = entry
        poller._state.last_tse_poll_at = time.time()

        poll_calls = []
        poller.poll_now = lambda *args, **kwargs: poll_calls.append(1)

        snapshot, _ = poller.touch_session("s1", [panel], 10)
        self.assertIn("br:1", snapshot)
        self.assertEqual(poll_calls, [])
        time.sleep(0.15)
        self.assertEqual(poll_calls, [])

    def test_touch_session_retorna_antes_do_poll(self):
        poller = ElectionPoller()
        panel = PanelConfig(key="br:1", printables=4)
        returned = threading.Event()
        poll_ran = threading.Event()

        def slow_poll(*args, **kwargs):
            poll_ran.set()
            if not returned.wait(timeout=1):
                raise AssertionError("poll bloqueou a resposta do heartbeat")

        poller.poll_now = slow_poll

        snapshot, _ = poller.touch_session("s1", [panel], 10)
        self.assertIsNone(snapshot.get("br:1"))
        returned.set()
        self.assertTrue(poll_ran.wait(timeout=1))

    def test_fingerprint_ignora_mudanca_profunda_irrelevante(self):
        base = {
            "perc_sec_totalizadas": 50.0,
            "candidatos": [
                {"nome": f"Top {i}", "qtd_votos": 1000 - i, "perc_votos": 1.0, "sf_e": "n"}
                for i in range(60)
            ],
        }
        changed = {
            **base,
            "candidatos": [
                *base["candidatos"][:50],
                {"nome": "Deep", "qtd_votos": 1, "perc_votos": 0.01, "sf_e": "n"},
                *base["candidatos"][51:],
            ],
        }
        self.assertEqual(entry_fingerprint(base), entry_fingerprint(changed))


if __name__ == "__main__":
    unittest.main()
