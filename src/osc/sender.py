"""
VRChat OSC sender for chatbox messages.
Combines Yakutan's priority throttling with MioVRC's queue-based send loop.

Protocol:
  1. /chatbox/typing  [bool: ongoing]
  2. /chatbox/input   [text, True, not_ongoing]
"""
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

PRIORITY_HIGH = 1  # final messages
PRIORITY_LOW = 2   # partial/ongoing messages
MAX_CHATBOX_CHARS = 144
DUPLICATE_WINDOW_S = 1.5
SEND_QUEUE_MAXSIZE = 32


@dataclass
class _QueuedMessage:
    text: str
    ongoing: bool
    priority: int
    rate_limited: bool = True


class OSCSender:
    """Sends messages to VRChat chatbox via OSC with queue-based throttling."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9000,
                 max_length: int = 144, min_interval: float = 1.5):
        self.host = host
        self.port = port
        self.max_length = min(max_length, MAX_CHATBOX_CHARS)
        self.min_send_interval = min_interval

        self._running = False
        self._client = None
        self._send_thread: Optional[threading.Thread] = None

        # Queue-based send (MioVRC pattern)
        self._queue: queue.Queue[_QueuedMessage] = queue.Queue(maxsize=SEND_QUEUE_MAXSIZE)
        self._last_sent_at = 0.0

        # Duplicate suppression
        self._state_lock = threading.Lock()
        self._last_enqueued_text = ""
        self._last_enqueued_at = 0.0
        self._last_sent_text = ""

    def start(self):
        if self._running:
            return
        self._running = True
        self._init_client()
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True, name="osc-send")
        self._send_thread.start()
        logger.info(f"OSC sender started: {self.host}:{self.port}")

    def stop(self):
        self._running = False
        # Poison pill
        try:
            self._queue.put_nowait(None)  # type: ignore
        except queue.Full:
            pass
        if self._send_thread:
            self._send_thread.join(timeout=3)
            self._send_thread = None
        logger.info("OSC sender stopped")

    def send_chatbox(self, text: str, priority: str = "normal"):
        """Send final text to VRChat chatbox."""
        if not text or not self._running:
            return
        safe = self._normalize_text(text)
        if not safe:
            return
        p = PRIORITY_HIGH if priority == "high" else PRIORITY_LOW
        self._enqueue(safe, ongoing=False, priority=p)

    def send_partial(self, text: str):
        """Send partial/ongoing text (typing indicator)."""
        if not text or not self._running:
            return
        safe = self._normalize_text(text)
        if not safe:
            return
        self._enqueue(safe, ongoing=True, priority=PRIORITY_LOW)

    def set_typing(self, typing: bool):
        """Send typing indicator only."""
        if not self._running or not self._client:
            return
        try:
            self._client.send_message("/chatbox/typing", typing)
        except Exception as e:
            logger.debug(f"OSC typing error: {e}")

    def clear_chatbox(self):
        """Clear the chatbox."""
        if not self._running or not self._client:
            return
        try:
            self._client.send_message("/chatbox/typing", False)
            self._client.send_message("/chatbox/input", ["", True, True])
        except Exception:
            pass

    # ── Internal ────────────────────────────────────────────────

    def _normalize_text(self, text: str) -> str:
        safe = str(text or "").strip()
        if len(safe) > self.max_length:
            safe = safe[:self.max_length - 3] + "..."
        return safe

    def _enqueue(self, text: str, ongoing: bool, priority: int):
        """Enqueue with duplicate suppression (MioVRC pattern)."""
        now = time.monotonic()
        with self._state_lock:
            # Duplicate suppression: same text within window
            if (text == self._last_enqueued_text
                    and (now - self._last_enqueued_at) < DUPLICATE_WINDOW_S
                    and not ongoing):
                return
            self._last_enqueued_text = text
            self._last_enqueued_at = now

        msg = _QueuedMessage(text=text, ongoing=ongoing, priority=priority)

        # Drop-oldest-on-full pattern (MioVRC)
        try:
            self._queue.put_nowait(msg)
            return
        except queue.Full:
            pass
        # Queue full: drop oldest, try again
        try:
            self._queue.get_nowait()
        except queue.Empty:
            return
        try:
            self._queue.put_nowait(msg)
        except queue.Full:
            pass

    def _send_loop(self):
        """Dedicated send thread with rate limiting (MioVRC pattern)."""
        while True:
            msg = self._queue.get()
            if msg is None:
                return
            try:
                if msg.rate_limited:
                    wait = self.min_send_interval - (time.monotonic() - self._last_sent_at)
                    if wait > 0:
                        time.sleep(wait)

                # Priority check: skip low-priority if a high-priority is queued
                if msg.priority == PRIORITY_LOW and not self._queue.empty():
                    # Peek if higher priority is waiting
                    try:
                        next_msg = self._queue.get_nowait()
                        if next_msg.priority <= msg.priority:
                            # Higher or equal priority found, send it instead
                            self._do_send(next_msg)
                        else:
                            # Lower priority, send current and re-queue next
                            self._do_send(msg)
                            self._queue.put_nowait(next_msg)
                            continue
                    except queue.Empty:
                        pass

                self._do_send(msg)
            except Exception as exc:
                logger.error(f"OSC send error: {exc}")

    def _do_send(self, msg: _QueuedMessage):
        """Actually send the OSC message."""
        if not self._client:
            return
        try:
            self._client.send_message("/chatbox/typing", msg.ongoing)
            self._client.send_message("/chatbox/input", [msg.text, True, not msg.ongoing])
            self._last_sent_at = time.monotonic()
            if not msg.ongoing:
                with self._state_lock:
                    self._last_sent_text = msg.text
            logger.debug(f"OSC sent: ongoing={msg.ongoing} text={msg.text[:50]}")
        except Exception as e:
            logger.error(f"OSC send error: {e}")

    def _init_client(self):
        try:
            from pythonosc import udp_client
            self._client = udp_client.SimpleUDPClient(self.host, self.port)
        except ImportError:
            logger.error("python-osc not installed")
            self._client = None
