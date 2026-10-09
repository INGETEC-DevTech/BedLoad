# ui/forms/project_form.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QDoubleSpinBox,
                                QGroupBox, QScrollArea, QCheckBox, QPushButton,
                                QLabel, QDialog, QMessageBox, QFrame, QSizePolicy)
from PyQt6.QtCore import pyqtSignal, Qt

from core.geometry import CONNECT_POINT_ERRORS, invalid_connect_side
from core.models import ProjectParameters
from ui import theme
from ui.dialogs.point_picker_dialog import PointPickerDialog

class ProjectProfileForm(QWidget):
    data_changed = pyqtSignal(dict)
    export_excel_requested = pyqtSignal()

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
        # Valeurs (anchor_x, anchor_z) des spinboxes juste après le choix d'un point
        # d'ancrage existant, ou None : le message "Ancré sur le point existant" n'est vrai
        # que tant que l'ancrage garde exactement ces valeurs (cf. _refresh_anchor_confirm).
        self._anchored_values = None
        # Raccords latéraux : (x, z) figés à la sélection, ou None si non configurés.
        self._connect_left = None
        self._connect_right = None
        # Dernier jeu de valeurs de self.inputs connu pour donner une géométrie valide
        # (cf. on_value_changed) : permet d'annuler une saisie qui rendrait un raccord
        # existant invalide, en revenant à la valeur juste avant.
        self._last_valid_values = None

        self._setup_geo_tab()
        self._last_valid_values = {key: sb.value() for key, sb in self.inputs.items()}

    def _create_spinbox(self, min_val, max_val, step, decimals=2, default_val=None):
        sb = QDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setSingleStep(step)
        sb.setDecimals(decimals)
        if default_val is not None:
            sb.setValue(default_val)
        sb.valueChanged.connect(self.on_value_changed)
        return sb

    def _make_section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_SM}px; font-weight: bold; color: $TEXT_SECONDARY;"
        ))
        return lbl

    def _make_separator(self) -> QFrame:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(theme.qss("QFrame { color: $BORDER; }"))
        return separator

    def _build_side_groupbox(self, title, banquette_rows, berge_rows, floodplain_rows) -> QGroupBox:
        """Boîte "Gauche"/"Droite" regroupant, pour une rive donnée, tous les paramètres
        de Banquette, Berges et Lit majeur (dans cet ordre : du plus proche au plus
        éloigné de l'axe du lit), avec un séparateur entre chaque segment."""
        grp = QGroupBox(title)
        box_layout = QVBoxLayout(grp)
        box_layout.setSpacing(theme.SPACE_SM)

        box_layout.addWidget(self._make_section_label("Banquettes"))
        box_layout.addWidget(self._make_separator())
        form_banquette = QFormLayout()
        for label, widget in banquette_rows:
            form_banquette.addRow(label, widget)
        box_layout.addLayout(form_banquette)

        box_layout.addWidget(self._make_section_label("Berges"))
        box_layout.addWidget(self._make_separator())
        form_berge = QFormLayout()
        for label, widget in berge_rows:
            form_berge.addRow(label, widget)
        box_layout.addLayout(form_berge)

        box_layout.addWidget(self._make_section_label("Lit majeur"))
        box_layout.addWidget(self._make_separator())
        form_floodplain = QFormLayout()
        for label, widget in floodplain_rows:
            form_floodplain.addRow(label, widget)
        box_layout.addLayout(form_floodplain)

        return grp

    def _setup_geo_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }") # Évite une double bordure
        # Aucun contenu de cet onglet ne doit jamais déclencher de défilement horizontal,
        # même par accident à l'avenir (cf. les boutons de raccord, qui se partagent
        # désormais la largeur disponible au lieu de la dépasser).
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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

        # Banquette, Berges et Lit majeur : une boîte par rive (Gauche / Droite), côte à
        # côte, chaque boîte regroupant tous les paramètres de cette rive pour les trois
        # segments, du plus proche au plus éloigné de l'axe du lit. Le lit trapézoïdal
        # n'a pas de notion gauche/droite et reste dans son propre groupe ci-dessus.
        row_sides = QHBoxLayout()
        row_sides.setSpacing(theme.SPACE_SM)

        self.inputs['berm_width_left'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['berm_slope_left'] = self._create_spinbox(0.0, 1.0, 0.001, 4)
        self.inputs['bank_slope_left'] = self._create_spinbox(0.01, 100, 0.1)
        self.inputs['bank_width_left'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['floodplain_width_left'] = self._create_spinbox(0, 1000, 0.1)
        self.inputs['floodplain_slope_left'] = self._create_spinbox(0.0, 1.0, 0.001, 4)
        grp_left = self._build_side_groupbox(
            "Gauche",
            banquette_rows=[
                ("Banquette G (m):", self.inputs['berm_width_left']),
                ("Pente Banquette G (m/m):", self.inputs['berm_slope_left']),
            ],
            berge_rows=[
                ("Pente Berge G (H/V):", self.inputs['bank_slope_left']),
                ("Largeur Berge G (m):", self.inputs['bank_width_left']),
            ],
            floodplain_rows=[
                ("Largeur Lit majeur G (m):", self.inputs['floodplain_width_left']),
                ("Pente Lit majeur G (m/m):", self.inputs['floodplain_slope_left']),
            ],
        )

        self.inputs['berm_width_right'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['berm_slope_right'] = self._create_spinbox(0.0, 1.0, 0.001, 4)
        self.inputs['bank_slope_right'] = self._create_spinbox(0.01, 100, 0.1)
        self.inputs['bank_width_right'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['floodplain_width_right'] = self._create_spinbox(0, 1000, 0.1)
        self.inputs['floodplain_slope_right'] = self._create_spinbox(0.0, 1.0, 0.001, 4)
        grp_right = self._build_side_groupbox(
            "Droite",
            banquette_rows=[
                ("Banquette D (m):", self.inputs['berm_width_right']),
                ("Pente Banquette D (m/m):", self.inputs['berm_slope_right']),
            ],
            berge_rows=[
                ("Pente Berge D (H/V):", self.inputs['bank_slope_right']),
                ("Largeur Berge D (m):", self.inputs['bank_width_right']),
            ],
            floodplain_rows=[
                ("Largeur Lit majeur D (m):", self.inputs['floodplain_width_right']),
                ("Pente Lit majeur D (m/m):", self.inputs['floodplain_slope_right']),
            ],
        )

        row_sides.addWidget(grp_left, stretch=1)
        row_sides.addWidget(grp_right, stretch=1)
        layout.addLayout(row_sides)

        # --- Raccord au terrain naturel (optionnel, de chaque côté) ---
        grp_connect = QGroupBox("Raccord au terrain naturel")
        # Grille à deux colonnes (gauche / droite) : chaque côté empile son bouton de
        # raccord, son bouton de retrait et le rappel du point raccordé, pour que ce rappel
        # reste sous le bouton du côté concerné (même quand un seul côté est raccordé).
        layout_connect = QGridLayout(grp_connect)
        layout_connect.setHorizontalSpacing(theme.SPACE_SM)
        layout_connect.setVerticalSpacing(theme.SPACE_SM)
        layout_connect.setColumnStretch(0, 1)
        layout_connect.setColumnStretch(1, 1)

        self.btn_pick_connect_left = QPushButton("Raccord gauche")
        self.btn_pick_connect_left.clicked.connect(lambda: self._pick_connect_point('left'))
        self.btn_pick_connect_right = QPushButton("Raccord droit")
        self.btn_pick_connect_right.clicked.connect(lambda: self._pick_connect_point('right'))

        self.btn_remove_connect_left = QPushButton("Retirer le raccord")
        self.btn_remove_connect_left.clicked.connect(lambda: self._remove_connect_point('left'))
        self.btn_remove_connect_right = QPushButton("Retirer le raccord")
        self.btn_remove_connect_right.clicked.connect(lambda: self._remove_connect_point('right'))

        self.lbl_connect_confirm_left = QLabel()
        self.lbl_connect_confirm_right = QLabel()

        for column, (btn_pick, btn_remove, lbl) in enumerate((
            (self.btn_pick_connect_left, self.btn_remove_connect_left, self.lbl_connect_confirm_left),
            (self.btn_pick_connect_right, self.btn_remove_connect_right, self.lbl_connect_confirm_right),
        )):
            btn_pick.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            btn_remove.setVisible(False)
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            lbl.setStyleSheet(theme.qss("font-size: ${FONT_SIZE_SM}px; color: $TEXT_MUTED;"))
            lbl.setVisible(False)
            layout_connect.addWidget(btn_pick, 0, column)
            layout_connect.addWidget(btn_remove, 1, column)
            layout_connect.addWidget(lbl, 2, column)

        layout.addWidget(grp_connect)

        self.chk_overlay = QCheckBox("Afficher le profil existant en fond (vert)")
        self.chk_overlay.stateChanged.connect(self.on_value_changed)
        row_overlay = QHBoxLayout()
        row_overlay.setContentsMargins(theme.SPACE_SM, 0, 0, 0)
        row_overlay.addWidget(self.chk_overlay)
        row_overlay.addStretch()
        layout.addLayout(row_overlay)

        # Export Excel : le classeur est écrit par MainWindow, qui connaît le profil ouvert
        # (noms du projet, du scénario et du profil, repris dans le fichier).
        self.btn_export_excel = QPushButton("Exporter le profil projet (Excel)...")
        self.btn_export_excel.setToolTip(
            "Points du profil projet (X, Z, nom du point) et paramètres de géométrie, dans un fichier .xlsx."
        )
        self.btn_export_excel.clicked.connect(self.export_excel_requested.emit)
        layout.addWidget(self.btn_export_excel)

        # Sans ce stretch final, le QVBoxLayout distribue l'espace restant du QScrollArea
        # en étirant chaque QGroupBox au lieu de le laisser vide en bas.
        layout.addStretch()

        scroll.setWidget(widget)
        self.main_layout.addWidget(scroll)

    def get_data(self) -> dict:
        data = {key: sb.value() for key, sb in self.inputs.items()}
        data['show_overlay_project'] = self.chk_overlay.isChecked()
        data['connect_x_left'], data['connect_z_left'] = self._connect_left or (None, None)
        data['connect_x_right'], data['connect_z_right'] = self._connect_right or (None, None)
        return data

    def set_data(self, data: dict):
        self._is_loading = True

        for key, value in data.items():
            if key in self.inputs:
                self.inputs[key].setValue(float(value))

        # Clé propre à cet onglet ; un profil enregistré avant la séparation n'a que
        # l'ancienne clé commune "show_overlay", qui sert alors de valeur initiale.
        self.chk_overlay.setChecked(bool(data.get('show_overlay_project', data.get('show_overlay', False))))
        # Simple repère visuel ponctuel de la session : il ne fait pas partie des
        # données sauvegardées, donc il se réinitialise à chaque rechargement de profil.
        self._anchored_values = None
        self.lbl_anchor_confirm.setVisible(False)

        cx_l, cz_l = data.get('connect_x_left'), data.get('connect_z_left')
        self._connect_left = (cx_l, cz_l) if cx_l is not None and cz_l is not None else None
        self._update_connect_ui('left')

        cx_r, cz_r = data.get('connect_x_right'), data.get('connect_z_right')
        self._connect_right = (cx_r, cz_r) if cx_r is not None and cz_r is not None else None
        self._update_connect_ui('right')

        self._last_valid_values = {key: sb.value() for key, sb in self.inputs.items()}
        self._is_loading = False

    def set_existing_points(self, existing_data: list):
        """Reçoit les points du profil existant (MainWindow), pour permettre de
        choisir directement l'un d'eux comme point d'ancrage."""
        self._existing_points = existing_data

    def _choose_existing_point(self, title: str):
        """Fait choisir un point du profil existant dans une liste défilante (les points
        peuvent être nombreux). Retourne (x, z), ou None si aucun point n'est disponible
        ou si l'utilisateur annule."""
        if not self._existing_points:
            QMessageBox.information(
                self, "Aucun point disponible",
                "Renseignez d'abord des points dans l'onglet Profil existant."
            )
            return None

        points = sorted(
            (pt["X (m)"], pt["Z (m NGF)"]) for pt in self._existing_points
        )
        items = [f"X = {x:.2f} m  |  Z = {z:.2f} m NGF" for x, z in points]

        dialog = PointPickerDialog(self, title, "Point (X, Z) :", items)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        index = dialog.selected_index()
        return points[index] if index is not None else None

    def _pick_anchor_point(self):
        point = self._choose_existing_point("Choisir un point d'ancrage")
        if point is None:
            return
        x, z = point

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
        # Valeurs relues sur les spinboxes (arrondies à leur précision), pas celles du
        # point : c'est à elles que les saisies suivantes seront comparées.
        self._anchored_values = (self.inputs['anchor_x'].value(), self.inputs['anchor_z'].value())

        self.on_value_changed()

    def _refresh_anchor_confirm(self):
        """Affiche "Ancré sur le point existant" seulement si l'ancrage correspond encore
        au point choisi : une modification de X ou de Z le rend faux, on le masque."""
        current = (self.inputs['anchor_x'].value(), self.inputs['anchor_z'].value())
        self.lbl_anchor_confirm.setVisible(
            self._anchored_values is not None and current == self._anchored_values
        )

    def _pick_connect_point(self, side: str):
        title = "Choisir le point de raccord gauche" if side == 'left' else "Choisir le point de raccord droit"
        point = self._choose_existing_point(title)
        if point is None:
            return

        # Validé AVANT d'être enregistré, seul (l'autre côté n'entre pas en compte).
        if self._invalid_connect_side(**{side: point}) is not None:
            QMessageBox.warning(self, "Point de raccord invalide", CONNECT_POINT_ERRORS[side])
            return

        if side == 'left':
            self._connect_left = point
        else:
            self._connect_right = point

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

    def _invalid_connect_side(self, left=None, right=None) -> str | None:
        """Côté dont le raccord ((x, z), ou None si absent) serait invalide avec les
        valeurs ACTUELLES des spinboxes (point plus proche de l'axe du lit que le bout du
        lit majeur, ou à défaut le haut de berge), ou None. La règle n'est définie que
        dans core.geometry.invalid_connect_side."""
        cx_l, cz_l = left or (None, None)
        cx_r, cz_r = right or (None, None)
        params = ProjectParameters(
            **{key: sb.value() for key, sb in self.inputs.items()},
            connect_x_left=cx_l, connect_z_left=cz_l,
            connect_x_right=cx_r, connect_z_right=cz_r,
        )
        return invalid_connect_side(params)

    def _restore_last_valid_values(self):
        if self._last_valid_values is None:
            return
        self._is_loading = True
        for key, value in self._last_valid_values.items():
            if key in self.inputs:
                self.inputs[key].setValue(value)
        self._is_loading = False

    def _handle_invalid_connect(self, side: str):
        """La dernière saisie rend le raccord {side} invalide : on propose soit
        d'annuler la saisie (retour à la valeur juste avant), soit de retirer ce
        raccord pour conserver la nouvelle valeur. Le graphique n'est pas touché
        tant que l'utilisateur n'a pas choisi : il continue d'afficher le dernier
        état valide."""
        side_label = "gauche" if side == 'left' else "droit"

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Modification refusée")
        box.setText(
            f"Cette modification placerait le point de raccord {side_label} plus "
            "proche de l'axe du lit que le bout du lit majeur (ou le haut de berge) "
            "actuel — géométrie invalide."
        )
        btn_cancel = box.addButton("Annuler la modification", QMessageBox.ButtonRole.RejectRole)
        btn_remove = box.addButton("Retirer le raccord", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(btn_cancel)
        box.exec()

        if box.clickedButton() is btn_remove:
            self._remove_connect_point(side)
        else:
            self._restore_last_valid_values()

    def on_value_changed(self):
        if self._is_loading:
            return

        invalid_side = self._invalid_connect_side(self._connect_left, self._connect_right)
        if invalid_side is not None:
            self._handle_invalid_connect(invalid_side)
            # "Annuler la modification" a pu remettre l'ancrage sur le point choisi.
            self._refresh_anchor_confirm()
            return

        self._refresh_anchor_confirm()

        self._last_valid_values = {key: sb.value() for key, sb in self.inputs.items()}
        self.data_changed.emit(self.get_data())
