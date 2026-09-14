from mergency.domain.ownership_resolver import OwnershipResolver


class _StubCodeownersProvider:
    def __init__(self, owners_by_path: dict[str, list[tuple[str, str]]]) -> None:
        self._owners_by_path = owners_by_path

    async def owners_for(self, installation_id, repo, path):
        return self._owners_by_path.get(path, [])


async def test_resolves_a_single_team_owner():
    resolver = OwnershipResolver(_StubCodeownersProvider({"src/a.py": [("TEAM", "@org/team-a")]}))

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py"], "unassigned")

    assert owners == ["@org/team-a"]


async def test_fans_out_to_multiple_distinct_team_owners():
    resolver = OwnershipResolver(
        _StubCodeownersProvider(
            {
                "src/a.py": [("TEAM", "@org/team-a")],
                "src/b.py": [("TEAM", "@org/team-b")],
            }
        )
    )

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py", "src/b.py"], "unassigned")

    assert owners == ["@org/team-a", "@org/team-b"]


async def test_deduplicates_the_same_team_matched_by_multiple_files():
    resolver = OwnershipResolver(
        _StubCodeownersProvider(
            {
                "src/a.py": [("TEAM", "@org/team-a")],
                "src/b.py": [("TEAM", "@org/team-a")],
            }
        )
    )

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py", "src/b.py"], "unassigned")

    assert owners == ["@org/team-a"]


async def test_individual_match_falls_back_to_default_team():
    resolver = OwnershipResolver(_StubCodeownersProvider({"src/a.py": [("USERNAME", "@someuser")]}))

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py"], "unassigned")

    assert owners == ["unassigned"]


async def test_email_match_also_falls_back_to_default_team():
    resolver = OwnershipResolver(
        _StubCodeownersProvider({"src/a.py": [("EMAIL", "docs@example.com")]})
    )

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py"], "unassigned")

    assert owners == ["unassigned"]


async def test_no_match_falls_back_to_default_team():
    resolver = OwnershipResolver(_StubCodeownersProvider({}))

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/unmatched.py"], "unassigned")

    assert owners == ["unassigned"]


async def test_mixed_team_and_individual_matches_keep_only_the_team():
    resolver = OwnershipResolver(
        _StubCodeownersProvider({"src/a.py": [("TEAM", "@org/team-a"), ("USERNAME", "@someuser")]})
    )

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py"], "unassigned")

    assert owners == ["@org/team-a"]
