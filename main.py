from fastapi import FastAPI, HTTPException
from util.fpl_service import FplService

app = FastAPI()
service = FplService()


@app.get("/events/{event_id}")
def get_event_by_id(event_id: int):
    result = service.get_event_by_id(event_id)
    if not result:
        raise HTTPException(status_code=404, detail="Event not found")

    return result


@app.get("/elements/{element_id}")
def get_player_by_id(element_id: int):
    result = service.get_player_by_id(element_id)
    if not result:
        raise HTTPException(status_code=404, detail="Player not found")

    return result


@app.get("/players/by/position")
def get_players_by_position():
    result = service.get_players_by_position()
    if not result:
        raise HTTPException(status_code=500)

    return result


@app.get("/players/top/score")
def get_players_by_total_points():
    result = service.get_players_by_position_best_score()
    if not result:
        raise HTTPException(status_code=500)

    return result
