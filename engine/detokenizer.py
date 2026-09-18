"""Streaming detokenisation.

One UTF-8 character can span several GPT-2 byte-level tokens, so decoding each token on its
own yields broken characters (U+FFFD). We decode a sliding window and only release text once
it no longer ends in an incomplete character.
"""
from __future__ import annotations


class IncrementalDetokenizer:
    def __init__(self, tokenizer) -> None:
        self.tok = tokenizer
        self.ids: list[int] = []
        self.prefix = 0   # start of the window we re-decode (gives BPE context)
        self.read = 0     # ids before this have already been emitted as text

    def push(self, token_id: int) -> str:
        self.ids.append(token_id)
        prefix_text = self.tok.decode(self.ids[self.prefix:self.read])
        new_text = self.tok.decode(self.ids[self.prefix:])
        if len(new_text) > len(prefix_text) and not new_text.endswith("�"):
            self.prefix, self.read = self.read, len(self.ids)
            return new_text[len(prefix_text):]
        return ""   # incomplete character: hold it back until more bytes arrive

    def flush(self) -> str:
        """Emit whatever is left (an incomplete tail becomes U+FFFD, as a plain decode would)."""
        prefix_text = self.tok.decode(self.ids[self.prefix:self.read])
        new_text = self.tok.decode(self.ids[self.prefix:])
        self.prefix = self.read = len(self.ids)
        return new_text[len(prefix_text):]
