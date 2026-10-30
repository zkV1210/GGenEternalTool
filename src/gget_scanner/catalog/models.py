"""Schema-v1 records. Progression and player ownership do not belong here."""

from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


class CatalogError(ValueError):
    """Invalid catalog, conflicting identity, or unavailable reference image."""


def identity_id(source: str, source_id: str) -> str:
    """Stable project ID, never an assertion about the game's internal IDs."""
    return str(uuid5(NAMESPACE_URL, f"urn:gget-scanner:unit:{source}:{source_id}"))


@dataclass(frozen=True)
class UnitSource:
    source: str
    source_id: str
    page_url: str
    retrieved_at: str
    rarity_code: str | None = None
    role_code: str | None = None


@dataclass(frozen=True)
class UnitImage:
    kind: str
    source_url: str | None
    local_path: str | None = None
    status: str = "not_downloaded"
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class Unit:
    unit_id: str
    name: str | None
    language: str | None
    rarity: str | None
    variant: str | None
    role: str | None
    sources: tuple[UnitSource, ...]
    images: tuple[UnitImage, ...]


@dataclass(frozen=True)
class Catalog:
    units: tuple[Unit, ...]
    schema_version: int = 1

    def get(self, unit_id: str) -> Unit:
        for unit in self.units:
            if unit.unit_id == unit_id:
                return unit
        raise KeyError(unit_id)

    def reference_paths(self, unit_id: str, root: str | Path, *, kind: str | None = None) -> tuple[Path, ...]:
        """Recheck files on use; a stored 'downloaded' flag alone is insufficient."""
        from .validator import check_image, local_image_path

        paths = []
        for image in self.get(unit_id).images:
            if image.status == "downloaded" and (kind is None or image.kind == kind):
                check_image(image, Path(root))
                paths.append(local_image_path(Path(root), image.local_path))
        return tuple(paths)
