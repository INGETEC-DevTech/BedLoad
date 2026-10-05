# ui/forms/hydraulics_form.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QScrollArea,
                                QRadioButton, QCheckBox, QDoubleSpinBox, QLabel)
from PyQt6.QtCore import pyqtSignal

from ui import theme


class HydraulicsForm(QWidget):
    # Signal émis vers MainWindow quand les données changent (auto-save + maj graphique)
    data_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, theme.SPACE_MD, 0, 0)
        self.main_layout.setSpacing(theme.SPACE_MD)

        self.setStyleSheet(theme.qss("""
            QLabel, QRadioButton, QCheckBox { font-size: ${FONT_SIZE_BASE}px; color: $TEXT_SECONDARY; }
        """))

        self.inputs = {}
        self._is_loading = False

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, theme.SPACE_MD, theme.SPACE_SM)
        layout.setSpacing(theme.SPACE_SM)

        # --- Source du calcul ---
        grp_source = QGroupBox("Calculer sur :")
        layout_source = QVBoxLayout(grp_source)
        self.radio_source_existing = QRadioButton("Profil existant")
        self.radio_source_project = QRadioButton("Profil projet")
        self.radio_source_project.setChecked(True)
        layout_source.addWidget(self.radio_source_existing)
        layout_source.addWidget(self.radio_source_project)
        layout.addWidget(grp_source)

        self.radio_source_project.toggled.connect(self._update_overlay_label)

        # --- Mode de dimensionnement ---
        grp_mode = QGroupBox("Mode de dimensionnement")
        layout_mode = QVBoxLayout(grp_mode)
        self.radio_calc_q = QRadioButton("Imposer H (Calculer le Débit)")
        self.radio_calc_h = QRadioButton("Imposer Q (Calculer la Hauteur d'eau)")
        self.radio_calc_q.setChecked(True)
        layout_mode.addWidget(self.radio_calc_q)
        layout_mode.addWidget(self.radio_calc_h)
        layout.addWidget(grp_mode)

        self.radio_calc_q.toggled.connect(self._toggle_hydro_fields)

        # --- Paramètres hydrauliques ---
        grp_hydro = QGroupBox("Paramètres Hydrauliques")
        form_hydro = QFormLayout(grp_hydro)

        self.inputs['h_eau'] = self._create_spinbox(0.01, 100, 0.05, 3, default_val=0.42)
        self.inputs['q_target'] = self._create_spinbox(0.1, 10000, 0.5, 2, default_val=15.0)
        # Regroupé avec Ks : ce sont les deux seuls paramètres de la formule de
        # Manning-Strickler, ce champ n'a rien à faire dans l'onglet Géométrie.
        self.inputs['slope'] = self._create_spinbox(0.0001, 1.0, 0.001, 4)
        self.inputs['ks_pro'] = self._create_spinbox(10, 100, 1, 1, default_val=25.0)
        # Un seul Ks pour le lit majeur (les deux rives partagent la même rugosité) :
        # stocké ici, pas encore utilisé dans le calcul hydraulique.
        self.inputs['floodplain_ks'] = self._create_spinbox(0, 200, 1, 1, default_val=25.0)

        form_hydro.addRow("Tirant d'eau h (m):", self.inputs['h_eau'])
        form_hydro.addRow("Débit Cible Q (m³/s):", self.inputs['q_target'])
        form_hydro.addRow("Pente long. (m/m):", self.inputs['slope'])
        form_hydro.addRow("Strickler (Ks):", self.inputs['ks_pro'])
        form_hydro.addRow("Strickler (Ks) – Lit majeur:", self.inputs['floodplain_ks'])
        layout.addWidget(grp_hydro)

        # --- Lit de calcul (limites en X) ---
        # Quand le profil comporte plusieurs lits, permet de ne calculer que sur celui
        # compris entre deux X. Les limites agissent comme des parois verticales.
        grp_bounds = QGroupBox("Lit de calcul")
        layout_bounds = QVBoxLayout(grp_bounds)
        self.chk_bounds = QCheckBox("Limiter le calcul au lit compris entre deux X")
        self.chk_bounds.toggled.connect(self._toggle_bounds_fields)
        layout_bounds.addWidget(self.chk_bounds)

        form_bounds = QFormLayout()
        self.inputs['hydro_x_left'] = self._create_spinbox(-1_000_000, 1_000_000, 0.5, 3, default_val=0.0)
        self.inputs['hydro_x_right'] = self._create_spinbox(-1_000_000, 1_000_000, 0.5, 3, default_val=0.0)
        form_bounds.addRow("X gauche (m):", self.inputs['hydro_x_left'])
        form_bounds.addRow("X droite (m):", self.inputs['hydro_x_right'])
        layout_bounds.addLayout(form_bounds)

        hint_bounds = QLabel(
            "L'eau ne s'étend pas au-delà de ces limites (parois verticales, non comptées "
            "dans le périmètre mouillé). Elles sont tracées en tirets sur le graphique."
        )
        hint_bounds.setWordWrap(True)
        hint_bounds.setStyleSheet(theme.qss("color: $TEXT_MUTED; font-size: ${FONT_SIZE_SM}px;"))
        layout_bounds.addWidget(hint_bounds)
        layout.addWidget(grp_bounds)

        # --- Superposition de l'autre profil ---
        self.chk_overlay = QCheckBox()
        self.chk_overlay.stateChanged.connect(self.on_value_changed)
        row_overlay = QHBoxLayout()
        row_overlay.setContentsMargins(theme.SPACE_SM, 0, 0, 0)
        row_overlay.addWidget(self.chk_overlay)
        row_overlay.addStretch()
        layout.addLayout(row_overlay)

        layout.addStretch()

        scroll.setWidget(widget)
        self.main_layout.addWidget(scroll)

        self._toggle_hydro_fields()
        self._update_overlay_label()
        self._toggle_bounds_fields()

    def _toggle_bounds_fields(self, _=None):
        enabled = self.chk_bounds.isChecked()
        self.inputs['hydro_x_left'].setEnabled(enabled)
        self.inputs['hydro_x_right'].setEnabled(enabled)
        self.on_value_changed()

    def _create_spinbox(self, min_val, max_val, step, decimals=2, default_val=None):
        sb = QDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setSingleStep(step)
        sb.setDecimals(decimals)
        if default_val is not None:
            sb.setValue(default_val)
        sb.valueChanged.connect(self.on_value_changed)
        return sb

    def _toggle_hydro_fields(self):
        is_calc_q = self.radio_calc_q.isChecked()
        self.inputs['h_eau'].setEnabled(is_calc_q)
        self.inputs['q_target'].setEnabled(not is_calc_q)
        self.on_value_changed()

    def _update_overlay_label(self):
        # Le libellé nomme toujours l'AUTRE profil que celui sur lequel porte le calcul.
        other = "existant" if self.radio_source_project.isChecked() else "projet"
        self.chk_overlay.setText(f"Afficher le profil {other} en fond")
        self.on_value_changed()

    def get_data(self) -> dict:
        data = {key: sb.value() for key, sb in self.inputs.items()}
        data['calc_mode'] = 'Q_FROM_H' if self.radio_calc_q.isChecked() else 'H_FROM_Q'
        data['hydro_source'] = 'existing' if self.radio_source_existing.isChecked() else 'project'
        data['show_overlay'] = self.chk_overlay.isChecked()
        data['hydro_bounds_enabled'] = self.chk_bounds.isChecked()
        return data

    def set_data(self, data: dict):
        self._is_loading = True

        mode = data.get('calc_mode', 'Q_FROM_H')
        self.radio_calc_q.setChecked(mode == 'Q_FROM_H')
        self.radio_calc_h.setChecked(mode == 'H_FROM_Q')

        source = data.get('hydro_source', 'project')
        self.radio_source_existing.setChecked(source == 'existing')
        self.radio_source_project.setChecked(source != 'existing')

        self.chk_overlay.setChecked(bool(data.get('show_overlay', False)))
        self.chk_bounds.setChecked(bool(data.get('hydro_bounds_enabled', False)))

        for key, value in data.items():
            if key in self.inputs:
                self.inputs[key].setValue(float(value))
        # Profil enregistré avant l'ajout du lit de calcul : pas de limites en base, on
        # remet les valeurs par défaut plutôt que de garder celles du profil précédent.
        for key in ('hydro_x_left', 'hydro_x_right'):
            if key not in data:
                self.inputs[key].setValue(0.0)

        self._toggle_hydro_fields()
        self._update_overlay_label()
        self._toggle_bounds_fields()
        self._is_loading = False

    def on_value_changed(self):
        if not self._is_loading:
            self.data_changed.emit(self.get_data())
