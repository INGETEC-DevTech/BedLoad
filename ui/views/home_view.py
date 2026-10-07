# ui/views/home_view.py
"""Page d'accueil, affichée à la place de toute la zone de travail quand rien n'est
sélectionné (au lancement, ou quand l'élément ouvert vient d'être supprimé ou archivé) :
logo et nom de l'application, actions rapides et projets récents."""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from ui import theme

APP_NAME = "BedLoad"
# Nombre de projets proposés dans « Projets récents ».
RECENT_PROJECTS_COUNT = 5

# Largeur maximale du contenu : centré en plein écran plutôt qu'étiré sur toute la largeur.
_CONTENT_MAX_WIDTH = 680
_LOGO_HEIGHT = 26
_SECTION_GAP = theme.SPACE_XL + theme.SPACE_SM

# Les libellés posés sur une carte blanche doivent rester transparents : la feuille de
# style globale donne à tout QWidget le fond gris de la fenêtre.
_TRANSPARENT = "background: transparent;"


def format_last_modified(moment: Optional[datetime], now: datetime) -> str:
    """« Modifié aujourd'hui à 14:32 », « Modifié hier à 09:05 », puis seulement la date
    (« Modifié le 12/09/2026 »). `moment` et `now` doivent être dans le même fuseau."""
    if moment is None:
        return ""
    if moment.date() == now.date():
        return f"Modifié aujourd'hui à {moment:%H:%M}"
    if moment.date() == now.date() - timedelta(days=1):
        return f"Modifié hier à {moment:%H:%M}"
    return f"Modifié le {moment:%d/%m/%Y}"


def _logo_pixmap(path: Path, height: int, device_pixel_ratio: float) -> QPixmap:
    """Logo à `height` px logiques, rééchantillonné pour l'écran (net en 125 % / 150 %).
    Pixmap nulle si le fichier est introuvable ou illisible."""
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return pixmap
    scaled = pixmap.scaledToHeight(
        round(height * device_pixel_ratio), Qt.TransformationMode.SmoothTransformation
    )
    scaled.setDevicePixelRatio(device_pixel_ratio)
    return scaled


