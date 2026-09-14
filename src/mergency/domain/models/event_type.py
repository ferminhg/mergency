from enum import Enum


class EventType(str, Enum):
    BUILD_FAILURE = "build_failure"
    REVERT = "revert"
