"""Magna Carta's public GUI registration; no emulator or transport connection."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_magnacarta_registration_is_exact():
    from adapters.magnacarta.adapter import MagnaCartaAdapter
    from gui.camera_controller import app as gui
    assert gui.ADAPTERS["MAGNACARTA"] is MagnaCartaAdapter
    assert gui.ADAPTER_BY_GAME_ID["SLPS-25401"] is MagnaCartaAdapter
    assert "SLPS-25401" in gui.SUPPORTED_IDS
