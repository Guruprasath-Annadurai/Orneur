"""Parameter and AdamW memory estimates.

These are closed-form estimates for a decoder-only stack with a 4x MLP.
They are not measurements of a trained model and they do not show that a
development workstation can run frontier pretraining.
"""
from __future__ import annotations


def decoder_parameter_count(*, layers: int, d_model: int, vocab: int, tied_embeddings: bool = True) -> int:
    """Embeddings plus 4 square attention matrices and two 4d MLP matrices per layer.

    Layer norms and biases are omitted and called out as an underestimate.
    """
    if layers < 1 or d_model < 1 or vocab < 1:
        raise ValueError("layers, d_model, and vocab must be positive")
    per_layer = (4 * d_model * d_model) + (8 * d_model * d_model)
    embeddings = vocab * d_model
    head = 0 if tied_embeddings else vocab * d_model
    return embeddings + head + layers * per_layer


def adamw_state_bytes(parameters: int, *, dtype_bytes: int = 4) -> int:
    """fp32 master weights, first moment, and second moment. Gradients are extra."""
    if parameters < 0 or dtype_bytes < 1:
        raise ValueError("parameters and dtype_bytes must be non-negative and positive respectively")
    return parameters * dtype_bytes * 3


def gradient_bytes(parameters: int, *, dtype_bytes: int = 4) -> int:
    return parameters * dtype_bytes


GPU_REQUIRED_NOT_RUN = (
    "multi-gpu all-reduce",
    "sharded checkpoint reload on more than one device",
    "bf16 matmul parity against an accelerator",
)
