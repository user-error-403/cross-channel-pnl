import hashlib
import random

from faker import Faker


def _stage_int(seed: int, stage: str) -> int:
    """
    Derive a stable integer seed from a `seed` and `stage` pair.

    - Determinism: SHA-256 is required because builtin `hash()` is salted per
      process, so it varies between runs.
    """
    digest = hashlib.sha256(f"{seed}:{stage}".encode()).digest()
    return int.from_bytes(digest[:8], "little")


def stage_faker(seed: int, stage: str) -> Faker:
    """
    Return a Faker instance seeded deterministically for `stage`.

    - Behavior: `Faker.seed` mutates process-global state, so the most recent
      `stage_faker` call governs every Faker instance in the process.
    """
    f = Faker()
    Faker.seed(_stage_int(seed, stage))
    return f


def stage_rng(seed: int, stage: str) -> random.Random:
    """
    Return a `random.Random` seeded deterministically for `stage`.

    - Determinism: A distinct `stage` name isolates one generator from another,
      so changing one stream leaves the rest untouched.
    """
    return random.Random(f"{seed}:{stage}")
