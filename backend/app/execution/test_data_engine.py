"""
Test data engine — generates contextual test data and tracks created entities for reuse.
"""
from __future__ import annotations

import random
import re
import string
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()

_WORDS = [
    "Alpha", "Beta", "Gamma", "Delta", "Echo", "Foxtrot", "Globe",
    "Horizon", "Impact", "Jupiter", "Kappa", "Lambda", "Metro", "Nexus",
    "Orbit", "Prime", "Quest", "Ranger", "Summit", "Titan", "Ultra",
    "Vector", "Warp", "Xenon", "Yield", "Zeta",
]


def _rand_suffix(n: int) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


@dataclass
class TrackedEntity:
    name: str
    value: str
    entity_type: str
    created_step: int = 0
    needs_cleanup: bool = True


class TestDataEngine:
    """Generates and tracks test data values across a workflow execution."""

    def __init__(self) -> None:
        self._registry: dict[str, TrackedEntity] = {}
        self._step_counter: int = 0
        self._run_suffix: str = _rand_suffix(6)

    def generate(self, data_type: str, context: str = "") -> str:
        dt = data_type.lower().strip()
        ctx = context.lower()

        if dt in ("product_name", "product"):
            w1, w2 = random.sample(_WORDS, 2)
            return f"{w1} {w2} {_rand_suffix(4)}"

        if dt in ("name", "full_name"):
            return f"QA User {_rand_suffix(5)}"

        if dt == "email":
            return f"qa_{_rand_suffix(8).lower()}@test.com"

        if dt == "phone":
            digits1 = "".join(random.choices(string.digits, k=4))
            digits2 = "".join(random.choices(string.digits, k=4))
            return f"+1-555-{digits1}-{digits2}"

        if dt in ("number", "quantity", "count"):
            if "negative" in ctx:
                return str(random.randint(-100, -1))
            if "large" in ctx:
                return str(random.randint(10000, 99999))
            return str(random.randint(1, 999))

        if dt in ("price", "amount"):
            return f"{random.randint(10, 999)}.{random.randint(0, 99):02d}"

        if dt == "date":
            month = random.randint(1, 12)
            day = random.randint(1, 28)
            return f"2025-{month:02d}-{day:02d}"

        if dt in ("description", "notes", "text"):
            return f"QA auto-generated {self._run_suffix}"

        if dt in ("code", "id", "reference"):
            return f"QA-{_rand_suffix(8)}"

        if dt == "company":
            return f"QA Corp {_rand_suffix(4)}"

        if dt == "address":
            return f"{random.randint(1, 999)} Test Street, QA City"

        if dt == "password":
            return f"QA@Test#{_rand_suffix(6)}"

        return f"QA-{data_type.title()}-{_rand_suffix(5)}"

    def track(self, name: str, value: str, entity_type: str = "generic") -> None:
        self._registry[name] = TrackedEntity(
            name=name,
            value=value,
            entity_type=entity_type,
            created_step=self._step_counter,
        )
        log.debug("Tracked entity", name=name, entity_type=entity_type)

    def recall(self, name: str) -> str | None:
        entity = self._registry.get(name)
        return entity.value if entity else None

    def set_step(self, step_num: int) -> None:
        self._step_counter = step_num

    def resolve(self, template: str) -> str:
        if "{{" not in template:
            return template

        result = template

        # Replace {{entity:name|fallback_type}} and {{entity:name}}
        entity_pattern = re.compile(r"\{\{entity:([^|}]+)(?:\|([^}]+))?\}\}")
        for match in entity_pattern.finditer(result):
            entity_name = match.group(1).strip()
            fallback_type = (match.group(2) or "").strip()
            value = self.recall(entity_name)
            if value is None:
                gen_type = fallback_type or entity_name
                value = self.generate(gen_type)
                self.track(entity_name, value, gen_type)
            result = result.replace(match.group(0), value, 1)

        # Replace {{data_type}}
        type_pattern = re.compile(r"\{\{([^}]+)\}\}")
        for match in type_pattern.finditer(result):
            data_type = match.group(1).strip()
            result = result.replace(match.group(0), self.generate(data_type), 1)

        return result

    def resolve_step(self, step: dict[str, Any]) -> dict[str, Any]:
        copy = dict(step)
        for field_name in ("value", "text", "url", "target"):
            if field_name in copy and isinstance(copy[field_name], str):
                copy[field_name] = self.resolve(copy[field_name])
        return copy

    def get_cleanup_entities(self) -> list[TrackedEntity]:
        return [e for e in self._registry.values() if e.needs_cleanup]

    def summary(self) -> dict[str, Any]:
        return {
            "entities_created": len(self._registry),
            "entity_names": list(self._registry.keys()),
        }
