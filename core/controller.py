# core/controller.py
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional
import pandas as pd
import plotly.graph_objects as go

from core.geometry import build_project_cross_section
from core.models import CrossSection, ProjectParameters, dataframe_to_points
from core.hydraulics import compute_hydraulic_params, find_water_level_for_discharge
from viz.plots import EXISTING_COLOR, PROJECT_COLOR, plot_overlay, plot_single_profile

class ViewMode(Enum):
    EXISTING = "existing"
    PROJECT = "project"

class ProfileController:
    MIN_POINTS_FOR_PLOT = 2

    def build_figure(
        self,
        existing_data: List[Dict[str, Any]],
        project_data: Dict[str, Any],
        mode: ViewMode,
        show_overlay: bool = False,
    ) -> Optional[go.Figure]:
        
        if mode is ViewMode.EXISTING:
            return self._build_existing_figure(existing_data)
        return self._build_project_figure(existing_data, project_data, show_overlay)

    @staticmethod
    def default_project_params() -> Dict[str, Any]:
        return vars(ProjectParameters())

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
        
        # --- Moteur Hydraulique ---
        mode = project_data.get('calc_mode', 'Q_FROM_H')
        slope = getattr(params, 'slope', 0.005)
        ks = getattr(params, 'ks_pro', 25.0)
        anchor_z = getattr(params, 'anchor_z', 0.0)
        
        if mode == 'H_FROM_Q':
            q_target = project_data.get('q_target', 15.0)
            res = find_water_level_for_discharge(section_proj, q_target, slope, ks)
        else:
            h_eau = project_data.get('h_eau', 0.5)
            res = compute_hydraulic_params(section_proj, anchor_z + h_eau, slope, ks)

        # --- Génération de la figure ---
        if show_overlay:
            section_ext = self._to_cross_section(existing_data, name="Existant", allow_empty=True)
            fig = plot_overlay(
                section_ext, section_proj,
                water_level=res["water_z"], water_x_left=res["x_left"], water_x_right=res["x_right"]
            )
        else:
            fig = plot_single_profile(
                section_proj, color=PROJECT_COLOR,
                water_level=res["water_z"], water_x_left=res["x_left"], water_x_right=res["x_right"]
            )
            
        # --- Incrustation des résultats ---
        if res["S"] > 0:
            calc_h_tag = "[Calculé]" if mode == 'H_FROM_Q' else "[Saisi]"
            calc_q_tag = "[Saisi]" if mode == 'H_FROM_Q' else "[Calculé]"
            h_relative = res["water_z"] - anchor_z
            
            texte_resultats = (
                f"<b>Débit (Q) :</b> {res['Q']:.2f} m³/s <i>{calc_q_tag}</i><br>"
                f"<b>Vitesse moyenne (V) :</b> {res['V']:.2f} m/s<br>"
                f"<b>Surface mouillée (S) :</b> {res['S']:.2f} m²<br>"
                f"<b>Tirant d'eau (h) :</b> {h_relative:.2f} m <i>{calc_h_tag}</i>"
            )
            
            fig.add_annotation(
                text=texte_resultats, align="left", showarrow=False,
                xref="paper", yref="paper", x=0.02, y=0.96,
                bgcolor="rgba(255, 255, 255, 0.9)", bordercolor="#ced4da",
                borderwidth=1, borderpad=10, font=dict(size=12, color="#495057")
            )
            
        return fig

    def _to_cross_section(self, raw_data: List[Dict[str, Any]], name: str, allow_empty: bool = False) -> Optional[CrossSection]:
        points = dataframe_to_points(pd.DataFrame(raw_data))
        if not allow_empty and len(points) < self.MIN_POINTS_FOR_PLOT:
            return None
        return CrossSection(name=name, points=points)

    @staticmethod
    def _to_project_parameters(project_data: Dict[str, Any]) -> ProjectParameters:
        valid_keys = ProjectParameters.__dataclass_fields__.keys()
        filtered = {k: v for k, v in project_data.items() if k in valid_keys}
        return ProjectParameters(**filtered)