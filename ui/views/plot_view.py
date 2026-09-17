# ui/views/plot_view.py
import tempfile
from pathlib import Path

import plotly
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

def _get_or_create_plotly_cache_dir() -> tuple[Path, str]:
    """Écrit plotly.min.js sur disque (une fois par version) et renvoie
    (dossier de cache, nom du fichier JS).

    setHtml() a une limite de taille (~2 Mo côté Chromium/Qt) qui tronque
    silencieusement le JS de Plotly (plusieurs Mo) s'il est injecté inline.
    On passe donc par un vrai fichier local, chargé via load(), qui n'a pas
    cette limite.
    """
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
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.browser = QWebEngineView()
        self.main_layout.addWidget(self.browser)
        
        # --- NOUVEAU : Gestion de l'asynchronisme ---
        self._is_ready = False       # Vrai quand la page HTML est totalement chargée
        self._pending_fig = None     # Stocke le graphique en attente
        self.browser.loadFinished.connect(self.on_page_loaded)

        cache_dir, plotly_js_filename = _get_or_create_plotly_cache_dir()
        html_base = f"""
        
        
        <html>
        <head>
            <script type="text/javascript" src="{plotly_js_filename}"></script>
            <style>
                body {{ margin: 0; padding: 0; background-color: #ffffff; }}
                #graph {{ width: 100vw; height: 100vh; }}
                .empty-state {{ display:flex; justify-content:center; align-items:center; height:90vh; font-family:"Segoe UI", sans-serif; color:#adb5bd; font-size:14px; }}
            </style>
        </head>
        <body>
            <div id="graph">
                <div class="empty-state">Chargement du moteur graphique...</div>
            </div>
            
            <script>
                function updateGraph(figData) {{
                    var graphDiv = document.getElementById('graph');
                    var config = {{
                        displaylogo: false,
                        modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
                        displayModeBar: 'hover'
                    }};
                    Plotly.react(graphDiv, figData.data, figData.layout, config);
                }}
                
                function showEmptyState() {{
                    document.getElementById('graph').innerHTML = '<div class="empty-state">Données insuffisantes pour tracer le profil.</div>';
                }}
            </script>
        </body>
        </html>
        """

        # Le HTML lui-même reste petit : il peut passer par un fichier, à côté
        # de plotly.min.js pour que le <script src="..."> relatif se résolve.
        html_path = cache_dir / "index.html"
        html_path.write_text(html_base, encoding="utf-8")

        self.browser.load(QUrl.fromLocalFile(str(html_path)))
        
    def on_page_loaded(self, ok: bool):
        """Déclenché automatiquement par Qt quand le HTML a fini de charger."""
        if not ok:
            # Le chargement local a échoué (fichier manquant, permissions...) :
            # on ne bascule pas _is_ready pour ne pas exécuter du JS sur une page vide.
            return

        self._is_ready = True
        # Si un graphique attendait dans la file, on l'affiche maintenant
        if self._pending_fig is not None:
            self.update_plot(self._pending_fig)
            self._pending_fig = None

    def update_plot(self, fig):
        # Si la page n'est pas prête, on met la figure en attente et on s'arrête
        if not self._is_ready:
            self._pending_fig = fig
            return
            
        if fig is None:
            self.browser.page().runJavaScript("showEmptyState();")
            return
        
        # Sérialisation instantanée de la figure Python en texte JSON
        fig_json = fig.to_json()
        
        # Injection du JSON pur dans la fonction JavaScript
        self.browser.page().runJavaScript(f"updateGraph({fig_json});")