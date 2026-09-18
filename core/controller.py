"""
core/controller.py

Couche d'orchestration entre les données brutes des formulaires (UI) et la
génération des figures Plotly (viz/plots.py).

Cette classe ne dépend d'aucun module Qt : elle ne manipule que des types
Python natifs (dict, list) en entrée et renvoie une figure Plotly (ou None).
Elle est donc testable indépendamment de l'interface graphique.

La vue (ui/main_window.py) ne doit plus faire que :
    1. lire les données brutes des formulaires,
    2. les transmettre au contrôleur,
    3. afficher la figure renvoyée.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go

from core.geometry import build_project_cross_section
from core.models import CrossSection, ProjectParameters, dataframe_to_points
from viz.plots import EXISTING_COLOR, PROJECT_COLOR, plot_overlay, plot_single_profile


class ViewMode(Enum):
    """Onglet métier actif. Volontairement indépendant de l'ordre des QTabWidget."""
    EXISTING = "existing"
    PROJECT = "project"


@dataclass
class WaterLevel:
    """Paramètres de la ligne d'eau à tracer, dérivés des données du profil projet."""
    level: Optional[float]
    x_left: Optional[float]
    x_right: Optional[float]

    @classmethod
    def from_project_data(cls, project_data: Dict[str, Any]) -> "WaterLevel":
        h_eau = project_data.get("h_eau", 0)
        anchor_z = project_data.get("anchor_z", 0)
        return cls(
            level=anchor_z + h_eau,
            x_left=project_data.get("x_eau_gauche"),
            x_right=project_data.get("x_eau_droite"),
        )


class ProfileController:
    """Construit la figure Plotly à afficher à partir des données brutes des formulaires."""

    # Nombre minimum de points pour qu'un profil existant soit traçable seul.
    MIN_POINTS_FOR_PLOT = 2

    def build_figure(
        self,
        existing_data: List[Dict[str, Any]],
        project_data: Dict[str, Any],
        mode: ViewMode,
        show_overlay: bool = False,
    ) -> Optional[go.Figure]:
        """Retourne la figure Plotly à afficher, ou None si les données sont insuffisantes."""
        if mode is ViewMode.EXISTING:
            return self._build_existing_figure(existing_data)
        return self._build_project_figure(existing_data, project_data, show_overlay)

    @staticmethod
    def default_project_params() -> Dict[str, Any]:
        """Valeurs par défaut à utiliser tant qu'aucun paramètre n'a été sauvegardé."""
        return vars(ProjectParameters())

    # --- Construction des figures -----------------------------------------

    def _build_existing_figure(self, existing_data: List[Dict[str, Any]]) -> Optional[go.Figure]:
        section = self._to_cross_section(existing_data, name="Existant")
        if section is None:
            return None
        return plot_single_profile(section, color=EXISTING_COLOR)

    def _build_project_figure(
        self,
        existing_data: List[Dict[str, Any]],
        project_data: Dict[str, Any],
        show_overlay: bool,
    ) -> go.Figure:
        params = self._to_project_parameters(project_data)
        section_proj = build_project_cross_section(params, name="Projet")
        water = WaterLevel.from_project_data(project_data)

        if show_overlay:
            # Comportement identique à l'ancien code : le profil existant est
            # tracé même s'il est vide/incomplet (pas de contrôle de longueur ici).
            section_ext = self._to_cross_section(existing_data, name="Existant", allow_empty=True)
            return plot_overlay(
                section_ext, section_proj,
                water_level=water.level,
                water_x_left=water.x_left, water_x_right=water.x_right,
            )

        return plot_single_profile(
            section_proj, color=PROJECT_COLOR,
            water_level=water.level,
            water_x_left=water.x_left, water_x_right=water.x_right,
        )

    # --- Conversions données brutes -> modèles métier -----------------------

    def _to_cross_section(
        self,
        raw_data: List[Dict[str, Any]],
        name: str,
        allow_empty: bool = False,
    ) -> Optional[CrossSection]:
        """Convertit les données brutes du tableau en CrossSection, ou None si insuffisant."""
        points = dataframe_to_points(pd.DataFrame(raw_data))
        if not allow_empty and len(points) < self.MIN_POINTS_FOR_PLOT:
            return None
        return CrossSection(name=name, points=points)

    @staticmethod
    def _to_project_parameters(project_data: Dict[str, Any]) -> ProjectParameters:
        """Instancie ProjectParameters en filtrant les clés qui ne lui appartiennent pas."""
        valid_keys = ProjectParameters.__dataclass_fields__.keys()
        filtered = {k: v for k, v in project_data.items() if k in valid_keys}
        return ProjectParameters(**filtered)
