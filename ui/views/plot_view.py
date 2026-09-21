# ui/views/plot_view.py
import tempfile
from pathlib import Path

import plotly
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton

from ui import theme

def _get_or_create_plotly_cache_dir() -> tuple[Path, str]:
    cache_dir = Path(tempfile.gettempdir()) / "hydrotopo_plotly_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    js_path = cache_dir / f"plotly-{plotly.__version__}.min.js"
    if not js_path.exists():
        js_path.write_text(plotly.offline.get_plotlyjs(), encoding="utf-8")
    return cache_dir, js_path.name

class PlotView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(15)
        
        # --- EN-TÊTE ---
        self.header_layout = QHBoxLayout()
        self.lbl_title = QLabel("Visualisation de la coupe transversale")
        self.lbl_title.setStyleSheet(theme.qss(
            "font-size: 16px; font-weight: bold; color: $TEXT_PRIMARY;"
        ))
        self.header_layout.addWidget(self.lbl_title)
        
        self.header_layout.addStretch() 
        
        self.btn_export = QPushButton("📷 Exporter l'image")
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.setStyleSheet(theme.qss("""
            QPushButton { background-color: $SURFACE; color: $TEXT_SECONDARY; border: 1px solid $BORDER_INPUT; border-radius: ${RADIUS_MD}px; padding: 6px 12px; font-weight: bold; }
            QPushButton:hover { background-color: $BACKGROUND; border-color: $BORDER_HOVER; }
        """))
        self.header_layout.addWidget(self.btn_export)
        self.main_layout.addLayout(self.header_layout)
        
        # --- MOTEUR WEB ---
        self.browser = QWebEngineView()
        self.main_layout.addWidget(self.browser)
        
        self._is_ready = False
        self._pending_fig = None
        self.browser.loadFinished.connect(self.on_page_loaded)

        cache_dir, plotly_js_filename = _get_or_create_plotly_cache_dir()
        
        html_base = f"""
        <html>
        <head>
            <script type="text/javascript" src="{plotly_js_filename}"></script>
            <style>
                body {{ margin: 0; padding: 0; background-color: transparent; height: 100vh; overflow: hidden; }}
                #card {{ position: relative; width: 100%; height: 100%; background-color: {theme.SURFACE}; border-radius: 10px; border: 1px solid {theme.BORDER}; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05); overflow: hidden; }}
                #graph {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; }}
                #empty-state {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 2; display: flex; flex-direction: column; justify-content: center; align-items: center; background-color: {theme.SURFACE}; font-family: {theme.FONT_FAMILY}; color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_TITLE}px; }}
                .icon-placeholder {{ margin-bottom: 15px; opacity: 0.5; }}
            </style>
        </head>
        <body>
            <div id="card">
                <div id="graph"></div>
                <div id="empty-state">
                    <svg class="icon-placeholder" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M3 3v18h18"/><path d="M18 9l-5 5-4-4-4 4"/>
                    </svg>
                    <span id="empty-state-text">Chargement du moteur graphique...</span>
                </div>
            </div>
            <script>
                function updateGraph(figData) {{
                    try {{
                        if (typeof Plotly === 'undefined') return;
                        var graphDiv = document.getElementById('graph');
                        var config = {{ displaylogo: false, modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'], displayModeBar: 'hover' }};
                        Plotly.react(graphDiv, figData.data, figData.layout, config);
                        document.getElementById('graph').style.display = 'block';
                        document.getElementById('empty-state').style.display = 'none';
                    }} catch(err) {{
                        showEmptyState("Erreur d'affichage : " + err.message);
                    }}
                }}
                function showEmptyState(msg) {{
                    document.getElementById('graph').style.display = 'none';
                    document.getElementById('empty-state-text').innerHTML = msg || 'Données insuffisantes pour tracer le profil.';
                    document.getElementById('empty-state').style.display = 'flex';
                }}
            </script>
        </body>
        </html>
        """
        
        # Écriture du fichier et chargement (L'étape qui manquait !)
        html_path = cache_dir / "index.html"
        html_path.write_text(html_base, encoding="utf-8")
        self.browser.load(QUrl.fromLocalFile(str(html_path)))
        
    def on_page_loaded(self, ok: bool):
        if not ok: return
        self._is_ready = True
        
        # S'il y a un graphique en attente, on l'affiche. 
        # Sinon, on efface "Chargement..." pour afficher un texte d'accueil stylisé.
        if self._pending_fig is not None:
            self.update_plot(self._pending_fig)
            self._pending_fig = None
        else:
            self.browser.page().runJavaScript("showEmptyState('👈 Sélectionnez un projet ou un profil pour commencer');")

    def update_plot(self, fig):
        if not self._is_ready:
            self._pending_fig = fig
            return
            
        if fig is None:
            self.browser.page().runJavaScript("showEmptyState('Données insuffisantes pour tracer le profil.');")
            return
        
        fig_json = fig.to_json()
        self.browser.page().runJavaScript(f"updateGraph({fig_json});")