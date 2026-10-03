import os
import threading
import time
from dataclasses import dataclass, field

from extras.eleicao import EleicaoStats, fetch_eleicao_stats
from extras.fixtures import MOCK_ENABLED, fetch_mock_panel, reset_mock_state
from extras.tse_client import resolve_panel

MIN_WAIT_SECONDS = 5
SESSION_TTL_SECONDS = int(os.environ.get("TSELIVESCORE_SESSION_TTL", "30"))


@dataclass
class PanelConfig:
    key: str
    printables: int = 5


@dataclass
class ClientSession:
    session_id: str
    panels: list[PanelConfig]
    wait: int
    last_seen: float = field(default_factory=time.time)


@dataclass
class PollerState:
    sessions: dict[str, ClientSession] = field(default_factory=dict)
    cache: dict[str, dict] = field(default_factory=dict)
    prev_stats: dict[str, EleicaoStats] = field(default_factory=dict)
    last_tse_poll_at: float | None = None
    last_tse_poll_panels: list[str] = field(default_factory=list)
    tse_poll_total: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class ElectionPoller:
    def __init__(self):
        self._state = PollerState()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def touch_session(
        self, session_id: str, panels: list[PanelConfig], wait: int
    ) -> dict:
        wait = max(wait, MIN_WAIT_SECONDS)
        with self._state.lock:
            merged_before = self._panel_signature(self._merged_panels_locked())
            self._state.sessions[session_id] = ClientSession(
                session_id=session_id,
                panels=panels,
                wait=wait,
                last_seen=time.time(),
            )
            session_panels = list(panels)
            merged_after_sig = self._panel_signature(self._merged_panels_locked())

        if merged_after_sig != merged_before:
            self.poll_now()

        return self._snapshot_for(session_panels)

    def end_session(self, session_id: str):
        with self._state.lock:
            self._state.sessions.pop(session_id, None)

    def reset_mock(self):
        if not MOCK_ENABLED:
            return
        reset_mock_state()
        with self._state.lock:
            self._state.cache.clear()
            self._state.prev_stats.clear()
            self._state.last_tse_poll_at = None
            self._state.last_tse_poll_panels = []
            self._state.tse_poll_total = 0
        panels = self._merged_panels()
        if panels:
            self.poll_now(panels)

    def get_snapshot_for(self, panels: list[PanelConfig]) -> dict:
        return self._snapshot_for(panels)

    def active_session_count(self) -> int:
        self._purge_stale_sessions()
        with self._state.lock:
            return len(self._state.sessions)

    def debug_status(self) -> dict:
        self._purge_stale_sessions()
        now = time.time()
        with self._state.lock:
            sessions = [
                {
                    "session_id": sid,
                    "panels": [
                        {"key": p.key, "printables": p.printables} for p in s.panels
                    ],
                    "wait": s.wait,
                    "last_seen_seconds_ago": round(now - s.last_seen, 1),
                }
                for sid, s in self._state.sessions.items()
            ]
            merged = self._merged_panels_locked()
            polled = [
                {
                    "key": key,
                    "printables": entry.get("printables"),
                    "candidatos_cached": len(entry.get("candidatos") or []),
                }
                for key, entry in self._state.cache.items()
            ]
            last_poll_at = self._state.last_tse_poll_at
            last_poll_panels = list(self._state.last_tse_poll_panels)
            poll_total = self._state.tse_poll_total

        tse_polling_active = bool(merged)
        return {
            "mock_enabled": MOCK_ENABLED,
            "tse_polling_active": tse_polling_active,
            "active_sessions": len(sessions),
            "sessions": sessions,
            "merged_panels": [
                {"key": p.key, "printables": p.printables} for p in merged
            ],
            "last_tse_poll_seconds_ago": (
                round(now - last_poll_at, 1) if last_poll_at is not None else None
            ),
            "last_tse_poll_panels": last_poll_panels,
            "tse_poll_total": poll_total,
            "cache": polled,
        }

    def poll_now(self, panels: list[PanelConfig] | None = None):
        if panels is None:
            panels = self._merged_panels()
        if not panels:
            return
        for panel in panels:
            self._poll_panel(panel)
        with self._state.lock:
            self._state.last_tse_poll_at = time.time()
            self._state.last_tse_poll_panels = [panel.key for panel in panels]
            self._state.tse_poll_total += len(panels)

    def _purge_stale_sessions(self):
        cutoff = time.time() - SESSION_TTL_SECONDS
        with self._state.lock:
            stale = [
                sid
                for sid, session in self._state.sessions.items()
                if session.last_seen < cutoff
            ]
            for sid in stale:
                del self._state.sessions[sid]

    def _active_sessions(self) -> list[ClientSession]:
        self._purge_stale_sessions()
        with self._state.lock:
            return list(self._state.sessions.values())

    def _merged_panels_locked(self) -> list[PanelConfig]:
        merged: dict[str, PanelConfig] = {}
        cutoff = time.time() - SESSION_TTL_SECONDS
        for session in self._state.sessions.values():
            if session.last_seen < cutoff:
                continue
            for panel in session.panels:
                current = merged.get(panel.key)
                if not current or panel.printables > current.printables:
                    merged[panel.key] = panel
        return list(merged.values())

    def _merged_panels(self) -> list[PanelConfig]:
        self._purge_stale_sessions()
        with self._state.lock:
            return self._merged_panels_locked()

    def _effective_wait(self) -> int:
        sessions = self._active_sessions()
        if not sessions:
            return MIN_WAIT_SECONDS
        return max(MIN_WAIT_SECONDS, min(session.wait for session in sessions))

    @staticmethod
    def _panel_signature(panels: list[PanelConfig]) -> tuple:
        return tuple((panel.key, panel.printables) for panel in panels)

    def _snapshot_for(self, panels: list[PanelConfig]) -> dict:
        with self._state.lock:
            cache = dict(self._state.cache)
        return {
            panel.key: self._slice_entry(cache.get(panel.key), panel.printables)
            for panel in panels
        }

    @staticmethod
    def _slice_entry(entry: dict | None, printables: int) -> dict | None:
        if entry is None:
            return None
        sliced = dict(entry)
        sliced["printables"] = printables
        candidatos = entry.get("candidatos")
        if candidatos is not None:
            sliced["candidatos"] = candidatos[:printables]
        return sliced

    def _poll_panel(self, panel: PanelConfig):
        panel_key, _, _ = resolve_panel(panel.key)
        if MOCK_ENABLED:
            with self._state.lock:
                prev_cache = self._state.cache.get(panel_key)
            entry = fetch_mock_panel(panel_key, panel.printables, prev_cache)
            with self._state.lock:
                self._state.cache[panel_key] = entry
            return

        with self._state.lock:
            prev = self._state.prev_stats.get(panel_key)

        stats, error = fetch_eleicao_stats(prev, panel_key, panel.printables)
        entry = {
            "key": panel_key,
            "printables": panel.printables,
            "error": error,
        }

        if stats is not None:
            entry.update(stats.to_dict())
            with self._state.lock:
                self._state.prev_stats[panel_key] = stats

        with self._state.lock:
            self._state.cache[panel_key] = entry

    def _loop(self):
        while True:
            panels = self._merged_panels()
            if not panels:
                time.sleep(1)
                continue

            wait = self._effective_wait()
            self.poll_now(panels)
            time.sleep(wait)
