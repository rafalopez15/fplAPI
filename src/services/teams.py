from src.util.fpl_service import FplService


def get_teams():
    """Return all Premier League teams as the raw dicts FPL sends."""
    teams = FplService().get_data("teams")
    return teams


def get_team_by_name(name: str):
    """Return the team whose name matches exactly, or None.

    Matching is case-sensitive and uses FPL's names, such as "Man City" rather
    than "Manchester City".
    """
    teams = get_teams()
    for team in teams:
        if team.get("name") == name:
            return team

    return None
