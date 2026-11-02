"""Keyboard source: arrow keys are only the camera's while the game or the controller has the focus."""
from __future__ import annotations

from core.controller import sources
from core.controller.sources import KeyboardSource, keyboard_focus_ok


def test_focus_rules():
    assert keyboard_focus_ok("pcsx2-qt.exe")
    assert keyboard_focus_ok("python.exe")
    assert not keyboard_focus_ok("notepad.exe")
    assert not keyboard_focus_ok("chrome.exe")
    assert not keyboard_focus_ok("")                    # unknown window: not for us
    assert keyboard_focus_ok("myapp.exe", own_exe="MyApp.exe")


def test_arrow_keys_are_ignored_in_other_windows(monkeypatch):
    src = KeyboardSource(foreground_only=True)
    monkeypatch.setattr(sources, "_foreground_process_name", lambda: "notepad.exe")
    monkeypatch.setattr(src, "_user32", type("U", (), {"GetAsyncKeyState": staticmethod(lambda vk: 0x8000)})())
    assert src.poll() == (0.0, 0.0)
    monkeypatch.setattr(sources, "_foreground_process_name", lambda: "pcsx2-qt.exe")
    src._focus_checked = 0.0
    assert src.poll() == (0.0, 0.0)                     # all four arrows down cancel out ...
    monkeypatch.setattr(src, "_user32", type("U", (), {
        "GetAsyncKeyState": staticmethod(lambda vk: 0x8000 if vk == 0x27 else 0)})())
    assert src.poll() == (1.0, 0.0)                     # ... and right alone turns the camera


def test_foreground_only_can_be_switched_off(monkeypatch):
    src = KeyboardSource(foreground_only=False)
    monkeypatch.setattr(sources, "_foreground_process_name", lambda: "notepad.exe")
    monkeypatch.setattr(src, "_user32", type("U", (), {
        "GetAsyncKeyState": staticmethod(lambda vk: 0x8000 if vk == 0x26 else 0)})())
    assert src.poll() == (0.0, 1.0)
