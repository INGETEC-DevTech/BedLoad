# ui/forms/project_form.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QDoubleSpinBox,
                                QGroupBox, QScrollArea, QCheckBox, QPushButton,
                                QLabel, QInputDialog, QMessageBox)
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
            QLabel, QCheckBox { font-size: ${FONT_SIZE_BASE}px; color: $TEXT_SECONDARY; }
        """))

        self.inputs = {}
        self._is_loading = False
        # Points du profil existant, transmis par MainWindow (cf. set_existing_points),
        # pour permettre de pointer anchor_x/anchor_z (ou un raccord) dessus plutôt
        # que de les taper.
        self._existing_points = []
        # Raccords latéraux : (x, z) figés à la sélection, ou None si non configurés.
        self._connect_left = None
        self._connect_right = None

        self._setup_geo_tab()

        self.chk_overlay = QCheckBox("Afficher le profil existant en fond (vert)")
        self.chk_overlay.stateChanged.connect(self.on_value_changed)
        self.main_layout.addWidget(self.chk_overlay)

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

        grp_anchor = QGroupBox("Ancrage && Topographie")
        layout_anchor = QVBoxLayout(grp_anchor)

        self.btn_pick_anchor = QPushButton("Choisir un point d'ancrage existant")
        self.btn_pick_anchor.clicked.connect(self._pick_anchor_point)
        layout_anchor.addWidget(self.btn_pick_anchor)

        form_anchor = QFormLayout()
        self.inputs['anchor_x'] = self._create_spinbox(-1000, 1000, 0.1)
        self.inputs['anchor_z'] = self._create_spinbox(-100, 1000, 0.01)
        form_anchor.addRow("X bord gauche fond (m):", self.inputs['anchor_x'])
        form_anchor.addRow("Z fond du lit (m NGF):", self.inputs['anchor_z'])
        layout_anchor.addLayout(form_anchor)

        self.lbl_anchor_confirm = QLabel()
        self.lbl_anchor_confirm.setWordWrap(True)
        self.lbl_anchor_confirm.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_SM}px; color: $TEXT_MUTED;"
        ))
        self.lbl_anchor_confirm.setVisible(False)
        layout_anchor.addWidget(self.lbl_anchor_confirm)

        # --- Raccords latéraux optionnels vers le profil existant ---
        self.btn_pick_connect_left = QPushButton("Choisir le point de raccord gauche")
        self.btn_pick_connect_left.clicked.connect(lambda: self._pick_connect_point('left'))
        layout_anchor.addWidget(self.btn_pick_connect_left)

        self.btn_remove_connect_left = QPushButton("Retirer le raccord")
        self.btn_remove_connect_left.clicked.connect(lambda: self._remove_connect_point('left'))
        self.btn_remove_connect_left.setVisible(False)
        layout_anchor.addWidget(self.btn_remove_connect_left)

        self.lbl_connect_confirm_left = QLabel()
        self.lbl_connect_confirm_left.setWordWrap(True)
        self.lbl_connect_confirm_left.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_SM}px; color: $TEXT_MUTED;"
        ))
        self.lbl_connect_confirm_left.setVisible(False)
        layout_anchor.addWidget(self.lbl_connect_confirm_left)

        self.btn_pick_connect_right = QPushButton("Choisir le point de raccord droit")
        self.btn_pick_connect_right.clicked.connect(lambda: self._pick_connect_point('right'))
        layout_anchor.addWidget(self.btn_pick_connect_right)

        self.btn_remove_connect_right = QPushButton("Retirer le raccord")
        self.btn_remove_connect_right.clicked.connect(lambda: self._remove_connect_point('right'))
        self.btn_remove_connect_right.setVisible(False)
        layout_anchor.addWidget(self.btn_remove_connect_right)

        self.lbl_connect_confirm_right = QLabel()
        self.lbl_connect_confirm_right.setWordWrap(True)
        self.lbl_connect_confirm_right.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_SM}px; color: $TEXT_MUTED;"
        ))
        self.lbl_connect_confirm_right.setVisible(False)
        layout_anchor.addWidget(self.lbl_connect_confirm_right)

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

        grp_berms = QGroupBox("Banquettes && Berges")
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
        # Sans ce stretch final, le QVBoxLayout distribue l'espace restant du QScrollArea
        # en étirant chaque QGroupBox au lieu de le laisser vide en bas.
        layout.addStretch()

        scroll.setWidget(widget)
        self.main_layout.addWidget(scroll)

    def get_data(self) -> dict:
        data = {key: sb.value() for key, sb in self.inputs.items()}
        data['show_overlay'] = self.chk_overlay.isChecked()
        data['connect_x_left'], data['connect_z_left'] = self._connect_left or (None, None)
        data['connect_x_right'], data['connect_z_right'] = self._connect_right or (None, None)
        return data

    def set_data(self, data: dict):
        self._is_loading = True

        for key, value in data.items():
            if key in self.inputs:
                self.inputs[key].setValue(float(value))

        self.chk_overlay.setChecked(bool(data.get('show_overlay', False)))
        # Simple repère visuel ponctuel de la session : il ne fait pas partie des
        # données sauvegardées, donc il se réinitialise à chaque rechargement de profil.
        self.lbl_anchor_confirm.setVisible(False)

        cx_l, cz_l = data.get('connect_x_left'), data.get('connect_z_left')
        self._connect_left = (cx_l, cz_l) if cx_l is not None and cz_l is not None else None
        self._update_connect_ui('left')

        cx_r, cz_r = data.get('connect_x_right'), data.get('connect_z_right')
        self._connect_right = (cx_r, cz_r) if cx_r is not None and cz_r is not None else None
        self._update_connect_ui('right')

        self._is_loading = False

    def set_existing_points(self, existing_data: list):
        """Reçoit les points du profil existant (MainWindow), pour permettre de
        choisir directement l'un d'eux comme point d'ancrage."""
        self._existing_points = existing_data

    def _pick_anchor_point(self):
        if not self._existing_points:
            QMessageBox.information(
                self, "Aucun point disponible",
                "Renseignez d'abord des points dans l'onglet Profil existant."
            )
            return

        points = sorted(
            (pt["X (m)"], pt["Z (m NGF)"]) for pt in self._existing_points
        )
        items = [f"X = {x:.2f} m  |  Z = {z:.2f} m NGF" for x, z in points]

        item, ok = QInputDialog.getItem(
            self, "Choisir un point d'ancrage", "Point (X, Z) :", items, editable=False
        )
        if not ok or not item:
            return

        x, z = points[items.index(item)]

        # On bloque temporairement les signaux des deux spinboxes pour n'émettre
        # data_changed qu'une seule fois à la fin (même pattern que paste_from_clipboard).
        self.inputs['anchor_x'].blockSignals(True)
        self.inputs['anchor_z'].blockSignals(True)
        self.inputs['anchor_x'].setValue(x)
        self.inputs['anchor_z'].setValue(z)
        self.inputs['anchor_x'].blockSignals(False)
        self.inputs['anchor_z'].blockSignals(False)

        self.lbl_anchor_confirm.setText(
            f"Ancré sur le point existant X = {x:.2f} m, Z = {z:.2f} m NGF"
        )
        self.lbl_anchor_confirm.setVisible(True)

        self.on_value_changed()

    def _bank_top_x(self, side: str) -> float:
        """Reproduit le calcul de hdbg.x / hdbd.x de core.geometry.build_project_cross_section,
        pour valider un point de raccord AVANT de l'enregistrer (même règle des deux côtés)."""
        anchor_x = self.inputs['anchor_x'].value()
        bed_side_slope = self.inputs['bed_side_slope'].value()
        bed_depth = self.inputs['bed_depth'].value()

        if side == 'left':
            banq_x = anchor_x - bed_side_slope * bed_depth
            pdb_x = banq_x - self.inputs['berm_width_left'].value()
            return pdb_x - self.inputs['bank_width_left'].value()

        fdld_x = anchor_x + self.inputs['bed_width'].value()
        banq_x = fdld_x + bed_side_slope * bed_depth
        pdb_x = banq_x + self.inputs['berm_width_right'].value()
        return pdb_x + self.inputs['bank_width_right'].value()

    def _pick_connect_point(self, side: str):
        if not self._existing_points:
            QMessageBox.information(
                self, "Aucun point disponible",
                "Renseignez d'abord des points dans l'onglet Profil existant."
            )
            return

        points = sorted(
            (pt["X (m)"], pt["Z (m NGF)"]) for pt in self._existing_points
        )
        items = [f"X = {x:.2f} m  |  Z = {z:.2f} m NGF" for x, z in points]

        title = "Choisir le point de raccord gauche" if side == 'left' else "Choisir le point de raccord droit"
        item, ok = QInputDialog.getItem(self, title, "Point (X, Z) :", items, editable=False)
        if not ok or not item:
            return

        x, z = points[items.index(item)]
        bank_top_x = self._bank_top_x(side)

        if side == 'left':
            is_valid = x < bank_top_x
            error_msg = (
                "Le point de raccord gauche est plus proche de l'axe du lit que le "
                "haut de berge actuel — géométrie invalide."
            )
        else:
            is_valid = x > bank_top_x
            error_msg = (
                "Le point de raccord droit est plus proche de l'axe du lit que le "
                "haut de berge actuel — géométrie invalide."
            )

        if not is_valid:
            QMessageBox.warning(self, "Point de raccord invalide", error_msg)
            return

        if side == 'left':
            self._connect_left = (x, z)
        else:
            self._connect_right = (x, z)

        self._update_connect_ui(side)
        self.on_value_changed()

    def _remove_connect_point(self, side: str):
        if side == 'left':
            self._connect_left = None
        else:
            self._connect_right = None

        self._update_connect_ui(side)
        self.on_value_changed()

    def _update_connect_ui(self, side: str):
        if side == 'left':
            connect, lbl, btn_remove = self._connect_left, self.lbl_connect_confirm_left, self.btn_remove_connect_left
        else:
            connect, lbl, btn_remove = self._connect_right, self.lbl_connect_confirm_right, self.btn_remove_connect_right

        if connect is not None:
            x, z = connect
            lbl.setText(f"Raccordé au point existant X = {x:.2f} m, Z = {z:.2f} m NGF")
        lbl.setVisible(connect is not None)
        btn_remove.setVisible(connect is not None)

    def on_value_changed(self):
        if not self._is_loading:
            self.data_changed.emit(self.get_data())
