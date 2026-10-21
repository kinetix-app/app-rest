"""Validate the local ExerciseDB V2 export before performing any remote writes."""

import json
import re
from dataclasses import dataclass
from hashlib import file_digest
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

SOURCE = "ascend_edb_v2"


class ExerciseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    exerciseId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,150}$")
    name: str = Field(min_length=1)
    imageUrl: str
    imageUrls: dict[str, str]
    videoUrl: str
    equipments: list[str]
    bodyParts: list[str]
    exerciseType: str = Field(min_length=1, max_length=50)
    targetMuscles: list[str]
    secondaryMuscles: list[str]
    keywords: list[str]
    overview: str
    instructions: list[str]
    exerciseTips: list[str]
    variations: list[str]
    relatedExerciseIds: list[str]

    def database_values(self) -> dict:
        return {
            "source": SOURCE,
            "external_id": self.exerciseId,
            # The catalogue is gym movements, including equipment-based cardio;
            # exerciseType remains a separate provider classification.
            "activity_type": "gym",
            "name": self.name,
            "overview": self.overview,
            "body_parts": self.bodyParts,
            "equipments": self.equipments,
            "exercise_types": [self.exerciseType],
            "target_muscles": self.targetMuscles,
            "secondary_muscles": self.secondaryMuscles,
            "instructions": self.instructions,
            "exercise_tips": self.exerciseTips,
            "variations": self.variations,
            "keywords": self.keywords,
            "related_exercise_ids": self.relatedExerciseIds,
        }


@dataclass(frozen=True)
class Asset:
    path: Path
    digest: str
    content_type: str
    blob_name: str


@dataclass(frozen=True)
class SeedExercise:
    data: ExerciseInput
    images: dict[str, Asset]
    default_image: str
    video: Asset

    @property
    def assets(self) -> list[Asset]:
        return [*self.images.values(), self.video]


def load_dataset(root: Path) -> list[SeedExercise]:
    root = root.resolve(strict=True)
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    if not isinstance(index, dict) or not index:
        raise ValueError("index.json must map exercise IDs to directory names")
    if any(not isinstance(slug, str) for slug in index.values()):
        raise ValueError("index.json directory names must be strings")
    if len(set(index.values())) != len(index):
        raise ValueError("index.json maps multiple exercises to the same directory")
    if {p.parent.name for p in root.glob("*/data.json")} != set(index.values()):
        raise ValueError("index.json must include every exercise directory exactly once")

    def asset(path: Path, external_id: str, content_type: str) -> Asset:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("Assets must be files inside the dataset")
        if not resolved.stat().st_size:
            raise ValueError(f"Empty asset: {path.relative_to(root)}")
        with resolved.open("rb") as stream:
            digest = file_digest(stream, "sha256").hexdigest()
        name = f"{SOURCE}/{external_id}/{digest}{path.suffix}"
        return Asset(resolved, digest, content_type, name)

    result = []
    for external_id, slug in sorted(index.items()):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError("Exercise directories must be lowercase slugs")
        folder = root / slug
        metadata = (folder / "data.json").resolve(strict=True)
        if not metadata.is_relative_to(root):
            raise ValueError("Metadata must be inside the dataset")
        data = ExerciseInput.model_validate_json(metadata.read_bytes())
        if data.exerciseId != external_id:
            raise ValueError(f"Exercise ID does not match index: {slug}")
        if not data.imageUrls or not data.videoUrl:
            raise ValueError(f"Missing image/video metadata: {slug}")
        images = {}
        for resolution in data.imageUrls:
            if not re.fullmatch(r"[1-9][0-9]*p", resolution):
                raise ValueError(f"Unsupported image resolution: {slug}")
            images[resolution] = asset(
                folder / "images" / f"{resolution}.jpg", external_id, "image/jpeg"
            )
        defaults = [key for key, value in data.imageUrls.items() if value == data.imageUrl]
        if len(defaults) != 1:
            raise ValueError(f"Default image must identify exactly one image variant: {slug}")
        video = asset(folder / "video.mp4", external_id, "video/mp4")
        expected = {metadata, video.path, *(item.path for item in images.values())}
        actual = {p.resolve() for p in folder.rglob("*") if p.is_file()}
        if actual != expected:
            raise ValueError(f"Unmapped files in exercise directory: {slug}")
        result.append(SeedExercise(data, images, defaults[0], video))
    return result
