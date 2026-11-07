# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""Net points per transfer: the rules (services/transfer_points.py) and /transfers."""

import logging
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy.exc import OperationalError
from src.db.models import ElementEventPoints
from src.services import managers
from src.services.transfer_points import PointsData, load_points, with_net_points
from src.util import fpl_client

MID, FWD = 3, 4


def transfer(element_in, element_out, event, minute=0, **overrides):
    """An FPL transfers row; minute orders rows within a gameweek."""
    return {
        "element_in": element_in,
        "element_out": element_out,
        "event": event,
        "time": f"2026-10-{event:02d}T10:{minute:02d}:00.000000Z",
        "entry": 1,
        "element_in_cost": 50,
        "element_out_cost": 45,
        **overrides,
    }


def data(points, latest=9, types=None):
    """PointsData from {element: {event: points}}. Players 10-19 are MIDs, 20-29
    FWDs."""
    return PointsData(
        element_types=types or {e: MID if e < 20 else FWD for e in range(10, 30)},
        points={
            (e, ev): p for e, by_event in points.items() for ev, p in by_event.items()
        },
        latest_event=latest,
    )


def by_pair(rows):
    return {(r["element_in"], r["element_out"], r["event"]): r for r in rows}


def net(row):
    return row.get("points_in"), row.get("points_out"), row.get("net_points")


# --- rules ---------------------------------------------------------------------


def test_player_still_owned_counts_up_to_the_latest_gameweek():
    row = with_net_points(
        [transfer(10, 11, 8)], set(), data({10: {8: 5, 9: 7}, 11: {8: 2, 9: 1}})
    )[0]
    assert row["is_churn"] is False
    assert net(row) == (12, 3, 9)


def test_player_sold_later_counts_until_the_gameweek_before():
    rows = by_pair(
        with_net_points(
            [
                transfer(12, 10, 9),
                transfer(10, 11, 8),
            ],  # newest first, as FPL lists them
            set(),
            data({10: {8: 5, 9: 7}, 11: {8: 2, 9: 1}, 12: {9: 3}}),
        )
    )
    assert net(rows[(10, 11, 8)]) == (5, 2, 3)  # gameweek 8 only
    assert net(rows[(12, 10, 9)]) == (3, 7, -4)


def test_players_with_no_stored_points_count_zero():
    row = with_net_points([transfer(10, 11, 8)], set(), data({10: {8: 5}}))[0]
    assert net(row) == (5, 0, 5)


@pytest.mark.parametrize("latest", [9, None])
def test_points_are_null_until_the_first_gameweek_is_stored(latest):
    row = with_net_points([transfer(10, 11, 10)], set(), data({}, latest=latest))[0]
    assert row["is_churn"] is False
    assert net(row) == (None, None, None)


def test_free_hit_transfer_covers_its_gameweek_only():
    rows = by_pair(
        with_net_points(
            [transfer(12, 11, 8), transfer(11, 13, 7)],
            {8},  # gameweek 8 was a Free Hit
            data({11: {7: 1, 8: 2, 9: 4}, 12: {8: 6, 9: 9}, 13: {7: 3, 8: 3, 9: 3}}),
        )
    )
    assert net(rows[(12, 11, 8)]) == (6, 2, 4)  # not gameweek 9: the squad reverted
    # Selling 11 on the Free Hit doesn't end the gameweek 7 transfer: 7 to 9.
    assert net(rows[(11, 13, 7)]) == (7, 9, -2)


def test_wildcard_churn_is_flagged_and_the_real_change_is_built():
    # Bought 10 for 11, then changed mind and bought 12 for 10: really 12 for 11.
    rows = with_net_points(
        [
            transfer(12, 10, 8, minute=5, element_in_cost=60),
            transfer(10, 11, 8, minute=1, element_out_cost=44),
        ],
        set(),
        data({10: {8: 9}, 11: {8: 2}, 12: {8: 6}}),
    )
    churn = [(r["element_in"], r["element_out"]) for r in rows if r["is_churn"]]
    assert churn == [(12, 10), (10, 11)]
    [built] = [r for r in rows if not r["is_churn"]]
    assert (built["element_in"], built["element_out"], built["event"]) == (12, 11, 8)
    assert built["time"] == "2026-10-08T10:05:00.000000Z"  # when 12 was bought
    assert (built["element_in_cost"], built["element_out_cost"]) == (60, 44)
    assert net(built) == (6, 2, 4)
    assert all(net(r) == (None, None, None) for r in rows if r["is_churn"])


def test_unpaired_changes_are_matched_within_a_position():
    # Two churned swaps leave MID 12 for MID 11 and FWD 22 for FWD 21.
    rows = with_net_points(
        [
            transfer(22, 10, 8, minute=4),
            transfer(12, 20, 8, minute=3),
            transfer(20, 21, 8, minute=2),
            transfer(10, 11, 8, minute=1),
        ],
        set(),
        data({}),
    )
    built = {(r["element_in"], r["element_out"]) for r in rows if not r["is_churn"]}
    assert built == {(12, 11), (22, 21)}


def test_real_pair_rows_in_a_chip_week_are_kept_as_they_are():
    rows = with_net_points(
        [
            transfer(12, 10, 8, minute=3),
            transfer(10, 13, 8, minute=2),
            transfer(14, 15, 8, minute=1),
        ],
        set(),
        data({}),
    )
    real = [(r["element_in"], r["element_out"]) for r in rows if not r["is_churn"]]
    assert sorted(real) == [(12, 13), (14, 15)]  # 14 for 15 is FPL's own row


