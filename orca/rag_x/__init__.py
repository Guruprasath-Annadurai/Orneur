"""In-process RAG-X kernel.

This package qualifies retrieval behavior on synthetic fixtures. It does
not train a model, does not claim a production index, and does not replace
`orca.truth` or `orca.connectors.federated_retrieval`.
"""

from orca.rag_x.kernel import execute
from orca.rag_x.matrix import CAPABILITIES

__all__ = ["CAPABILITIES", "execute"]
