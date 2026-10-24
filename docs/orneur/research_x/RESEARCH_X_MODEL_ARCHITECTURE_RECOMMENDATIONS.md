# Architecture recommendations

Do not change the canonical decoder-only training stack from this work.

The estimate in `decoder_parameter_count` is a formula with omitted layer norms. It is not an experiment that compared attention variants, mixture-of-experts, or positional schemes.

Future training, if separately authorized, still needs the existing tokenizer, data-admission, checkpoint, and evaluation gates. Retrieval prototypes in `orca/rag_x` are not training objectives. No retrieval-conditioned loss was implemented.

GENESIS, NOVUS, and AETERNUM remain untrained. Role labels in `arbitrate` do not create those models.
