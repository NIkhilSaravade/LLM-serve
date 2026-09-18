"""Regenerate golden fixtures from the HuggingFace reference implementation.

Run once, commit tests/fixtures/. If the fixtures change, that must show up in a diff.
This is the ONLY file in the repo allowed to call model.generate().
"""
from __future__ import annotations

import json
from pathlib import Path

import torch
from transformers import GPT2LMHeadModel, GPT2TokenizerFast

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
EOS = 50256
BLOCK_SIZE = 16  # the M4 default; boundary fixtures are built around it

BASE_TEXT = """
The harbour town woke slowly that morning, as it always did in late autumn. Fishing
boats rocked against their moorings while gulls argued over scraps on the quay. In
the bakery on Mill Street, Marta pulled the first loaves from the oven and set them
on the rack to cool, the smell drifting out into the cold air. Across the square,
the clockmaker unlocked his shop and began the daily ritual of winding forty clocks,
each one slightly out of agreement with its neighbours. Nobody in town minded. They
had long ago decided that the exact time mattered less than the fact that someone
cared enough to keep trying. Up on the hill, the old lighthouse keeper watched a
grey line of weather gathering far out over the water. He had seen storms like it
before, and he knew the signs: the swell rising without wind, the strange stillness
of the birds, the way the light turned the colour of pewter. He climbed the spiral
stairs, checked the lamp, and wrote a brief note in the logbook. Below him the town
carried on with its small business. A child chased a dog along the seawall. Two
merchants haggled over a crate of salted cod. A woman in a blue coat sat on a bench
and read a letter for the third time, as though the words might change. By noon the
first heavy drops began to fall, and the whole town seemed to exhale, gather its
things, and move indoors together. Later that night the storm arrived in earnest,
and the lighthouse beam swept steadily through sheets of rain, patient and
unhurried, keeping faith with every boat still out on the dark sea. Morning came
again, washed clean, and the clockmaker began winding his forty clocks once more.
Science is a way of thinking much more than it is a body of knowledge. Whenever we
ask why something happens, we are stepping onto a path that leads to a model of the
world, and that model can be tested against what we observe. A good theory makes
risky predictions and survives them. A bad one explains everything and therefore
explains nothing at all. The engineers who built the first bridges did not have
equations for stress and strain, yet many of their structures still stand, because
they paid close attention to what failed and quietly avoided doing it again.
""".strip().replace("\n", " ")

# name -> (offset into base token stream, prompt_len, max_new_tokens, why)
SINGLES = {
    "short_5_out20":      (0,   5,   20,  "basic sanity"),
    "long_400_out20":     (7,   400, 20,  "prefill and position bugs"),
    "short_5_out300":     (40,  5,   300, "cache-growth bugs"),
    "block_exact_16":     (11,  16,  20,  "prompt exactly one block"),
    "block_exact_32":     (23,  32,  20,  "prompt exactly two blocks"),
    "block_plus1_17":     (3,   17,  20,  "one token over a block boundary"),
    "block_minus1_15":    (29,  15,  20,  "one token under a block boundary"),
    "cross_block_gen_10": (17,  10,  40,  "output crosses block boundaries mid-generation"),
}

# Batch cases: lists of single-fixture names. Only meaningful from M2/M3 on.
BATCHES = {
    "two_different_lengths": ["short_5_out20", "long_400_out20"],
    "same_prompt_twice": ["short_5_out20", "short_5_out20"],
    "mixed_8": ["short_5_out20", "long_400_out20", "short_5_out300", "block_exact_16",
                "block_plus1_17", "block_minus1_15", "cross_block_gen_10", "block_exact_32"],
}


def main() -> None:
    tok = GPT2TokenizerFast.from_pretrained("gpt2")
    model = GPT2LMHeadModel.from_pretrained("gpt2", dtype=torch.float32).eval()
    base = tok.encode(BASE_TEXT)
    OUT.mkdir(parents=True, exist_ok=True)

    for name, (off, plen, n_new, why) in SINGLES.items():
        prompt = base[off:off + plen]
        assert len(prompt) == plen, f"{name}: base text too short ({len(base)} tokens)"
        ids = torch.tensor([prompt])
        with torch.inference_mode():
            # generate() is allowed here and nowhere else in the repo.
            out = model.generate(ids, attention_mask=torch.ones_like(ids), do_sample=False,
                                 max_new_tokens=n_new, pad_token_id=EOS, eos_token_id=EOS)
        expected = out[0, plen:].tolist()
        (OUT / f"{name}.json").write_text(json.dumps({
            "name": name, "why": why, "prompt_token_ids": prompt,
            "max_new_tokens": n_new, "expected_token_ids": expected,
        }, indent=1) + "\n")
        print(f"{name}: prompt={plen} out={len(expected)}")

    (OUT / "batches.json").write_text(json.dumps(BATCHES, indent=1) + "\n")


if __name__ == "__main__":
    main()
