import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import torch
from conftest import RunIf
from test_generate_sequentially import find_forward_hooks


def test_tensor_parallel_linear():
    from generate.tp import tensor_parallel_linear

    fabric = Mock()
    fabric.world_size = 4
    fabric.global_rank = 2

    def get_linear(bias=True):
        linear = torch.nn.Linear(8, 8, bias=bias)
        linear.weight.data = torch.arange(64, dtype=torch.float32).reshape(8, 8)
        if bias:
            linear.bias.data = torch.arange(8, dtype=torch.float32)
        return linear

    linear = get_linear()
    tensor_parallel_linear(fabric, linear, "colwise")
    expected = torch.arange(32, 48, dtype=torch.float32).reshape(2, 8)
    torch.testing.assert_close(linear.weight, expected)
    expected = torch.arange(4, 6, dtype=torch.float32)
    torch.testing.assert_close(linear.bias, expected)

    linear = get_linear(bias=False)
    tensor_parallel_linear(fabric, linear, "rowwise")
    expected = torch.arange(4, 62, 8, dtype=torch.float32).reshape(8, 1)
    expected = torch.cat([expected, expected + 1], dim=1)
    torch.testing.assert_close(linear.weight, expected)
    assert linear.bias is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "Llama-2-70b-hf",
            {
                "transformer.h.0.attn": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.0.mlp": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.1.attn": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.1.mlp": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.2.attn": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.2.mlp": [("forward_hook", "all_reduce_output", (8,), {})],
            },
        ),
        (
            "falcon-180B",
            {
                "transformer.h.0.attn": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.0.mlp": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.1.attn": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.1.mlp": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.2.attn": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.2.mlp": [("forward_hook", "all_reduce_output", (8,), {})],
            },
        ),
        (
            "Mixtral-8x7B-v0.1",
            {
                "transformer.h.0.attn": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.0.mlp.experts.0": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.0.mlp.experts.1": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.1.attn": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.1.mlp.experts.0": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.1.mlp.experts.1": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.2.attn": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.2.mlp.experts.0": [("forward_hook", "all_reduce_output", (8,), {})],
                "transformer.h.2.mlp.experts.1": [("forward_hook", "all_reduce_output", (8,), {})],
            },
        ),
    ],
)
def test_tensor_parallel_llama(name, expected):
    from generate.tp import tensor_parallel
    from lit_gpt import GPT

    fabric = Mock()
    fabric.world_size = 8
    fabric.global_rank = 1

    with torch.device("meta"):
        model = GPT.from_name(name, n_layer=3, n_expert=2)
    config = replace(model.config)  # make a copy

    model = tensor_parallel(fabric, model)

    hooks = find_forward_hooks(model)
    assert hooks == expected

    assert model.config.n_embd * 8 == config.n_embd
    assert model.config.n_head * 8 == config.n_head
    assert model.config.n_query_groups * 8 == config.n_query_groups


@RunIf(min_cuda_gpus=2)
def test_tp(tmp_path):
    from lit_gpt import GPT, Config
    from scripts.download import download_from_hub

    # download the tokenizer
    download_from_hub(repo_id="EleutherAI/pythia-14m", tokenizer_only=True, checkpoint_dir=tmp_path)
    checkpoint_dir = tmp_path / "EleutherAI/pythia-14m"
    # save the config
    config = Config.from_name("pythia-14m")
    (checkpoint_dir / "lit_config.json").write_text(json.dumps(asdict(config)))
    # create a state dict to load from
    torch.save(GPT(config).state_dict(), checkpoint_dir / "lit_model.pth")

    args = [
        "--num_samples=1",
        "--max_new_tokens=10",
        "--precision=16-true",
        "--temperature=0.0",
        f"--checkpoint_dir={str(checkpoint_dir)}",
    ]
    tp_stdout = subprocess.check_output([sys.executable, "generate/tp.py", *args]).decode()

    # there is some unaccounted randomness so cannot compare the output with that of `generate/base.py`
    assert tp_stdout.startswith("What food do llamas eat?")


def test_cli():
    cli_path = Path(__file__).parent.parent / "generate" / "tp.py"
    output = subprocess.check_output([sys.executable, cli_path, "-h"])
    output = str(output.decode())
    assert "Generates text samples" in output