class _RecentProjectRow(QAbstractButton):
    """Ligne cliquable d'un projet récent : nom à gauche (élidé s'il est trop long), date
    à droite. Dessinée à la main, comme les lignes de la barre latérale."""

    HEIGHT = 44
    _PADDING = theme.SPACE_MD
    _CHEVRON_WIDTH = theme.SPACE_LG

    def __init__(self, project_id: int, name: str, date_text: str, separator: bool, parent=None):
        super().__init__(parent)
        self.project_id = project_id
        self.date_text = date_text
        # Filet sous la ligne, sauf pour la dernière de la liste.
        self._separator = separator
        self.setText(name)
        self.setToolTip(f"Ouvrir le projet « {name} »")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        # Focus au clavier seulement (Tab, puis Espace) : un clic n'y laisse pas de cadre.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def sizeHint(self):
        return QSize(_CONTENT_MAX_WIDTH, self.HEIGHT)

    def minimumSizeHint(self):
        return QSize(240, self.HEIGHT)

    def _fonts(self):
        name_font = QFont(self.font())
        name_font.setPixelSize(theme.FONT_SIZE_VALUE)
        name_font.setWeight(QFont.Weight.DemiBold)
        date_font = QFont(self.font())
        date_font.setPixelSize(theme.FONT_SIZE_BASE)
        return name_font, date_font

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        painter.fillRect(rect, QColor(theme.SURFACE))

        hovered = self.underMouse()
        if self.isDown() or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.HOVER if self.isDown() else theme.SURFACE_ALT))
            painter.drawRoundedRect(rect.adjusted(0, 1, 0, -1), theme.RADIUS_SM, theme.RADIUS_SM)
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.BORDER_FOCUS)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 1.5, -0.5, -1.5), theme.RADIUS_SM, theme.RADIUS_SM)
        elif self._separator:
            painter.setPen(QPen(QColor(theme.BORDER)))
            y = rect.bottom() - 0.5
            painter.drawLine(int(rect.left() + self._PADDING), int(y), int(rect.right() - self._PADDING), int(y))

        name_font, date_font = self._fonts()
        right = rect.right() - self._PADDING

        # Chevron : signale que la ligne s'ouvre.
        painter.setFont(date_font)
        painter.setPen(QColor(theme.TEXT_MUTED))
        chevron_rect = QRectF(right - self._CHEVRON_WIDTH, rect.top(), self._CHEVRON_WIDTH, rect.height())
        painter.drawText(chevron_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "›")
        right -= self._CHEVRON_WIDTH + theme.SPACE_SM

        painter.setPen(QColor(theme.TEXT_SECONDARY))
        date_width = QFontMetrics(date_font).horizontalAdvance(self.date_text)
        date_rect = QRectF(right - date_width, rect.top(), date_width, rect.height())
        painter.drawText(date_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.date_text)

        left = rect.left() + self._PADDING
        name_width = max(0.0, date_rect.left() - theme.SPACE_LG - left)
        name = QFontMetrics(name_font).elidedText(self.text(), Qt.TextElideMode.ElideRight, int(name_width))
        painter.setFont(name_font)
        painter.setPen(QColor(theme.PRIMARY_TEXT if hovered else theme.TEXT_PRIMARY))
        painter.drawText(
            QRectF(left, rect.top(), name_width, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name,
        )


class HomeView(QWidget):
    # Actions rapides : MainWindow les relie aux boutons équivalents de la barre latérale.
    new_project_requested = pyqtSignal()
    import_requested = pyqtSignal()
    # Clic sur un projet récent (id du projet) : MainWindow le sélectionne dans l'arbre.
    project_activated = pyqtSignal(int)

    def __init__(self, logo_path: Path, parent=None):
        super().__init__(parent)
        self._rows: List[_RecentProjectRow] = []

        # Défilement si la fenêtre est trop basse pour tout afficher.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # Contenu en colonne centrée, un peu au-dessus du milieu de la page (1/3 - 2/3).
        page = QWidget()
        scroll.setWidget(page)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL, theme.SPACE_XL, theme.SPACE_XL)
        page_layout.addStretch(1)
        centering = QHBoxLayout()
        page_layout.addLayout(centering)
        page_layout.addStretch(2)

        column = QWidget()
        column.setMaximumWidth(_CONTENT_MAX_WIDTH)
        # Facteur élevé : la colonne prend toute la place jusqu'à sa largeur maximale, les
        # marges de part et d'autre ne récupérant que le surplus (d'où le centrage).
        centering.addStretch(1)
        centering.addWidget(column, 100)
        centering.addStretch(1)

        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- En-tête ---
        self.lbl_logo = QLabel()
        logo = _logo_pixmap(logo_path, _LOGO_HEIGHT, self.devicePixelRatioF())
        self.lbl_logo.setPixmap(logo)
        self.lbl_logo.setVisible(not logo.isNull())
        layout.addWidget(self.lbl_logo, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(theme.SPACE_LG)

        self.lbl_title = QLabel(APP_NAME)
        self.lbl_title.setStyleSheet(theme.qss(
            "font-size: 32px; font-weight: bold; color: $TEXT_PRIMARY;"
        ))
        layout.addWidget(self.lbl_title)
        layout.addSpacing(theme.SPACE_XS)

        hint = QLabel(
            "Choisissez un scénario pour son profil en long, ou un profil pour éditer son "
            "profil en travers."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.qss("font-size: ${FONT_SIZE_BASE}px; color: $TEXT_SECONDARY;"))
        layout.addWidget(hint)
        layout.addSpacing(_SECTION_GAP)

        # --- Actions rapides ---
        layout.addWidget(self._section_title("Actions rapides"))
        layout.addSpacing(theme.SPACE_SM)
        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE_SM)
        self.btn_new_project = self._action_button(
            "+ Nouveau Projet", theme.BUTTON_PRIMARY_QSS, "Crée un projet, avec un premier scénario."
        )
        self.btn_new_project.clicked.connect(self.new_project_requested.emit)
        actions.addWidget(self.btn_new_project)
        self.btn_import = self._action_button(
            "Importer...", theme.BUTTON_SECONDARY_QSS,
            "Importe un fichier .json exporté depuis HydroTopo (profil, scénario ou projet).",
        )
        self.btn_import.clicked.connect(self.import_requested.emit)
        actions.addWidget(self.btn_import)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addSpacing(_SECTION_GAP)

        # --- Projets récents ---
        self.lbl_recent = self._section_title("Projets récents")
        layout.addWidget(self.lbl_recent)
        layout.addSpacing(theme.SPACE_SM)

        self.recent_card = self._card()
        self._recent_layout = QVBoxLayout(self.recent_card)
        self._recent_layout.setContentsMargins(theme.SPACE_XS, theme.SPACE_XS, theme.SPACE_XS, theme.SPACE_XS)
        self._recent_layout.setSpacing(0)
        layout.addWidget(self.recent_card)

        # Carte affichée à la place de la liste quand il n'y a aucun projet actif.
        self.empty_card = self._card()
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL, theme.SPACE_XL, theme.SPACE_XL)
        empty_layout.setSpacing(theme.SPACE_XS)
        self.lbl_empty_title = QLabel()
        self.lbl_empty_title.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_TITLE}px; font-weight: bold; color: $TEXT_PRIMARY;" + _TRANSPARENT
        ))
        empty_layout.addWidget(self.lbl_empty_title)
        self.lbl_empty_text = QLabel()
        self.lbl_empty_text.setWordWrap(True)
        self.lbl_empty_text.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_BASE}px; color: $TEXT_SECONDARY;" + _TRANSPARENT
        ))
        empty_layout.addWidget(self.lbl_empty_text)
        layout.addWidget(self.empty_card)

        self.set_recent_projects([], archived_count=0)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        """Titre de section : même niveau typographique que les titres de QGroupBox."""
        label = QLabel(text)
        label.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_TITLE}px; font-weight: bold; color: $TEXT_SECONDARY;"
        ))
        return label

    @staticmethod
    def _action_button(text: str, qss: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setStyleSheet(qss)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumWidth(160)
        return button

    @staticmethod
    def _card() -> QFrame:
        card = QFrame()
        card.setObjectName("homeCard")
        card.setStyleSheet(theme.qss(
            "QFrame#homeCard { background-color: $SURFACE; border: 1px solid $BORDER;"
            " border-radius: ${RADIUS_MD}px; }"
        ))
        return card

    def set_recent_projects(self, projects: List[Dict], archived_count: int, now: Optional[datetime] = None):
        """Projets récents ({id, name, last_modified}, du plus récent au plus ancien, cf.
        DatabaseManager.get_recent_projects). Sans projet actif, une invitation à créer le
        premier projet — ou, si des projets sont archivés, un rappel qu'ils y sont."""
        now = now or datetime.now().astimezone()
        # Suppression différée : la ligne cliquée peut être en train d'émettre son signal.
        while self._recent_layout.count():
            widget = self._recent_layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._rows = []
        for i, project in enumerate(projects):
            row = _RecentProjectRow(
                project["id"], project["name"], format_last_modified(project["last_modified"], now),
                separator=i < len(projects) - 1,
            )
            row.clicked.connect(lambda _=False, pid=project["id"]: self.project_activated.emit(pid))
            self._recent_layout.addWidget(row)
            self._rows.append(row)

        if not projects:
            if archived_count:
                self.lbl_empty_title.setText("Aucun projet actif")
                archived = (f"Vos {archived_count} projets archivés restent accessibles" if archived_count > 1
                            else "Votre projet archivé reste accessible")
                self.lbl_empty_text.setText(
                    f"{archived} depuis le bouton « Archives » de la barre latérale, ou créez "
                    "un nouveau projet avec « + Nouveau Projet »."
                )
            else:
                self.lbl_empty_title.setText("Aucun projet pour l'instant")
                self.lbl_empty_text.setText(
                    "Créez votre premier projet avec « + Nouveau Projet », ou importez un "
                    "projet existant avec « Importer... »."
                )
        self.recent_card.setVisible(bool(projects))
        self.empty_card.setVisible(not projects)
