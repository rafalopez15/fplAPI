from src.util.fpl_service import FplService


def get_teams():
    teams = FplService().fpl_data.get("teams")
    return teams


def get_team_by_name(name: str):
    teams = get_teams()
    for team in teams:
        if team.get("name") == name:
            return team

    return None
