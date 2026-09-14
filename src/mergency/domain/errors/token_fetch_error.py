class TokenFetchError(Exception):
    def __init__(self, installation_id: int, cause: Exception) -> None:
        super().__init__(
            f"failed to fetch an installation token for installation {installation_id}: {cause}"
        )
        self.installation_id = installation_id
