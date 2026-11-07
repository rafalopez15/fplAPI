"""Net points per transfer, from FPL's transfers list and the stored gameweek points.

In Wildcard and Free Hit gameweeks FPL's list records every swap the manager tried,
not only the final changes, e.g. 55 rows for one Free Hit. So each gameweek is
reduced to its real changes first: players bought more often than sold that
gameweek ("ins") and sold more often than bought ("outs"). A row pairing an in with
an out is a real transfer; every other row is churn (is_churn). Ins and outs that no
row pairs, which only happens in chip weeks, are paired by position, because the
squad always keeps 2 GK, 5 DEF, 5 MID and 3 FWD, and returned as rows built here.

A transfer of A in for B out, made for gameweek N, covers N until the gameweek
before A is sold again, or the latest stored gameweek. A Free Hit transfer covers
its gameweek only, and doesn't end an earlier one, because the squad reverts.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from src.db.models import Element, ElementEventPoints


@dataclass
class PointsData:
    """What the calculation needs from the database."""

    element_types: dict[int, int]  # element id -> position (1 GK ... 4 FWD)
    points: dict[tuple[int, int], int]  # (element, event) -> total_points
    latest_event: Optional[int]  # the newest gameweek with stored points


def load_points(session: Session, elements: set[int]) -> PointsData:
    """Load positions and stored points for these players. Raises SQLAlchemyError."""
    types = session.execute(
        select(Element.id, Element.element_type).where(Element.id.in_(elements))
    )
    rows = session.execute(
        select(
            ElementEventPoints.element,
            ElementEventPoints.event,
            ElementEventPoints.total_points,
        ).where(ElementEventPoints.element.in_(elements))
    )
    return PointsData(
        element_types=dict(types.all()),
        points={(element, event): points or 0 for element, event, points in rows},
        latest_event=session.scalar(select(func.max(ElementEventPoints.event))),
    )


def _real_changes(rows: list[dict]) -> tuple[dict[int, dict], dict[int, dict]]:
    """One gameweek's real ins and outs, each mapped to the row of its last buy or sell.

    rows are newest first, as FPL lists them, so the first row seen is the last one.
    """
    balance = Counter()
    for row in rows:
        balance[row["element_in"]] += 1
        balance[row["element_out"]] -= 1
    ins, outs = {}, {}
    for row in rows:
        if balance[row["element_in"]] > 0:
            ins.setdefault(row["element_in"], row)
        if balance[row["element_out"]] < 0:
            outs.setdefault(row["element_out"], row)
    return ins, outs


def _pair_by_position(ins, outs, element_types) -> list[dict]:
    """Rows for real changes no FPL row pairs: earliest bought with earliest sold."""
    by_position = defaultdict(lambda: ([], []))
    for element, row in sorted(ins.items(), key=lambda item: item[1]["time"]):
        by_position[element_types.get(element)][0].append((element, row))
    for element, row in sorted(outs.items(), key=lambda item: item[1]["time"]):
        by_position[element_types.get(element)][1].append((element, row))
    return [
        {
            **bought,
            "element_out": sold_element,
            "element_out_cost": sold.get("element_out_cost"),
        }
        for position_ins, position_outs in by_position.values()
        for (_, bought), (sold_element, sold) in zip(position_ins, position_outs)
    ]


def _gameweek(rows: list[dict], data: Optional[PointsData]) -> tuple[list, list, set]:
    """One gameweek's rows with is_churn, its real transfers, and the players sold."""
    ins, outs = _real_changes(rows)
    flagged, real = [], []
    for row in rows:
        is_real = row["element_in"] in ins and row["element_out"] in outs
        row = {**row, "is_churn": not is_real}
        if is_real:
            # Each real change is paired once: later rows with it are churn.
            del ins[row["element_in"]], outs[row["element_out"]]
            real.append(row)
        flagged.append(row)
    sold = set(outs) | {row["element_out"] for row in real}
    if data is not None:
        built = [
            {**row, "is_churn": False}
            for row in _pair_by_position(ins, outs, data.element_types)
        ]
        real.extend(built)
        flagged.extend(built)
    elif ins or outs:
        # Pairing needs positions from the database. Without them, flagging churn
        # would hide real changes, so this gameweek shows FPL's rows as they are.
        flagged = [{**row, "is_churn": False} for row in rows]
    return flagged, real, sold


def with_net_points(
    transfers: list[dict], free_hits: set[int], data: Optional[PointsData]
) -> list[dict]:
    """FPL's transfer rows with is_churn and points, plus any rows built for chip weeks.

    data is None when the database couldn't be read: rows then keep is_churn, the
    points are null, and chip weeks get no built rows (they need positions).
    """
    by_event = defaultdict(list)
    for row in transfers:
        by_event[row["event"]].append(row)

    results, real, sold_in = [], [], defaultdict(list)
    for event, rows in by_event.items():
        flagged, gameweek_real, sold = _gameweek(rows, data)
        results.extend(flagged)
        real.extend(gameweek_real)
        if event not in free_hits:
            for element in sold:
                sold_in[element].append(event)

    for row in real:
        row.update(_points(row, free_hits, sold_in, data))
    return results


def _points(row, free_hits, sold_in, data) -> dict:
    """points_in, points_out and net_points for one real transfer, or nulls."""
    start = row["event"]
    if data is None or data.latest_event is None or start > data.latest_event:
        return {}
    if start in free_hits:
        end = start
    else:
        later_sales = [event for event in sold_in[row["element_in"]] if event > start]
        end = min(later_sales) - 1 if later_sales else data.latest_event
        end = min(end, data.latest_event)

    def total(element):
        return sum(
            data.points.get((element, event), 0) for event in range(start, end + 1)
        )

    points_in, points_out = total(row["element_in"]), total(row["element_out"])
    return {
        "points_in": points_in,
        "points_out": points_out,
        "net_points": points_in - points_out,
    }
