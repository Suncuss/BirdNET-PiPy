"""Minimal in-process MQTT 3.1.1 broker for exercising real Apprise + paho."""

import socket
import threading
import time


def _recv_exact(conn, n):
    data = b''
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


class FakeMqttBroker:
    """Answers CONNECT and PINGREQ, records the topic of each QoS 0 PUBLISH.

    ``connack_delay`` holds back every CONNACK, standing in for a broker that
    authenticates slowly (e.g. Home Assistant's Mosquitto add-on).
    """

    def __init__(self, connack_delay=0.0):
        self.connack_delay = connack_delay
        self.published = []
        self._open = 0
        self._lock = threading.Lock()
        self._server = socket.socket()
        self._server.bind(('127.0.0.1', 0))
        self._server.listen(64)
        self.port = self._server.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def url(self, topic='birdnet/detection'):
        return f'mqtt://127.0.0.1:{self.port}/{topic}'

    @property
    def open_connections(self):
        with self._lock:
            return self._open

    def wait_for_no_connections(self, timeout=5.0):
        """Wait for clients to hang up; returns how many are still open."""
        deadline = time.monotonic() + timeout
        while self.open_connections and time.monotonic() < deadline:
            time.sleep(0.02)
        return self.open_connections

    def close(self):
        self._server.close()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _read_packet(self, conn):
        header = _recv_exact(conn, 1)
        if header is None:
            return None, None
        length, shift = 0, 0
        while True:  # variable-length "remaining length" field
            byte = _recv_exact(conn, 1)
            if byte is None:
                return None, None
            length |= (byte[0] & 0x7F) << shift
            shift += 7
            if not byte[0] & 0x80:
                break
        body = _recv_exact(conn, length) if length else b''
        return header[0] >> 4, body

    def _serve(self, conn):
        with self._lock:
            self._open += 1
        try:
            while True:
                packet_type, body = self._read_packet(conn)
                if packet_type is None or body is None or packet_type == 14:  # DISCONNECT
                    return
                if packet_type == 1:  # CONNECT
                    time.sleep(self.connack_delay)
                    conn.sendall(b'\x20\x02\x00\x00')
                elif packet_type == 3:  # PUBLISH: 2-byte topic length, topic, payload
                    topic_len = int.from_bytes(body[:2], 'big')
                    with self._lock:
                        self.published.append(body[2:2 + topic_len].decode())
                elif packet_type == 12:  # PINGREQ
                    conn.sendall(b'\xd0\x00')
        except OSError:
            return
        finally:
            conn.close()
            with self._lock:
                self._open -= 1
