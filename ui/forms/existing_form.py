# ui/forms/existing_form.py
import math

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
                               QPushButton, QLabel, QHeaderView, QApplication, QMenu)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QBrush, QColor, QKeySequence

from ui import theme


class _PasteableTableWidget(QTableWidget):
    """QTableWidget qui délègue Ctrl+C / Ctrl+V au formulaire parent
    (copier-coller depuis/vers Excel)."""

    def __init__(self, rows, cols, form):
        super().__init__(rows, cols)
        self._form = form

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self._form.paste_from_clipboard()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self._form.copy_selection_to_clipboard()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._form.delete_selected_rows()
            return
        super().keyPressEvent(event)


def _parse_value(text: str):
    """Lit une cellule (virgule française acceptée). Retourne (valeur, erreur) : valeur
    None si la cellule est vide ou invalide, erreur None si la cellule est valide ou vide.
    "nan" / "inf" sont refusés : float() les accepte, mais ils fausseraient les calculs."""
    text = text.strip().replace(',', '.')
    if not text:
        return None, None
    try:
        value = float(text)
    except ValueError:
        return None, "Valeur non numérique"
    if not math.isfinite(value):
        return None, "Valeur non numérique"
    return value, None


class ExistingProfileForm(QWidget):
    # Signal émis vers MainWindow quand les données changent (auto-save + maj graphique)
    data_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, theme.SPACE_MD, 0, 0)
        self.main_layout.setSpacing(theme.SPACE_MD)

        # Titre de section et texte d'aide séparés : ils portent deux niveaux typographiques
        # distincts, qu'un unique QLabel en HTML ne permettait pas de distinguer nettement.
        # Ils sont regroupés dans un layout serré pour rester lus comme un seul bloc.
        header_layout = QVBoxLayout()
        header_layout.setSpacing(theme.SPACE_XS)

        self.lbl_title = QLabel("Profil en travers existant")
        self.lbl_title.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_TITLE}px; font-weight: bold; color: $TEXT_SECONDARY;"
        ))
        header_layout.addWidget(self.lbl_title)

        self.lbl_hint = QLabel("Vous pouvez désormais copier-coller les valeurs des points.")
        self.lbl_hint.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_SM}px; color: red;"
        ))
        header_layout.addWidget(self.lbl_hint)

        self.main_layout.addLayout(header_layout)

        # Tableau de saisie
        self.table = _PasteableTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["X (m)", "Z (m NGF)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.main_layout.addWidget(self.table)

        # Signale les lignes ignorées (valeur invalide ou manquante) : sans lui, elles
        # disparaissaient des calculs sans que rien ne le dise.
        self.lbl_invalid = QLabel()
        self.lbl_invalid.setWordWrap(True)
        self.lbl_invalid.setStyleSheet(theme.qss("font-size: ${FONT_SIZE_SM}px; color: $DANGER;"))
        self.lbl_invalid.hide()
        self.main_layout.addWidget(self.lbl_invalid)

        self.btn_add_row = QPushButton("Ajouter un point")
        self.main_layout.addWidget(self.btn_add_row)
        
        # Connexions
        self.btn_add_row.clicked.connect(self.add_row)
        self.table.itemChanged.connect(self.on_item_changed)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_table_context_menu)

        # Verrou pour éviter les signaux multiples lors du chargement initial
        self._is_loading = False
        
    def add_row(self):
        row = self.table.rowCount()
        self._is_loading = True
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem("0.0"))
        self.table.setItem(row, 1, QTableWidgetItem("0.0"))
        self._is_loading = False
        self.on_item_changed()
        
    def _cell_text(self, row: int, col: int) -> str:
        item = self.table.item(row, col)
        return item.text() if item is not None else ""

    def _row_errors(self, row: int) -> dict:
        """Erreurs de la ligne, par colonne ({} si la ligne est valide ou entièrement vide).
        Une ligne à moitié remplie est en erreur : le point serait sinon ignoré sans bruit."""
        texts = [self._cell_text(row, col) for col in range(2)]
        if not any(t.strip() for t in texts):
            return {}
        errors = {}
        for col, text in enumerate(texts):
            _, error = _parse_value(text)
            if error is None and not text.strip():
                error = "Valeur manquante"
            if error is not None:
                errors[col] = error
        return errors

    def get_data(self) -> list:
        """Extrait les points valides de la table sous forme de liste de dictionnaires.
        Les lignes vides ou invalides sont ignorées (et signalées, cf. _refresh_validation)."""
        data = []
        for row in range(self.table.rowCount()):
            if self._row_errors(row):
                continue
            x, _ = _parse_value(self._cell_text(row, 0))
            z, _ = _parse_value(self._cell_text(row, 1))
            if x is None or z is None:
                continue  # ligne entièrement vide
            data.append({"X (m)": x, "Z (m NGF)": z})
        return data

    def _refresh_validation(self):
        """Met en rouge les cellules invalides (avec la cause en infobulle) et affiche sous
        le tableau les lignes ignorées. Signaux coupés : changer le fond d'une cellule émet
        itemChanged, ce qui relancerait sauvegarde et validation en boucle."""
        invalid_rows = []
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                errors = self._row_errors(row)
                if errors:
                    invalid_rows.append(row + 1)
                for col in range(2):
                    item = self.table.item(row, col)
                    if item is None:
                        if col not in errors:
                            continue
                        # Cellule jamais créée (ex. collage d'une seule colonne) : on la crée
                        # pour pouvoir la mettre en rouge.
                        item = QTableWidgetItem("")
                        self.table.setItem(row, col, item)
                    if col in errors:
                        item.setBackground(QBrush(QColor(theme.DANGER_LIGHT)))
                        item.setToolTip(f"{errors[col]} : ce point est ignoré.")
                    else:
                        item.setBackground(QBrush())
                        item.setToolTip("")
        finally:
            self.table.blockSignals(False)

        if len(invalid_rows) == 1:
            self.lbl_invalid.setText(
                f"Ligne {invalid_rows[0]} ignorée : valeur non numérique ou manquante. Ce point "
                "n'est ni pris en compte dans les calculs, ni enregistré : corrigez-le pour "
                "ne pas le perdre."
            )
        elif invalid_rows:
            self.lbl_invalid.setText(
                f"{len(invalid_rows)} lignes ignorées ({', '.join(map(str, invalid_rows))}) : "
                "valeur non numérique ou manquante. Ces points ne sont ni pris en compte dans "
                "les calculs, ni enregistrés : corrigez-les pour ne pas les perdre."
            )
        self.lbl_invalid.setVisible(bool(invalid_rows))

    def set_data(self, data: list):
        """Peuple la table à partir des données chargées depuis la base SQLite."""
        self._is_loading = True
        self.table.setRowCount(0)
        for i, point in enumerate(data):
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(str(point.get("X (m)", 0.0))))
            self.table.setItem(i, 1, QTableWidgetItem(str(point.get("Z (m NGF)", 0.0))))
        self._is_loading = False
        self._refresh_validation()

    def on_item_changed(self, item=None):
        if not self._is_loading:
            self._refresh_validation()
            self.data_changed.emit(self.get_data())

    def delete_selected_rows(self):
        """Supprime les lignes couvertes par la sélection courante (une ou plusieurs
        cellules). Ordre décroissant pour ne pas décaler les index pendant la boucle."""
        rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()), reverse=True)
        if not rows:
            return

        self._is_loading = True
        for row in rows:
            self.table.removeRow(row)
        self._is_loading = False

        self.on_item_changed()

    def open_table_context_menu(self, position):
        """Menu contextuel clic droit sur le tableau : suppression des lignes sélectionnées."""
        n_rows = len(set(idx.row() for idx in self.table.selectedIndexes()))
        label = "Supprimer les lignes sélectionnées" if n_rows > 1 else "Supprimer la ligne sélectionnée"

        menu = QMenu(self.table)
        delete_action = menu.addAction(label)
        delete_action.setEnabled(n_rows > 0)

        action = menu.exec(self.table.viewport().mapToGlobal(position))
        if action == delete_action:
            self.delete_selected_rows()

    def paste_from_clipboard(self):
        """Colle une grille TSV/CSV Excel dans la table, à partir de la cellule active
        (ou (0,0) si aucune sélection). Aucune validation ici : get_data() filtre déjà
        les valeurs non numériques, et on_item_changed() les signale en rouge."""
        text = QApplication.clipboard().text()
        if not text:
            return

        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        while lines and lines[-1] == '':
            lines.pop()
        if not lines:
            return
        rows = [line.split('\t') for line in lines]

        current = self.table.currentIndex()
        start_row = current.row() if current.isValid() else 0
        start_col = current.column() if current.isValid() else 0
        n_cols = self.table.columnCount()

        self._is_loading = True
        try:
            for i, row_values in enumerate(rows):
                target_row = start_row + i
                if target_row >= self.table.rowCount():
                    self.table.insertRow(self.table.rowCount())
                for j, value in enumerate(row_values):
                    target_col = start_col + j
                    if target_col >= n_cols:
                        break
                    self.table.setItem(target_row, target_col, QTableWidgetItem(value.strip()))
        finally:
            self._is_loading = False

        self.on_item_changed()

    def copy_selection_to_clipboard(self):
        """Exporte la sélection rectangulaire courante en TSV brut (sans en-têtes)."""
        selected = self.table.selectedIndexes()
        if not selected:
            return

        rows = sorted(set(idx.row() for idx in selected))
        cols = sorted(set(idx.column() for idx in selected))

        lines = []
        for r in rows:
            cells = []
            for c in cols:
                item = self.table.item(r, c)
                cells.append(item.text() if item else "")
            lines.append('\t'.join(cells))

        QApplication.clipboard().setText('\n'.join(lines))