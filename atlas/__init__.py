"""Атлас AgPM: конвейер, база и сборка сайта."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_JSON = ROOT / "reference" / "Атлас_базовые_данные_2026-10-09_v1.json"
REFERENCE_HTML = ROOT / "reference" / "AgPM_atlas_navigator_2026-10-09_AgPMO.html"
PROTOTYPE = ROOT / "prototype" / "atlas-site"
