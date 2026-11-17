"""League use-case errors."""


class LeagueNotFound(Exception):
    pass


class LeagueForbidden(Exception):
    pass


class InvitationNotFound(Exception):
    pass


class InvitationExpired(Exception):
    pass
