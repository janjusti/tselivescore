import os
import threading
import time
from dataclasses import dataclass, field

from extras.eleicao import (
    EleicaoStats,
    candidatos_for_track,
    candidatos_para_exibicao,
    candidatos_track_payload,
    entry_fingerprint,
    fetch_eleicao_stats,
)
from extras.fixtures import MOCK_ENABLED, fetch_mock_panel, reset_mock_state
from extras.tse_client import resolve_panel

MIN_WAIT_SECONDS = 5
SESSION_TTL_SECONDS = int(os.environ.get("TSELIVESCORE_SESSION_TTL", "30"))


@dataclass
class PanelConfig:
    key: str
    printables: int = 5
    dispute_only: bool = False
    collapse_garantidos: bool = True


def _slice_entry(entry: dict | None, panel: PanelConfig) -> dict | None:
    if entry is None:
        return None
    sliced = dict(entry)
    sliced.pop("_rev", None)
    sliced["printables"] = panel.printables
    sliced["dispute_only"] = panel.dispute_only
    sliced["collapse_garantidos"] = panel.collapse_garantidos
    candidatos = entry.get("candidatos")
    if candidatos is not None:
        sliced["candidatos"] = candidatos_para_exibicao(
            candidatos,
            panel.printables,
            proporcional=bool(entry.get("proporcional")),
            dispute_only=panel.dispute_only,
            collapse_garantidos=panel.collapse_garantidos,
        )
        track_src = candidatos_for_track(candidatos, panel.printables)
        sliced["candidatos_track"] = (
            candidatos_track_payload(track_src) if track_src else []
        )
    return sliced


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
    mock_tick: int = 0
    last_tse_poll_at: float | None = None
    last_tse_poll_panels: list[str] = field(default_factory=list)
    tse_poll_total: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class ElectionPoller:
    def __init__(self):
        self._state = PollerState()
        self._poll_lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def touch_session(
        self,
        session_id: str,
        panels: list[PanelConfig],
        wait: int,
        client_revs: dict[str, int] | None = None,
    ) -> tuple[dict, dict[str, int]]:
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

        if merged_after_sig != merged_before and self._needs_poll(session_panels):
            self._schedule_poll()

        return self._snapshot_for(session_panels, client_revs)

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
            self._state.mock_tick = 0
            self._state.last_tse_poll_at = None
            self._state.last_tse_poll_panels = []
            self._state.tse_poll_total = 0
        panels = self._merged_panels()
        if panels:
            self.poll_now(panels)

    def get_snapshot_for(self, panels: list[PanelConfig]) -> dict:
        panels_out, _ = self._snapshot_for(panels)
        return panels_out

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
        if not self._poll_lock.acquire(blocking=False):
            return
        try:
            if panels is None:
                panels = self._merged_panels()
            if not panels:
                return
            mock_tick = 0
            if MOCK_ENABLED:
                with self._state.lock:
                    self._state.mock_tick += 1
                    mock_tick = self._state.mock_tick
            for panel in panels:
                self._poll_panel(panel, mock_tick=mock_tick)
            with self._state.lock:
                self._state.last_tse_poll_at = time.time()
                self._state.last_tse_poll_panels = [panel.key for panel in panels]
                self._state.tse_poll_total += len(panels)
        finally:
            self._poll_lock.release()

    def _needs_poll(self, panels: list[PanelConfig]) -> bool:
        with self._state.lock:
            cache = self._state.cache
            last_poll_at = self._state.last_tse_poll_at
        for panel in panels:
            if panel.key not in cache:
                return True
        if last_poll_at is None:
            return True
        return time.time() - last_poll_at >= self._effective_wait()

    def _schedule_poll(self):
        def run():
            panels = self._merged_panels()
            if panels:
                self.poll_now(panels)

        threading.Thread(target=run, daemon=True).start()

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

    def _snapshot_for(
        self, panels: list[PanelConfig], client_revs: dict[str, int] | None = None
    ) -> tuple[dict, dict[str, int]]:
        client_revs = client_revs or {}
        with self._state.lock:
            cache = dict(self._state.cache)
        panels_out: dict = {}
        revs_out: dict[str, int] = {}
        for panel in panels:
            entry = cache.get(panel.key)
            content_rev = (entry or {}).get("_rev", 0)
            revs_out[panel.key] = content_rev
            if entry is not None and client_revs.get(panel.key) == content_rev:
                continue
            panels_out[panel.key] = _slice_entry(entry, panel)
        return panels_out, revs_out

    def _poll_panel(self, panel: PanelConfig, mock_tick: int = 0):
        panel_key, _, _ = resolve_panel(panel.key)
        if MOCK_ENABLED:
            with self._state.lock:
                prev_cache = self._state.cache.get(panel_key)
            entry = fetch_mock_panel(panel_key, prev_cache, mock_tick)
            entry["_rev"] = entry_fingerprint(entry)
            with self._state.lock:
                self._state.cache[panel_key] = entry
            return

        with self._state.lock:
            prev = self._state.prev_stats.get(panel_key)

        stats, error = fetch_eleicao_stats(prev, panel_key, -1)
        entry = {
            "key": panel_key,
            "error": error,
        }

        if stats is not None:
            entry.update(stats.to_dict())
            with self._state.lock:
                self._state.prev_stats[panel_key] = stats

        entry["_rev"] = entry_fingerprint(entry)
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
