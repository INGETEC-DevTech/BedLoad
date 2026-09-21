# ui/forms/project_form.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QStackedWidget,
                                QDoubleSpinBox, QGroupBox, QScrollArea, QRadioButton, 
                                QHBoxLayout, QPushButton, QButtonGroup)
from PyQt6.QtCore import pyqtSignal

from ui import theme

class ProjectProfileForm(QWidget):
    data_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, theme.SPACE_MD, 0, 0)
        self.main_layout.setSpacing(theme.SPACE_MD)

        # Niveau 3 de la hiérarchie typographique : les libellés restent en retrait des
        # valeurs qu'ils décrivent (14px, cf. la règle globale sur les champs de saisie).
        self.setStyleSheet(theme.qss("""
            QLabel, QRadioButton { font-size: ${FONT_SIZE_BASE}px; color: $TEXT_SECONDARY; }
        """))
        
        # --- MENU PILULE (Segmented Control) ---
        self.nav_layout = QHBoxLayout()
        self.btn_geo = QPushButton("Géométrie")
        self.btn_hydro = QPushButton("Hydraulique")
        
        self.btn_geo.setCheckable(True)
        self.btn_hydro.setCheckable(True)
        self.btn_geo.setChecked(True)
        
        # Style QSS intégré pour créer l'effet pilule
        base_style = theme.qss("""
            QPushButton { background-color: $SURFACE; border: 1px solid $BORDER_INPUT; padding: ${SPACE_SM}px ${SPACE_LG}px; color: $TEXT_SECONDARY; font-weight: bold; }
            QPushButton:checked { background-color: $PRIMARY; color: $SURFACE; border: 1px solid $PRIMARY; }
            QPushButton:hover:!checked { background-color: $HOVER; }
        """)
        radius = theme.RADIUS_PILL
        self.btn_geo.setStyleSheet(
            base_style + f"border-top-left-radius: {radius}px; border-bottom-left-radius: {radius}px; border-right: none;"
        )
        self.btn_hydro.setStyleSheet(
            base_style + f"border-top-right-radius: {radius}px; border-bottom-right-radius: {radius}px;"
        )
        
        self.btn_group = QButtonGroup(self)
        self.btn_group.addButton(self.btn_geo, 0)
        self.btn_group.addButton(self.btn_hydro, 1)
        self.btn_group.buttonClicked.connect(self._switch_page)
        
        self.nav_layout.addStretch()
        self.nav_layout.addWidget(self.btn_geo)
        self.nav_layout.addWidget(self.btn_hydro)
        self.nav_layout.setSpacing(0) # Colle les deux boutons
        self.nav_layout.addStretch()
        self.main_layout.addLayout(self.nav_layout)
        
        # --- ZONE DE CONTENU DYNAMIQUE ---
        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)
        
        self.inputs = {}
        self._is_loading = False
        
        self._setup_geo_tab()
        self._setup_hydro_tab()
        
    def _switch_page(self, button):
        """Bascule l'affichage entre Géométrie (0) et Hydraulique (1)"""
        self.stack.setCurrentIndex(self.btn_group.id(button))
        
    def _create_spinbox(self, min_val, max_val, step, decimals=2, default_val=None):
        sb = QDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setSingleStep(step)
        sb.setDecimals(decimals)
        if default_val is not None:
            sb.setValue(default_val)
        sb.valueChanged.connect(self.on_value_changed)
        return sb
        
    def _setup_geo_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }") # Évite une double bordure
        widget = QWidget()
        layout = QVBoxLayout(widget)
        # Marge droite plus large : elle réserve la place de la barre de défilement.
        layout.setContentsMargins(0, 0, theme.SPACE_MD, theme.SPACE_SM)
        layout.setSpacing(theme.SPACE_SM)

        grp_anchor = QGroupBox("Ancrage & Topographie")
        form_anchor = QFormLayout(grp_anchor)
        self.inputs['anchor_x'] = self._create_spinbox(-1000, 1000, 0.1)
        self.inputs['anchor_z'] = self._create_spinbox(-100, 1000, 0.01)
        self.inputs['slope'] = self._create_spinbox(0.0001, 1.0, 0.001, 4)
        form_anchor.addRow("X bord gauche fond (m):", self.inputs['anchor_x'])
        form_anchor.addRow("Z fond du lit (m NGF):", self.inputs['anchor_z'])
        form_anchor.addRow("Pente long. (m/m):", self.inputs['slope'])
        layout.addWidget(grp_anchor)
        
        grp_bed = QGroupBox("Lit trapézoïdal")
        form_bed = QFormLayout(grp_bed)
        self.inputs['bed_width'] = self._create_spinbox(0, 1000, 0.1)
        self.inputs['bed_depth'] = self._create_spinbox(0, 100, 0.01)
        self.inputs['bed_side_slope'] = self._create_spinbox(0.01, 100, 0.1)
        form_bed.addRow("Largeur fond (m):", self.inputs['bed_width'])
        form_bed.addRow("Profondeur (m):", self.inputs['bed_depth'])
        form_bed.addRow("Pente bords (H/V):", self.inputs['bed_side_slope'])
        layout.addWidget(grp_bed)
        
        grp_berms = QGroupBox("Banquettes & Berges")
        form_berms = QFormLayout(grp_berms)
        self.inputs['berm_width_left'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['berm_width_right'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['bank_slope_left'] = self._create_spinbox(0.01, 100, 0.1)
        self.inputs['bank_width_left'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['bank_slope_right'] = self._create_spinbox(0.01, 100, 0.1)
        self.inputs['bank_width_right'] = self._create_spinbox(0, 100, 0.1)
        form_berms.addRow("Banquette RG (m):", self.inputs['berm_width_left'])
        form_berms.addRow("Banquette RD (m):", self.inputs['berm_width_right'])
        form_berms.addRow("Pente Berge G (H/V):", self.inputs['bank_slope_left'])
        form_berms.addRow("Largeur Berge G (m):", self.inputs['bank_width_left'])
        form_berms.addRow("Pente Berge D (H/V):", self.inputs['bank_slope_right'])
        form_berms.addRow("Largeur Berge D (m):", self.inputs['bank_width_right'])
        layout.addWidget(grp_berms)
        
        scroll.setWidget(widget)
        self.stack.addWidget(scroll)
        
    def _setup_hydro_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, theme.SPACE_MD, theme.SPACE_SM)
        layout.setSpacing(theme.SPACE_SM)

        grp_mode = QGroupBox("Mode de dimensionnement")
        layout_mode = QVBoxLayout(grp_mode)
        self.radio_calc_q = QRadioButton("Imposer H (Calculer le Débit)")
        self.radio_calc_h = QRadioButton("Imposer Q (Calculer la Hauteur d'eau)")
        self.radio_calc_q.setChecked(True)
        layout_mode.addWidget(self.radio_calc_q)
        layout_mode.addWidget(self.radio_calc_h)
        layout.addWidget(grp_mode)
        
        self.radio_calc_q.toggled.connect(self._toggle_hydro_fields)
        
        grp_hydro = QGroupBox("Paramètres Hydrauliques")
        form_hydro = QFormLayout(grp_hydro)
        
        self.inputs['h_eau'] = self._create_spinbox(0.01, 100, 0.05, 3, default_val=0.42)
        self.inputs['q_target'] = self._create_spinbox(0.1, 10000, 0.5, 2, default_val=15.0)
        self.inputs['ks_pro'] = self._create_spinbox(10, 100, 1, 1, default_val=25.0)
        
        form_hydro.addRow("Tirant d'eau h (m):", self.inputs['h_eau'])
        form_hydro.addRow("Débit Cible Q (m³/s):", self.inputs['q_target'])
        form_hydro.addRow("Strickler (Ks):", self.inputs['ks_pro'])
        layout.addWidget(grp_hydro)
        layout.addStretch()
        
        self.stack.addWidget(widget)
        self._toggle_hydro_fields()
        
    def _toggle_hydro_fields(self):
        is_calc_q = self.radio_calc_q.isChecked()
        self.inputs['h_eau'].setEnabled(is_calc_q)
        self.inputs['q_target'].setEnabled(not is_calc_q)
        self.on_value_changed()

    def get_data(self) -> dict:
        data = {key: sb.value() for key, sb in self.inputs.items()}
        data['calc_mode'] = 'Q_FROM_H' if self.radio_calc_q.isChecked() else 'H_FROM_Q'
        return data

    def set_data(self, data: dict):
        self._is_loading = True
        
        mode = data.get('calc_mode', 'Q_FROM_H')
        self.radio_calc_q.setChecked(mode == 'Q_FROM_H')
        self.radio_calc_h.setChecked(mode == 'H_FROM_Q')
        
        for key, value in data.items():
            if key in self.inputs:
                self.inputs[key].setValue(float(value))
                
        self._toggle_hydro_fields()
        self._is_loading = False

    def on_value_changed(self):
        if not self._is_loading:
            self.data_changed.emit(self.get_data())