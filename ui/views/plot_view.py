# ui/views/plot_view.py
import plotly.io as pio
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

class PlotView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.browser = QWebEngineView()
        self.layout.addWidget(self.browser)
        
        # Pré-chauffage du moteur avec un design raccord au thème
        html_init = """
        <html>
        <body style='background-color:#ffffff; display:flex; justify-content:center; align-items:center; height:90vh; margin:0; font-family:"Segoe UI", sans-serif; color:#adb5bd; font-size:14px;'>
            <p>Sélectionnez un profil dans l'arborescence pour visualiser la géométrie</p>
        </body>
        </html>
        """
        self.browser.setHtml(html_init)
        
    def update_plot(self, fig):
        if fig is None:
            html_empty = """
            <html>
            <body style='background-color:#ffffff; display:flex; justify-content:center; align-items:center; height:90vh; margin:0; font-family:"Segoe UI", sans-serif; color:#adb5bd; font-size:14px;'>
                <p>Données insuffisantes pour tracer le profil.</p>
            </body>
            </html>
            """
            self.browser.setHtml(html_empty)
            return


        # Configuration épurée de la barre d'outils Plotly
        config = {
            'displaylogo': False,
            'modeBarButtonsToRemove': ['lasso2d', 'select2d', 'autoScale2d'],
            'displayModeBar': 'hover' # Apparaît uniquement au survol
        }
        
        html = pio.to_html(fig, include_plotlyjs='cdn', full_html=True, config=config)
        self.browser.setHtml(html)