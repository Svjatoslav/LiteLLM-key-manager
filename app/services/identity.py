from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class IdentityGroup:
    dn: str
    members: list[str]


class IdentityProvider(ABC):
    """Future integration point for LDAP/LDAPS Active Directory sync."""

    @abstractmethod
    def list_groups(self) -> list[IdentityGroup]:
        raise NotImplementedError


class DisabledIdentityProvider(IdentityProvider):
    def list_groups(self) -> list[IdentityGroup]:
        return []

