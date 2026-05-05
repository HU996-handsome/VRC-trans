"""
VRChat OSC listener.
Listens for avatar parameter changes (e.g., mute state).
"""
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class OSCListener:
    """Listens for VRChat OSC messages (avatar parameters)."""

    def __init__(self, port: int = 9001, on_mute_change: Optional[Callable[[bool], None]] = None):
        self.port = port
        self.on_mute_change = on_mute_change

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._is_muted = False

    @property
    def is_muted(self) -> bool:
        return self._is_muted

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info(f"OSC listener started on port {self.port}")

    def stop(self):
        self._running = False
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        logger.info("OSC listener stopped")

    def _listen_loop(self):
        try:
            from pythonosc import dispatcher, osc_server

            disp = dispatcher.Dispatcher()
            disp.map("/avatar/parameters/MuteSelf", self._handle_mute)
            disp.map("/avatar/parameters/*", self._handle_avatar_param)

            self._server = osc_server.ThreadingOSCUDPServer(
                ("127.0.0.1", self.port), disp
            )
            logger.info(f"OSC listening on 127.0.0.1:{self.port}")
            self._server.serve_forever()
        except ImportError:
            logger.error("python-osc not installed, OSC listener disabled")
        except OSError as e:
            logger.error(f"OSC listener port error: {e}. Try changing listen_port.")
        except Exception as e:
            logger.error(f"OSC listener error: {e}")

    def _handle_mute(self, address: str, *args):
        if args:
            muted = bool(args[0])
            if muted != self._is_muted:
                self._is_muted = muted
                logger.info(f"Mute state: {'muted' if muted else 'unmuted'}")
                if self.on_mute_change:
                    self.on_mute_change(muted)

    def _handle_avatar_param(self, address: str, *args):
        # Log for debugging, can be extended
        pass
