"""What can be done to a game night, in one place.

Services call the require_* guards before writing; templates read the plain
predicates (they're also passed to the night page). A finalized night is
locked: nothing about its games, results, players or votes changes until a
host or admin reopens it.
"""

FINAL_MESSAGE = "This game night is finalized. Reopen it to make changes."
VOTING_CLOSED_MESSAGE = "Voting is closed for this game night."
MANAGER_MESSAGE = "Only this night's host or an admin can do that."


class NightRuleError(ValueError):
    """A night rule refused the change; the message is safe to show."""


def can_manage(night, user) -> bool:
    """Admins, the owner and this night's host."""
    return bool(night.managed_by(user))


def is_editable(night) -> bool:
    """Games, results, players and votes can change until the night is finalized."""
    return not night.final


def voting_open(night) -> bool:
    return not night.closed and not night.final


def ready_to_finalize(night, today) -> bool:
    """Worth offering Finalize: the night has happened (today is the app's
    local date) and at least one game has results."""
    return (
        not night.final
        and night.date <= today
        and any(gng.results for gng in night.game_night_games)
    )


def require_manager(night, user) -> None:
    if not can_manage(night, user):
        raise NightRuleError(MANAGER_MESSAGE)


def require_editable(night) -> None:
    if not is_editable(night):
        raise NightRuleError(FINAL_MESSAGE)


def require_voting_open(night) -> None:
    require_editable(night)
    if not voting_open(night):
        raise NightRuleError(VOTING_CLOSED_MESSAGE)
