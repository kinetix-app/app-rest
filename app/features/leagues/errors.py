"""League use-case errors."""


class LeagueNotFound(Exception):
    pass


class LeagueForbidden(Exception):
    pass


class LeagueRoleChangeForbidden(Exception):
    """A protected role cannot be changed."""


class InvitationNotFound(Exception):
    pass


class InvitationExpired(Exception):
    pass
