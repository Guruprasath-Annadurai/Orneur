"""Research-only RAG-X kernel.

Canonical retrieval is the Truth Fabric plus `orca.docs.authorized_index`.
This package qualifies strategies on synthetic fixtures. It does not train
a model and it does not replace `orca.truth` or
`orca.connectors.federated_retrieval`.
"""

from orca.rag_x.kernel import execute
from orca.rag_x.matrix import CAPABILITIES

__all__ = ["CAPABILITIES", "execute"]
