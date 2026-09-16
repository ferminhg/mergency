from functools import lru_cache

from mergency.adapters.db.activity_event_repository import SqlAlchemyActivityEventRepository
from mergency.adapters.db.engine import build_engine
from mergency.adapters.db.tenant_config_repository import SqlAlchemyTenantConfigRepository
from mergency.adapters.github.changed_files_provider import GithubChangedFilesProvider
from mergency.adapters.github.codeowners_provider import GithubCodeownersProvider
from mergency.adapters.github.commit_range_provider import GithubCommitRangeProvider
from mergency.adapters.github.pr_comment_client import GithubPrCommentClient
from mergency.adapters.github.pull_request_files_provider import GithubPullRequestFilesProvider
from mergency.adapters.github.repository_content_provider import GithubRepositoryContentProvider
from mergency.adapters.github.token_manager import PyGithubInstallationTokenProvider
from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.settings import Settings
from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.budget_history_query import BudgetHistoryQuery
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.event_classifier import EventClassifier
from mergency.domain.flaky_test_detector import FlakyTestDetector
from mergency.domain.installation_service import InstallationService
from mergency.domain.ownership_resolver import OwnershipResolver
from mergency.domain.ports.activity_event_repository import ActivityEventRepository
from mergency.domain.ports.changed_files_provider import ChangedFilesProvider
from mergency.domain.ports.codeowners_provider import CodeownersProvider
from mergency.domain.ports.commit_range_provider import CommitRangeProvider
from mergency.domain.ports.installation_token_provider import InstallationTokenProvider
from mergency.domain.ports.pr_comment_client import PrCommentClient
from mergency.domain.ports.pull_request_files_provider import PullRequestFilesProvider
from mergency.domain.ports.repository_content_provider import RepositoryContentProvider
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository
from mergency.domain.ports.tenant_repository import TenantRepository
from mergency.domain.pr_budget_evaluator import PrBudgetEvaluator


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_tenant_repository() -> TenantRepository:
    return InMemoryTenantRepository()


@lru_cache
def get_installation_service() -> InstallationService:
    return InstallationService(get_tenant_repository())


@lru_cache
def get_installation_token_provider() -> InstallationTokenProvider:
    settings = get_settings()
    return PyGithubInstallationTokenProvider(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
    )


@lru_cache
def get_db_engine():
    return build_engine(get_settings().database_url)


@lru_cache
def get_activity_event_repository() -> ActivityEventRepository:
    return SqlAlchemyActivityEventRepository(get_db_engine())


@lru_cache
def get_event_classifier() -> EventClassifier:
    return EventClassifier()


@lru_cache
def get_flaky_test_detector() -> FlakyTestDetector:
    return FlakyTestDetector(get_activity_event_repository())


@lru_cache
def get_tenant_config_repository() -> TenantConfigRepository:
    return SqlAlchemyTenantConfigRepository(get_db_engine())


@lru_cache
def get_repository_content_provider() -> RepositoryContentProvider:
    return GithubRepositoryContentProvider(get_installation_token_provider())


@lru_cache
def get_codeowners_provider() -> CodeownersProvider:
    return GithubCodeownersProvider(get_repository_content_provider())


@lru_cache
def get_changed_files_provider() -> ChangedFilesProvider:
    return GithubChangedFilesProvider(get_installation_token_provider())


@lru_cache
def get_commit_range_provider() -> CommitRangeProvider:
    return GithubCommitRangeProvider(get_installation_token_provider())


@lru_cache
def get_config_resolver() -> ConfigResolver:
    return ConfigResolver(get_repository_content_provider(), get_tenant_config_repository())


@lru_cache
def get_ownership_resolver() -> OwnershipResolver:
    return OwnershipResolver(get_codeowners_provider())


@lru_cache
def get_budget_calculator() -> BudgetCalculator:
    return BudgetCalculator(get_activity_event_repository(), get_tenant_config_repository())


@lru_cache
def get_budget_history_query() -> BudgetHistoryQuery:
    return BudgetHistoryQuery(get_budget_calculator(), get_activity_event_repository())


@lru_cache
def get_pull_request_files_provider() -> PullRequestFilesProvider:
    return GithubPullRequestFilesProvider(get_installation_token_provider())


@lru_cache
def get_pr_comment_client() -> PrCommentClient:
    return GithubPrCommentClient(get_installation_token_provider())


@lru_cache
def get_pr_budget_evaluator() -> PrBudgetEvaluator:
    return PrBudgetEvaluator(get_ownership_resolver(), get_budget_calculator())


def reset_dependency_caches() -> None:
    get_settings.cache_clear()
    get_tenant_repository.cache_clear()
    get_installation_service.cache_clear()
    get_installation_token_provider.cache_clear()
    get_activity_event_repository.cache_clear()
    get_event_classifier.cache_clear()
    get_flaky_test_detector.cache_clear()
    get_tenant_config_repository.cache_clear()
    get_repository_content_provider.cache_clear()
    get_codeowners_provider.cache_clear()
    get_changed_files_provider.cache_clear()
    get_commit_range_provider.cache_clear()
    get_config_resolver.cache_clear()
    get_ownership_resolver.cache_clear()
    get_db_engine.cache_clear()
    get_budget_calculator.cache_clear()
    get_budget_history_query.cache_clear()
    get_pull_request_files_provider.cache_clear()
    get_pr_comment_client.cache_clear()
    get_pr_budget_evaluator.cache_clear()
