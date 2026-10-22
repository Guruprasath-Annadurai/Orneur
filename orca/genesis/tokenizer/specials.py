"""Reserved GENESIS special-token ids.

These constants are the training/serving contract for pad, bos, eos and
unk. They live here so checks that only need the names do not import
SentencePiece.
"""

PAD_TOKEN, PAD_ID = "<pad>", 0
BOS_TOKEN, BOS_ID = "<bos>", 1
EOS_TOKEN, EOS_ID = "<eos>", 2
UNK_TOKEN, UNK_ID = "<unk>", 3
SPECIAL_TOKENS = (PAD_TOKEN, BOS_TOKEN, EOS_TOKEN, UNK_TOKEN)
