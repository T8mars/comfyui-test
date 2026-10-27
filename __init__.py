"""T8 Tools: utility nodes, written by a coding agent from a one-sentence request.
- T8 Text Watermark: put a (Chinese-capable) text watermark on images, position / size / opacity adjustable
- T8 Cover Studio (cover.py): generated image + title -> finished video cover
- T8 Color Palette: extract the N dominant colours of an image -> swatch image + HEX string
"""
import glob
import os

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from typing_extensions import override

from comfy_api.latest import ComfyExtension, IO

from .cover import T8CoverStudio

POSITIONS = ["bottom_right", "bottom_left", "top_right", "top_left", "center"]


def _font(size):
    for pat in ("/usr/share/fonts/**/NotoSansCJK*.tt[cf]", "/usr/share/fonts/**/*CJK*.tt[cf]", "C:/Windows/Fonts/msyh*.tt[cf]"):
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return ImageFont.truetype(hits[0], size)
    return ImageFont.load_default(size)


class T8TextWatermark(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="T8TextWatermark",
            display_name="T8 Text Watermark",
            category="T8/image",
            inputs=[
                IO.Image.Input("image"),
                IO.String.Input("text", default="@T8star"),
                IO.Combo.Input("position", options=POSITIONS, default="bottom_right"),
                IO.Float.Input("size", default=0.05, min=0.01, max=0.5, step=0.005, tooltip="font height as a fraction of image height"),
                IO.Float.Input("opacity", default=0.6, min=0.0, max=1.0, step=0.05),
                IO.Int.Input("margin", default=24, min=0, max=1024),
            ],
            outputs=[IO.Image.Output()],
        )

    @classmethod
    def execute(cls, image, text, position, size, opacity, margin) -> IO.NodeOutput:
        out = []
        for frame in image:
            im = Image.fromarray((frame.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)).convert("RGBA")
            w, h = im.size
            font = _font(max(8, int(h * size)))
            layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
            tw, th = x1 - x0, y1 - y0
            xs = {"left": margin, "right": w - tw - margin, "center": (w - tw) // 2}
            ys = {"top": margin, "bottom": h - th - margin, "center": (h - th) // 2}
            vy, _, vx = position.partition("_") if position != "center" else ("center", "", "center")
            xy = (xs[vx] - x0, ys[vy] - y0)
            a = int(255 * opacity)
            d.text((xy[0] + 2, xy[1] + 2), text, font=font, fill=(0, 0, 0, a // 2))
            d.text(xy, text, font=font, fill=(255, 255, 255, a))
            im = Image.alpha_composite(im, layer).convert("RGB")
            out.append(torch.from_numpy(np.asarray(im).astype(np.float32) / 255.0))
        return IO.NodeOutput(torch.stack(out))


class T8ColorPalette(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="T8ColorPalette",
            display_name="T8 Color Palette",
            category="T8/image",
            inputs=[
                IO.Image.Input("image"),
                IO.Int.Input("colors", default=5, min=2, max=12),
            ],
            outputs=[IO.Image.Output(display_name="swatch"), IO.String.Output(display_name="hex")],
        )

    @classmethod
    def execute(cls, image, colors) -> IO.NodeOutput:
        im = Image.fromarray((image[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)).convert("RGB")
        q = im.resize((256, 256)).quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette()[: colors * 3]
        counts = sorted(q.getcolors(), reverse=True)
        rgb = [tuple(pal[i * 3: i * 3 + 3]) for _, i in counts][:colors]
        sw = Image.new("RGB", (128 * len(rgb), 128))
        d = ImageDraw.Draw(sw)
        for k, c in enumerate(rgb):
            d.rectangle([k * 128, 0, k * 128 + 127, 127], fill=c)
        hexes = ",".join("#%02X%02X%02X" % c for c in rgb)
        return IO.NodeOutput(torch.from_numpy(np.asarray(sw).astype(np.float32) / 255.0)[None], hexes)


class T8ToolsExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[IO.ComfyNode]]:
        return [T8CoverStudio, T8TextWatermark, T8ColorPalette]


async def comfy_entrypoint() -> T8ToolsExtension:
    return T8ToolsExtension()
