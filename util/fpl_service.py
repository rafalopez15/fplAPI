import requests


class FplService:
    def __init__(self):
        self.data = requests.get(
            "https://fantasy.premierleague.com/api/bootstrap-static/"
        ).json()

    def get_events(self):
        events = self.data.get("events")
        return events

    def get_event_by_id(self, id: int):
        events = self.get_events()
        for event in events:
            if event.get("id") == id:
                return event

        return None

    def get_teams(self):
        teams = self.data.get("teams")
        return teams

    def get_team_by_name(self, name: str):
        teams = self.get_teams()
        for team in teams:
            if team.get("name") == name:
                return team

        return None

    def get_total_players(self) -> int:
        total_players = self.data.get("total_players")
        return total_players

    def get_elements(self):
        elements = self.data.get("elements")
        return elements

    def get_player_by_id(self, id: int):
        elements = self.data.get("elements")
        for element in elements:
            if element.get("id") == id:
                return element
        return None

    def get_element_types(self):
        element_types = self.data.get("element_types")
        return element_types

    def get_players_by_position(self):
        elements = self.get_elements()
        element_types = self.get_element_types()
        position_map = {elem.get("id"): [] for elem in element_types}
        try:
            for player in elements:
                player_info = {
                    "first_name": player.get("first_name"),
                    "second_name": player.get("second_name"),
                    "total_points": player.get("total_points"),
                }
                position_map[player.get("element_type")].append(player_info)
        except Exception as e:
            print(e)
            return None

        return position_map

    def get_players_by_position_best_score(self):
        elements = self.get_players_by_position()
        for pos, players in elements.items():
            elements[pos] = sorted(
                players, key=lambda player: player.get("total_points"), reverse=True
            )

        return elements
