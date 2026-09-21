# ui/forms/existing_form.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
                               QPushButton, QLabel, QHeaderView, QApplication)
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QKeySequence

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
        super().keyPressEvent(event)


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

        self.lbl_hint = QLabel("Renseignez les points (X = distance, Z = altitude).")
        self.lbl_hint.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_SM}px; color: $TEXT_MUTED;"
        ))
        header_layout.addWidget(self.lbl_hint)

        self.main_layout.addLayout(header_layout)

        # Tableau de saisie
        self.table = _PasteableTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["X (m)", "Z (m NGF)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.main_layout.addWidget(self.table)
        
        self.btn_add_row = QPushButton("Ajouter un point")
        self.main_layout.addWidget(self.btn_add_row)
        
        # Connexions
        self.btn_add_row.clicked.connect(self.add_row)
        self.table.itemChanged.connect(self.on_item_changed)
        
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
        
    def get_data(self) -> list:
        """Extrait les données de la table sous forme de liste de dictionnaires."""
        data = []
        for row in range(self.table.rowCount()):
            # Sécurisation : on vérifie que les cellules existent bien
            item_x = self.table.item(row, 0)
            item_z = self.table.item(row, 1)
            
            if not item_x or not item_z:
                continue
                
            # Nettoyage des espaces et remplacement de la virgule française
            str_x = item_x.text().strip().replace(',', '.')
            str_z = item_z.text().strip().replace(',', '.')
            
            # On ignore les lignes en cours de saisie (vides)
            if not str_x or not str_z:
                continue
                
            try:
                x = float(str_x)
                z = float(str_z)
                data.append({"X (m)": x, "Z (m NGF)": z})
            except ValueError:
                # TODO UX : Mettre la cellule en rouge si la valeur n'est pas un nombre valide
                continue
                
        return data
        
    def set_data(self, data: list):
        """Peuple la table à partir des données chargées depuis la base SQLite."""
        self._is_loading = True
        self.table.setRowCount(0)
        for i, point in enumerate(data):
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(str(point.get("X (m)", 0.0))))
            self.table.setItem(i, 1, QTableWidgetItem(str(point.get("Z (m NGF)", 0.0))))
        self._is_loading = False
        
    def on_item_changed(self, item=None):
        if not self._is_loading:
            self.data_changed.emit(self.get_data())

    def paste_from_clipboard(self):
        """Colle une grille TSV/CSV Excel dans la table, à partir de la cellule active
        (ou (0,0) si aucune sélection). Aucune validation ici : get_data() filtre déjà
        les valeurs non numériques au moment de l'extraction."""
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