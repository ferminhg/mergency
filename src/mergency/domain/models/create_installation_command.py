from dataclasses import dataclass

from mergency.domain.models.installation import Installation


@dataclass(frozen=True)
class CreateInstallation:
    installation: Installation