def test_swap_undone_in_a_normal_week_is_all_churn():
    rows = with_net_points(
        [transfer(11, 10, 8, minute=2), transfer(10, 11, 8, minute=1)], set(), data({})
    )
    assert [r["is_churn"] for r in rows] == [True, True]


def test_without_points_data_an_unpairable_week_keeps_fpl_rows_as_they_are():
    # Pairing 12 for 11 needs positions. Flagging both rows as churn would hide
    # that change from the app, so neither is flagged.
    rows = with_net_points(
        [
            transfer(12, 10, 8, minute=5),
            transfer(10, 11, 8, minute=1),
            transfer(14, 15, 7),
        ],
        set(),
        None,
    )
    assert [(r["element_in"], r["is_churn"]) for r in rows] == [
        (12, False),
        (10, False),
        (14, False),
    ]
    assert all(net(r) == (None, None, None) for r in rows)


def test_without_points_data_churn_that_hides_nothing_is_still_flagged():
    rows = with_net_points(
        [
            transfer(12, 13, 8, minute=3),
            transfer(11, 10, 8, minute=2),
            transfer(10, 11, 8, minute=1),
        ],
        set(),
        None,
    )
    assert [(r["element_in"], r["is_churn"]) for r in rows] == [
        (12, False),
        (11, True),
        (10, True),
    ]


# --- database ------------------------------------------------------------------


@pytest.fixture
def points(seeded_session):
    """Stored gameweek 8 points for the seeded players: Saka 1, Haaland 2, Palmer 3."""
    seeded_session.add_all(
        [
            ElementEventPoints(element=1, event=8, total_points=2, minutes=90),
            ElementEventPoints(element=2, event=8, total_points=13, minutes=90),
            ElementEventPoints(element=3, event=8, total_points=None, minutes=0),
        ]
    )
    seeded_session.flush()
    return seeded_session


def test_load_points(points):
    result = load_points(points, {1, 3})
    assert result.element_types == {1: MID, 3: MID}
    assert result.points == {(1, 8): 2, (3, 8): 0}  # null points count as 0
    assert result.latest_event == 8


@pytest.fixture
def fpl(monkeypatch):
    mocks = {
        "fetch_manager_transfers": Mock(return_value=[transfer(3, 1, 8)]),
        "fetch_manager_history": Mock(return_value={"chips": []}),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(fpl_client, name, mock)
    return mocks


@pytest.mark.usefixtures("points")
def test_transfers_endpoint_includes_net_points(client, fpl):
    fpl["fetch_manager_transfers"].return_value = [
        transfer(3, 1, 8, minute=1),
        transfer(2, 3, 8, minute=2),
    ]
    body = client.get("/api/managers/1/transfers").json()
    assert [(t["element_in"], t["is_churn"], t["net_points"]) for t in body] == [
        (2, True, None),  # newest first: bought Palmer, then swapped him for Haaland
        (3, True, None),
    ]
    fpl["fetch_manager_transfers"].return_value = [transfer(2, 1, 8)]
    [row] = client.get("/api/managers/1/transfers").json()
    assert (row["points_in"], row["points_out"], row["net_points"]) == (13, 2, 11)


@pytest.mark.usefixtures("points")
def test_built_rows_are_sorted_newest_first(seeded_session, fpl):
    # Saka for Haaland, then Haaland for Palmer: really Palmer for Saka. The built
    # row takes the time Palmer was bought, so it sorts between the two churned rows.
    fpl["fetch_manager_transfers"].return_value = [
        transfer(3, 2, 8, minute=3),
        transfer(2, 1, 8, minute=1),
        transfer(4, 5, 7),
    ]
    result = managers.get_transfers(1, seeded_session)
    assert [(t.element_in, t.element_out, t.is_churn) for t in result] == [
        (3, 2, True),
        (3, 1, False),
        (2, 1, True),
        (4, 5, False),
    ]


def test_free_hits_come_from_the_managers_chips(points, fpl):
    points.add_all(
        [
            ElementEventPoints(element=1, event=9, total_points=1, minutes=90),
            ElementEventPoints(element=2, event=9, total_points=5, minutes=90),
        ]
    )
    points.flush()
    fpl["fetch_manager_transfers"].return_value = [transfer(2, 1, 8)]
    fpl["fetch_manager_history"].return_value = {
        "chips": [{"name": "freehit", "event": 8}, {"name": "wildcard", "event": 3}]
    }

    [row] = managers.get_transfers(1, points)
    # Gameweek 8 only (13 - 2). Without the Free Hit it would run to 9: 18 - 3.
    assert (row.points_in, row.points_out, row.net_points) == (13, 2, 11)
    fpl["fetch_manager_history"].assert_called_once_with(1)


@pytest.mark.usefixtures("fpl")
def test_transfers_still_load_when_the_database_is_down(caplog):
    session = MagicMock()
    session.execute.side_effect = OperationalError("SELECT", {}, Exception("refused"))
    with caplog.at_level(logging.WARNING):
        [row] = managers.get_transfers(1, session)
    assert (row.element_in, row.is_churn, row.net_points) == (3, False, None)
    assert "Transfer points unavailable" in caplog.text
