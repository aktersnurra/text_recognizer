"""Miscellaneous neural network functionality."""
from typing import Tuple

from einops import rearrange
import torch
from torch.nn import Unfold


def sliding_window(
    images: torch.Tensor, patch_size: Tuple[int, int], stride: Tuple[int, int]
) -> torch.Tensor:
    """Creates patches of an image.

    Args:
        images (torch.Tensor): A Torch tensor of a 4D image(s), i.e. (batch, channel, height, width).
        patch_size (Tuple[int, int]): The size of the patches to generate, e.g. 28x28 for EMNIST.
        stride (Tuple[int, int]): The stride of the sliding window.

    Returns:
        torch.Tensor: A tensor with the shape (batch, patches, height, width).

    """
    unfold = Unfold(kernel_size=patch_size, stride=stride)
    # Preform the slidning window, unsqueeze as the channel dimesion is lost.
    patches = unfold(images).unsqueeze(1)
    patches = rearrange(
        patches, "b c (h w) t -> b t c h w", h=patch_size[0], w=patch_size[1]
    )
    return patches
