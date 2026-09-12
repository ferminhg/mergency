# Mergency architecture diagram

```mermaid
flowchart TB
    User(["Org admin / Eng team<br/>installs & configures Mergency"])

    subgraph GH["GitHub"]
        direction TB
        GHInstall["Installation events<br/>installation · installation_repositories"]
        GHEvents["Activity webhooks<br/>push · pull_request · check_run"]
        GHAPI["GitHub REST/GraphQL API<br/>CODEOWNERS · comments · tokens"]
    end

    subgraph Infra["Infrastructure"]
        direction TB
        Gateway{{"API Gateway / Load Balancer<br/>TLS termination, routing"}}
        ControlMQ[["Control-plane queue<br/>installation lifecycle events<br/>low volume, high priority"]]
        DataMQ[["Data-plane queue<br/>activity events<br/>high volume, retry + dead-letter"]]
        Cache[("Token cache<br/>Redis, TTL-based")]
    end

    subgraph Onboarding["Tenant onboarding"]
        direction TB
        InstallHandler["Installation handler<br/>creates/updates tenant record"]
        ConfigResolver["Config resolver<br/>reads mergency.yml from repo<br/>falls back to defaults"]
        TokenMgr["Installation token manager<br/>fetch + refresh short-lived tokens"]
    end

    subgraph Ingress["Ingestion service"]
        direction TB
        WH["Webhook receiver<br/>HMAC validation + tenant lookup<br/>routes by event type"]
    end

    subgraph Core["Mergency Core<br/>(all steps scoped by installation_id)"]
        direction TB
        Classifier["Event classifier<br/>build_failure · revert detection"]
        Owner["Ownership resolver<br/>CODEOWNERS parser + default team fallback"]
        Budget["Budget calculator<br/>rolling window per tenant config"]
    end

    subgraph Storage["Storage<br/>(row-level isolation by installation_id)"]
        direction TB
        TenantDB[("tenants<br/>installation_id · org · plan · status")]
        ConfigDB[("tenant_config<br/>installation_id · window · default_team · budget")]
        EventsDB[("events<br/>installation_id · repo · sha · type · owner · ts")]
    end

    subgraph Consumers["Consumers"]
        direction TB
        CommentBot["PR comment bot"]
        QueryAPI["Historical query API/view<br/>scoped by installation_id"]
    end

    %% User actions
    User -->|install GitHub App| GHInstall
    User -->|commit mergency.yml optionally| GHAPI
    User -.->|views budget status| Gateway

    %% GitHub -> infra entrypoint
    GHInstall -->|webhook payload| Gateway
    GHEvents -->|webhook payload| Gateway
    Gateway -->|routed request| WH

    %% webhook receiver splits by event type into two queues
    WH -->|installation event| ControlMQ
    WH -->|activity event, validated| DataMQ

    %% control-plane consumer
    ControlMQ --> InstallHandler

    %% data-plane consumer
    DataMQ --> Classifier

    %% onboarding flow
    InstallHandler --> TenantDB
    InstallHandler --> ConfigResolver
    ConfigResolver -->|fetch config file| GHAPI
    ConfigResolver --> ConfigDB
    InstallHandler --> TokenMgr
    TokenMgr <--> Cache

    %% core pipeline
    Classifier -->|build_failure / revert| Owner
    Owner -->|resolve installation_id| TenantDB
    Owner -->|fetch CODEOWNERS via cached token| Cache
    Owner -->|owner resolved| EventsDB
    ConfigDB -.->|default team, budget target| Owner
    ConfigDB -.->|window, budget target| Budget
    EventsDB --> Budget

    %% token-authenticated GitHub calls
    Cache -.->|scoped token| GHAPI

    %% consumers
    Budget -->|budget status| CommentBot
    CommentBot -->|post/update comment via cached token| Cache
    CommentBot -->|post/update comment| GHAPI
    EventsDB --> QueryAPI
    QueryAPI -->|query result| Gateway

    classDef actor fill:#fff3b0,stroke:#c9a227,color:#1a1a1a
    classDef external fill:#e8e8e8,stroke:#888,color:#333
    classDef infra fill:#ffd6e0,stroke:#c94f77,color:#1a1a1a
    classDef onboarding fill:#f0d9ff,stroke:#a05fd6,color:#1a1a1a
    classDef core fill:#d4e8ff,stroke:#4a7fc9,color:#1a1a1a
    classDef storage fill:#ffe8cc,stroke:#cc8844,color:#1a1a1a
    classDef consumer fill:#d8f0d8,stroke:#5a9a5a,color:#1a1a1a

    class User actor
    class GHInstall,GHEvents,GHAPI external
    class Gateway,ControlMQ,DataMQ,Cache infra
    class InstallHandler,ConfigResolver,TokenMgr onboarding
    class WH,Classifier,Owner,Budget core
    class TenantDB,ConfigDB,EventsDB storage
    class CommentBot,QueryAPI consumer
```


# Functional requirements
FR-INFRA1: The system must route every incoming GitHub webhook through a single entry point (API Gateway) before it reaches any internal service.
FR-INFRA2: The webhook receiver must classify each incoming event by type and route it to the correct queue: installation lifecycle events go to the control-plane queue, activity events (push, pull_request, check_run) go to the data-plane queue.
FR-INFRA3: The installation handler must only consume from the control-plane queue. It must never process activity events directly.
FR-INFRA4: The event classifier must only consume from the data-plane queue.
FR-INFRA5: The token manager must cache installation access tokens per tenant and serve them to any component that needs to call the GitHub API, instead of requesting a fresh token on every call.
FR-INFRA6: When a cached token is expired or missing, the token manager must transparently fetch a new one from GitHub and refresh the cache, without the calling component needing to know that happened.

# Non-functional requirements

NFR-INFRA1 (Isolation): A spike or outage on the data-plane queue must never block or delay processing on the control-plane queue. Installing or uninstalling the app must keep working even if activity processing is degraded.
NFR-INFRA2 (Throughput): The data-plane queue must be sized for high volume traffic (the whole premise of the project is more PRs coming from AI-assisted coding), while the control-plane queue can stay small since installs/uninstalls are rare by comparison.
NFR-INFRA3 (Reliability): Both queues must support retry with backoff, and the data-plane queue specifically must support a dead-letter mechanism, since losing an activity event silently would corrupt the budget calculation for that tenant.
NFR-INFRA4 (Latency): Reading a cached token must be fast enough (sub-10ms typically) that it doesn't become the bottleneck for the PR comment flow, which is the most latency-sensitive path in the system.
NFR-INFRA5 (Security): Tokens stored in the cache must be short-lived and scoped to a single installation. A cache compromise must never expose a token usable across tenants.
NFR-INFRA6 (Cost/complexity trade-off): Splitting the queue by plane adds one more moving part to operate. This decision should be revisited if actual traffic doesn't justify it yet (documented as a reversible decision, not a permanent architectural constraint).

📝 One thing worth calling out separately, since it's easy to lose in a diagram: NFR-INFRA1 is really the reason the two-queue split exists at all. If that requirement didn't matter to you, a single queue would be simpler and you shouldn't have split it. Worth keeping that link visible wherever this list lives next to the diagram.


