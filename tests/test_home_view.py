"""Page d'accueil : dates des projets récents, liste cliquable, actions rapides et message
quand il n'y a aucun projet. Qt tourne en mode "offscreen" : aucune fenêtre ne s'affiche."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta

import pytest
from PyQt6.QtWidgets import QApplication

from core.utils import LOGO_FILE_NAME, get_assets_dir
from ui.views.home_view import HomeView, format_last_modified

NOW = datetime(2026, 10, 7, 15, 0)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(qapp):
    view = HomeView(get_assets_dir() / LOGO_FILE_NAME)
    yield view
    view.deleteLater()


@pytest.mark.parametrize("moment, expected", [
    (datetime(2026, 10, 7, 9, 5), "Modifié aujourd'hui à 09:05"),
    (datetime(2026, 10, 6, 23, 59), "Modifié hier à 23:59"),
    (datetime(2026, 10, 5, 12, 0), "Modifié le 05/10/2026"),
    (None, ""),
])
def test_last_modified_is_relative_for_today_and_yesterday_only(moment, expected):
    assert format_last_modified(moment, NOW) == expected


def test_yesterday_is_recognised_across_a_month_boundary():
    assert format_last_modified(datetime(2026, 9, 30, 18, 0), datetime(2026, 10, 1, 8, 0)) \
        == "Modifié hier à 18:00"


def test_recent_projects_are_listed_in_order_and_open_on_click(home):
    activated = []
    home.project_activated.connect(activated.append)

    home.set_recent_projects([
        {"id": 7, "name": "Rivière", "last_modified": NOW - timedelta(hours=1)},
        {"id": 3, "name": "Torrent", "last_modified": NOW - timedelta(days=3)},
    ], archived_count=0, now=NOW)

    assert [(row.text(), row.date_text) for row in home._rows] == [
        ("Rivière", "Modifié aujourd'hui à 14:00"),
        ("Torrent", "Modifié le 04/10/2026"),
    ]
    assert not home.recent_card.isHidden() and home.empty_card.isHidden()
    home._rows[1].click()
    assert activated == [3]


def test_refreshing_replaces_the_previous_rows(home):
    home.set_recent_projects([{"id": 1, "name": "A", "last_modified": NOW}], archived_count=0, now=NOW)
    home.set_recent_projects([{"id": 2, "name": "B", "last_modified": NOW}], archived_count=0, now=NOW)

    assert [row.text() for row in home._rows] == ["B"]
    assert home._recent_layout.count() == 1


def test_without_any_project_invites_to_create_the_first_one(home):
    home.set_recent_projects([], archived_count=0)

    assert home.recent_card.isHidden() and not home.empty_card.isHidden()
    assert home.lbl_empty_title.text() == "Aucun projet pour l'instant"
    assert "premier projet" in home.lbl_empty_text.text()


@pytest.mark.parametrize("count, expected", [
    (1, "Votre projet archivé reste accessible"),
    (3, "Vos 3 projets archivés restent accessibles"),
])
def test_with_only_archived_projects_points_to_the_archives(home, count, expected):
    home.set_recent_projects([], archived_count=count)

    assert home.lbl_empty_title.text() == "Aucun projet actif"
    assert home.lbl_empty_text.text().startswith(expected)
    assert "« Archives »" in home.lbl_empty_text.text()


def test_quick_actions_emit_their_signals(home):
    received = []
    home.new_project_requested.connect(lambda: received.append("new"))
    home.import_requested.connect(lambda: received.append("import"))

    home.btn_new_project.click()
    home.btn_import.click()

    assert received == ["new", "import"]


def test_logo_is_hidden_when_its_file_is_missing(qapp, tmp_path):
    with_logo = HomeView(get_assets_dir() / LOGO_FILE_NAME)
    without_logo = HomeView(tmp_path / "absent.png")

    assert not with_logo.lbl_logo.isHidden()
    assert without_logo.lbl_logo.isHidden()


def test_a_long_project_name_is_drawn_without_error_in_a_narrow_row(home):
    home.set_recent_projects(
        [{"id": 1, "name": "Restauration du lit mineur " * 10, "last_modified": NOW}],
        archived_count=0, now=NOW,
    )
    row = home._rows[0]
    row.resize(260, row.HEIGHT)

    assert not row.grab().isNull()
