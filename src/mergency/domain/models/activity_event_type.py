from enum import Enum


class ActivityEventType(str, Enum):
    BUILD_FAILURE = "build_failure"
    REVERT = "revert"
    FLAKY_TEST = "flaky_test"
    INCIDENT = "incident"
