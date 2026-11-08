"""MIDI input from any USB drum kit (python-rtmidi), delivered to the UI as Qt signals.

Hits are timestamped with time.perf_counter() the moment rtmidi's thread receives them, so the
timing doesn't depend on how busy the UI is. Every channel is accepted, since kits differ.
"""

import time

from PySide6.QtCore import QObject, QTimer, Signal

NOTE_ON = 0x90
CONTROL_CHANGE = 0xB0
HIHAT_PEDAL_CC = 4


class MidiInput(QObject):
    hit = Signal(int, int, float)        # note, velocity, perf_counter time
    pedal = Signal(int)                  # hi-hat pedal position 0 (open) .. 127 (closed)
    ports_changed = Signal(list)         # available input names
    connected = Signal(str)              # name of the open port, "" when none

    def __init__(self, preferred="", parent=None):
        super().__init__(parent)
        import rtmidi

        self._rtmidi = rtmidi
        self._port = None
        self.port_name = ""
        self.preferred = preferred
        self.ports = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.rescan)
        self._timer.start(2000)  # hot-plug: notice kits being plugged in or out

    def rescan(self):
        try:
            # a new MidiIn each time: on Windows one kept from startup may never list a kit plugged in later
            lister = self._rtmidi.MidiIn()
            ports = lister.get_ports()
            lister.delete()
        except Exception:
            ports = []
        if ports != self.ports:
            self.ports = ports
            self.ports_changed.emit(ports)
        if self.port_name and self.port_name not in ports:
            self.close()
        if not self.port_name and ports:
            choice = self.preferred if self.preferred in ports else ports[0]
            self.open(choice)

    def open(self, name):
        self.close()
        if name not in self.ports:
            return False
        try:
            port = self._rtmidi.MidiIn()
            port.open_port(self.ports.index(name))
            port.ignore_types(sysex=True, timing=True, active_sense=True)
            port.set_callback(self._on_message)
        except Exception:
            return False
        self._port, self.port_name, self.preferred = port, name, name
        self.connected.emit(name)
        return True

    def close(self):
        if self._port is not None:
            try:
                self._port.cancel_callback()
                self._port.close_port()
            except Exception:
                pass
        self._port = None
        if self.port_name:
            self.port_name = ""
            self.connected.emit("")

    def _on_message(self, event, _data):
        now = time.perf_counter()
        msg, _delta = event
        if len(msg) < 3:
            return
        kind = msg[0] & 0xF0
        if kind == NOTE_ON and msg[2] > 0:  # velocity 0 = note off on many kits
            self.hit.emit(msg[1], msg[2], now)
        elif kind == CONTROL_CHANGE and msg[1] == HIHAT_PEDAL_CC:
            self.pedal.emit(msg[2])
