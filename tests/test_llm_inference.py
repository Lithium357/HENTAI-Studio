import torch

from hentai_studio.workloads.llm.inference import _has_repeated_token_pattern


def test_repeated_token_pattern_detects_one_to_four_token_loops():
    assert _has_repeated_token_pattern(torch.tensor([9] * 8))
    assert _has_repeated_token_pattern(torch.tensor([3, 7] * 8))
    assert _has_repeated_token_pattern(torch.tensor([1, 2, 3] * 8))
    assert _has_repeated_token_pattern(torch.tensor([4, 5, 6, 7] * 8))


def test_repeated_token_pattern_ignores_normal_short_and_varied_text():
    assert not _has_repeated_token_pattern(torch.tensor([9] * 7))
    assert not _has_repeated_token_pattern(torch.tensor([1, 2, 1, 2, 1, 2, 1, 3] * 2))
