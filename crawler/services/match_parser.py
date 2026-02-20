from datetime import datetime, timezone

from shared.models.match import MatchResponseModel
from shared.models.unit import UnitRowModel


def parse_game_version(raw_version: str) -> str:
    """
    Extracts a clean patch string from the raw game_version field.
    e.g. "Linux Version 16.3.745.7600 (Feb 10 2026/14:45:54) [PUBLIC] " → "16.3"
    """
    try:
        # Version string contains "16.3.745..." — extract major.minor only
        parts = raw_version.strip().split()
        for part in parts:
            segments = part.split(".")
            if len(segments) >= 2 and segments[0].isdigit():
                return f"{segments[0]}.{segments[1]}"
    except Exception:
        pass
    return raw_version.strip()


def get_item_slots(item_names: list[str]) -> tuple[str, str, str]:
    """
    Maps a list of item names (0-3 items) to exactly three slots.
    Empty slots are filled with empty strings.
    """
    padded = (item_names + ["", "", ""])[:3]
    return padded[0], padded[1], padded[2]


def explode_match_to_unit_rows(
    match: MatchResponseModel,
    player_ranks: dict[str, dict],
) -> list[UnitRowModel]:
    """
    Explodes a single match response into a list of flat UnitRowModel instances
    ready for batch insertion into ClickHouse tft.unit_stats table.

    One row is produced per unit per participant.
    A standard 8-player game produces approximately 72 rows.

    Args:
        match: Validated MatchResponseModel from Riot API response.
        player_ranks: Dict mapping puuid → {tier, rank, lp} from league_entries.
                      Used to denormalize rank data into each unit row.
                      If a puuid is not found, defaults to empty tier/rank and 0 lp.

    Returns:
        List of UnitRowModel instances ready for ClickHouse insertion.
    """
    rows: list[UnitRowModel] = []

    match_id = match.metadata.match_id
    game_version = parse_game_version(match.info.game_version)
    tft_set_number = match.info.tft_set_number
    queue_id = match.info.queue_id

    # Convert millisecond timestamp to datetime
    game_datetime = datetime.fromtimestamp(
        match.info.game_datetime / 1000,
        tz=timezone.utc,
    ).replace(tzinfo=None)  # ClickHouse DateTime is timezone-naive

    for participant in match.info.participants:
        # Look up player rank data — default to unknown if not found
        rank_data = player_ranks.get(participant.puuid, {})
        tier = rank_data.get("tier", "")
        rank = rank_data.get("rank", "")
        lp = rank_data.get("lp", 0)

        for unit in participant.units:
            item_1, item_2, item_3 = get_item_slots(unit.itemNames)

            row = UnitRowModel(
                # Match level
                match_id=match_id,
                game_datetime=game_datetime,
                game_version=game_version,
                tft_set_number=tft_set_number,
                queue_id=queue_id,

                # Participant level
                puuid=participant.puuid,
                placement=participant.placement,
                level=participant.level,
                last_round=participant.last_round,
                gold_left=participant.gold_left,
                players_eliminated=participant.players_eliminated,
                total_damage_to_players=participant.total_damage_to_players,

                # Rank — denormalized from league_entries
                tier=tier,
                rank=rank,
                lp=lp,

                # Unit level
                character_id=unit.character_id,
                unit_name=unit.name,
                unit_tier=unit.tier,
                unit_rarity=unit.rarity,

                # Items
                item_1=item_1,
                item_2=item_2,
                item_3=item_3,
            )
            rows.append(row)

    return rows
