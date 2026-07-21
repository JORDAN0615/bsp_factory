import os
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

_QDRANT_DIR = Path(__file__).parent.parent / "_qdrant"
_QDRANT_DIR.mkdir(exist_ok=True)
client = QdrantClient(path=str(_QDRANT_DIR))

COLLECTION = "bsp"


def init_collection(vector_size: int, *, force_recreate: bool = False) -> None:
    """Create collection if it doesn't exist.

    If the collection already exists and has points, it is reused (fast restart).
    Only recreates when forced (e.g. dimension change).

    Args:
        vector_size: embedding dimension (must match existing or new collection).
        force_recreate: if True, drop and recreate regardless of existing data.
    """
    if client.collection_exists(COLLECTION):
        if not force_recreate:
            # Collection exists — skip creation (reused from disk)
            return
        # Force mode: drop so we can recreate
        client.delete_collection(COLLECTION)

    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )

