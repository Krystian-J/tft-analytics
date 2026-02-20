from pydantic import BaseModel


class CompanionModel(BaseModel):
    content_ID: str
    item_ID: int
    skin_ID: int
    species: str


class TraitModel(BaseModel):
    name: str
    num_units: int
    style: int
    tier_current: int
    tier_total: int


class UnitModel(BaseModel):
    character_id: str
    itemNames: list[str]
    name: str
    rarity: int
    tier: int


class ParticipantModel(BaseModel):
    companion: CompanionModel
    gold_left: int
    last_round: int
    level: int
    placement: int
    players_eliminated: int
    puuid: str
    riotIdGameName: str
    riotIdTagline: str
    time_eliminated: float
    total_damage_to_players: int
    traits: list[TraitModel]
    units: list[UnitModel]
    win: bool


class MatchInfoModel(BaseModel):
    endOfGameResult: str
    gameCreation: int
    gameId: int
    game_datetime: int
    game_length: float
    game_version: str
    mapId: int
    participants: list[ParticipantModel]
    queueId: int
    queue_id: int
    tft_game_type: str
    tft_set_core_name: str
    tft_set_number: int


class MatchMetadataModel(BaseModel):
    data_version: str
    match_id: str
    participants: list[str]


class MatchResponseModel(BaseModel):
    """
    Represents the full response from the match detail endpoint.
    e.g. GET /tft/match/v1/matches/{matchId}
    """
    metadata: MatchMetadataModel
    info: MatchInfoModel
