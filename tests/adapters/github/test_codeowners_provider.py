from mergency.adapters.github.codeowners_provider import GithubCodeownersProvider


class _StubContentProvider:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = files
        self.requested_paths: list[str] = []

    async def get_file(self, installation_id, repo, path):
        self.requested_paths.append(path)
        return self._files.get(path)


async def test_parses_codeowners_from_root_location():
    content_provider = _StubContentProvider({"CODEOWNERS": "*.py @org/team-a\n"})
    provider = GithubCodeownersProvider(content_provider)

    owners = await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert owners == [("TEAM", "@org/team-a")]


async def test_falls_back_to_github_directory_location():
    content_provider = _StubContentProvider({".github/CODEOWNERS": "*.py @org/team-b\n"})
    provider = GithubCodeownersProvider(content_provider)

    owners = await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert owners == [("TEAM", "@org/team-b")]
    assert content_provider.requested_paths == ["CODEOWNERS", ".github/CODEOWNERS"]


async def test_falls_back_to_docs_directory_location():
    content_provider = _StubContentProvider({"docs/CODEOWNERS": "*.py @org/team-c\n"})
    provider = GithubCodeownersProvider(content_provider)

    owners = await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert owners == [("TEAM", "@org/team-c")]


async def test_returns_empty_list_when_no_codeowners_file_exists():
    provider = GithubCodeownersProvider(_StubContentProvider({}))

    owners = await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert owners == []


async def test_caches_parsed_rules_across_calls_for_the_same_repo():
    content_provider = _StubContentProvider({"CODEOWNERS": "*.py @org/team-a\n"})
    provider = GithubCodeownersProvider(content_provider)

    await provider.owners_for(1, "acme/widgets", "src/a.py")
    await provider.owners_for(1, "acme/widgets", "src/b.py")

    assert content_provider.requested_paths == ["CODEOWNERS"]


async def test_different_repos_are_cached_independently():
    content_provider = _StubContentProvider({"CODEOWNERS": "*.py @org/team-a\n"})
    provider = GithubCodeownersProvider(content_provider)

    await provider.owners_for(1, "acme/widgets", "src/a.py")
    await provider.owners_for(1, "acme/other", "src/a.py")

    assert content_provider.requested_paths == ["CODEOWNERS", "CODEOWNERS"]


async def test_refetches_after_the_ttl_expires(monkeypatch):
    content_provider = _StubContentProvider({"CODEOWNERS": "*.py @org/team-a\n"})
    provider = GithubCodeownersProvider(content_provider)
    current_time = [1000.0]
    monkeypatch.setattr(
        "mergency.adapters.github.codeowners_provider.time.monotonic", lambda: current_time[0]
    )

    await provider.owners_for(1, "acme/widgets", "src/a.py")
    current_time[0] += 301
    await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert content_provider.requested_paths == ["CODEOWNERS", "CODEOWNERS"]
