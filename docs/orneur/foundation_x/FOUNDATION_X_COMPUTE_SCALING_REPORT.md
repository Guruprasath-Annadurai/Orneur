# Compute and scaling

`decoder_parameter_count` estimates a decoder-only stack as tied embeddings `vocab * d_model` plus, per layer, four `d_model^2` attention matrices and two `4 * d_model` MLP matrices (`12 * d_model^2`). Layer norms and biases are omitted, so the count is an underestimate.

The checked example is 2 layers, `d_model` 16, vocab 100: 7,744 parameters. AdamW master weights plus the two moments at 4 bytes each are `parameters * 12` bytes. Gradients are counted separately.

This does not measure activation memory on a device, does not start a distributed job, and does not show that a development workstation can train GENESIS, NOVUS, or AETERNUM. No GPU test was run. No spend was made.
