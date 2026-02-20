from pydantic import BaseModel


class LeagueEntryModel(BaseModel):
    """
    Represents a single player entry within a league response.
    Maps directly to the league_entries PostgreSQL table.
    """
    puuid: str
    leaguePoints: int
    rank: str
    wins: int
    losses: int
    veteran: bool
    inactive: bool
    freshBlood: bool
    hotStreak: bool


class LeagueResponseModel(BaseModel):
    """
    Represents the full response from the league endpoint.
    e.g. GET /tft/league/v1/challenger
    """
    tier: str
    leagueId: str
    queue: str
    name: str
    entries: list[LeagueEntryModel]
