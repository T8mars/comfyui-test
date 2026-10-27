"""T8 Cover Studio: generated image + title -> a finished Bilibili / YouTube cover.
Smart crop toward the busiest region, readable scrim on the text side, auto accent colour picked from the image,
big display title with [highlight] words, subtitle pill. Request given to the agent was one sentence."""
import colorsys
import glob
import os
import re

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from comfy_api.latest import IO

HERE = os.path.dirname(os.path.abspath(__file__))
ASPECTS = {"16:10 B站横版": (1920, 1200), "16:9 YouTube": (1920, 1080), "3:4 竖版": (1080, 1440)}
LAYOUTS = ["left", "right", "bottom"]


def _display_font(size):
    f = os.path.join(HERE, "fonts", "SmileySans-Oblique.ttf")
    if os.path.exists(f):
        return ImageFont.truetype(f, size)
    hits = sorted(glob.glob("/usr/share/fonts/**/NotoSansCJK-Black.tt[cf]", recursive=True)) or sorted(glob.glob("C:/Windows/Fonts/msyhbd.tt[cf]"))
    return ImageFont.truetype(hits[0], size) if hits else ImageFont.load_default(size)


def _body_font(size):
    hits = sorted(glob.glob("/usr/share/fonts/**/NotoSansCJK-Bold.tt[cf]", recursive=True)) or sorted(glob.glob("/usr/share/fonts/**/NotoSansCJK*.tt[cf]", recursive=True)) or sorted(glob.glob("C:/Windows/Fonts/msyhbd.tt[cf]"))
    return ImageFont.truetype(hits[0], size) if hits else _display_font(size)


def _smart_crop(im, W, H, layout="left"):
    """crop to W:H; keep the busy region (the subject) out of the zone the title will cover"""
    s = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    e = np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES), np.float32)
    best, bx, by = -1e9, 0, 0
    for x in range(0, im.width - W + 1, max(1, (im.width - W) // 24 or 1)):
        for y in range(0, im.height - H + 1, max(1, (im.height - H) // 24 or 1)):
            c = e[y:y + H, x:x + W]
            text, subj = {"left": (c[:, :W // 2], c[:, W // 2:]), "right": (c[:, W // 2:], c[:, :W // 2]),
                          "bottom": (c[H * 11 // 20:], c[:H * 11 // 20])}[layout]
            v = subj.mean() - 0.7 * text.mean()
            if v > best: best, bx, by = v, x, y
    return im.crop((bx, by, bx + W, by + H))


def _auto_accent(im):
    q = im.resize((160, 160)).quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:24]
    best, col = -1, (255, 106, 26)
    for _, i in q.getcolors():
        r, g, b = pal[i * 3:i * 3 + 3]
        mx, mn = max(r, g, b), min(r, g, b)
        sat = (mx - mn) / (mx + 1e-6)
        score = sat * (mx / 255) * (1 if mx > 110 else 0.2)
        if score > best: best, col = score, (r, g, b)
    # the raw palette colour is often muddy; keep its hue but push it to poster strength
    h, s_, v = colorsys.rgb_to_hsv(*(c / 255 for c in col))
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, max(s_, 0.78), max(v, 0.95)))


def _hex(s):
    s = s.strip().lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) if re.fullmatch(r"[0-9a-fA-F]{6}", s) else None


def _layout_title(d, lines, font, maxw):
    """lines: list of [(text, hl)], returns per-line widths"""
    return [sum(d.textlength(t, font=font) for t, _ in ln) for ln in lines]


class T8CoverStudio(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="T8CoverStudio",
            display_name="T8 Cover Studio (封面工坊)",
            category="T8/image",
            description="生成图 + 标题 → 成品封面：智能裁切、可读性遮罩、自动取主题色、大字标题（[方括号]内为高亮词）、副标题胶囊。",
            inputs=[
                IO.Image.Input("image"),
                IO.String.Input("title", default="ComfyUI\n[过时]了吗？", multiline=True),
                IO.String.Input("subtitle", default="AI 时代的正确用法"),
                IO.Combo.Input("aspect", options=list(ASPECTS), default="16:10 B站横版"),
                IO.Combo.Input("layout", options=LAYOUTS, default="left"),
                IO.String.Input("accent", default="auto", tooltip="auto = 从图里挑最鲜艳的颜色；或填 #FF6A1A"),
                IO.Float.Input("title_scale", default=1.0, min=0.5, max=1.6, step=0.05),
            ],
            outputs=[IO.Image.Output(display_name="cover"), IO.String.Output(display_name="accent_hex")],
        )

    @classmethod
    def execute(cls, image, title, subtitle, aspect, layout, accent, title_scale) -> IO.NodeOutput:
        W, H = ASPECTS[aspect]
        src = Image.fromarray((image[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)).convert("RGB")
        im = _smart_crop(src, W, H, layout).convert("RGBA")
        acc = _hex(accent) or _auto_accent(src)

        # scrim on the text side so the title is always readable
        sc = Image.new("L", (W, H), 0)
        g = np.zeros((H, W), np.float32)
        if layout == "left": g[:] = np.clip(1.15 - np.linspace(0, 1, W)[None, :] * 1.9, 0, 1)
        elif layout == "right": g[:] = np.clip(1.15 - np.linspace(1, 0, W)[None, :] * 1.9, 0, 1)
        else: g[:] = np.clip((np.linspace(0, 1, H)[:, None] - 0.35) * 1.8, 0, 1)
        sc = Image.fromarray((g * 215).astype(np.uint8))
        im = Image.alpha_composite(im, Image.merge("RGBA", (*[Image.new("L", (W, H), 8)] * 3, sc)))

        d = ImageDraw.Draw(im)
        raw = [ln for ln in title.split("\n") if ln.strip()] or [" "]
        lines = [[(m.group(1) or m.group(2), bool(m.group(1))) for m in re.finditer(r"\[([^\]]+)\]|([^\[]+)", ln)] for ln in raw]
        maxw = W * (0.88 if layout == "bottom" else 0.56)
        size = int(H * 0.2 * title_scale)
        while size > 40:
            font = _display_font(size)
            if max(_layout_title(d, lines, font, maxw)) <= maxw and size * 1.08 * len(lines) <= H * (0.5 if layout == "bottom" else 0.62): break
            size -= 6
        font = _display_font(size)
        lh = int(size * 1.08)
        widths = _layout_title(d, lines, font, maxw)
        pad = int(W * 0.06)
        block_h = lh * len(lines)
        sub_font = _body_font(int(size * 0.24))
        sub_h = int(size * 0.24 * 1.9) if subtitle.strip() else 0
        total_h = block_h + (sub_h + int(size * 0.28) if sub_h else 0)
        y0 = (H - total_h) // 2 if layout != "bottom" else H - total_h - int(H * 0.08)
        stroke = max(4, size // 18)

        for k, (ln, w) in enumerate(zip(lines, widths)):
            x = pad if layout in ("left", "bottom") else W - pad - w
            if layout == "bottom": x = (W - w) / 2
            y = y0 + k * lh
            for txt, hl in ln:
                tw = d.textlength(txt, font=font)
                if hl:  # poster block behind highlighted words
                    bx0, by0, bx1, by1 = d.textbbox((x, y), txt, font=font)
                    d.rectangle([bx0 - size * 0.08, by0 - size * 0.04, bx1 + size * 0.08, by1 + size * 0.06], fill=acc + (255,))
                    light = (0.299 * acc[0] + 0.587 * acc[1] + 0.114 * acc[2]) / 255 > 0.62   # light accent -> dark text on the block
                    d.text((x, y), txt, font=font, fill=(12, 12, 16, 255) if light else (255, 255, 255, 255))
                else:
                    d.text((x + stroke * 0.6, y + stroke * 0.9), txt, font=font, fill=(0, 0, 0, 150))
                    d.text((x, y), txt, font=font, fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(10, 10, 14, 255))
                x += tw

        if sub_h:
            tw = d.textlength(subtitle, font=sub_font)
            sx = pad if layout in ("left",) else (W - pad - tw - sub_h if layout == "right" else (W - tw - sub_h) / 2)
            sy = y0 + block_h + int(size * 0.28)
            d.rounded_rectangle([sx, sy, sx + tw + sub_h, sy + sub_h], radius=sub_h // 2, fill=(12, 12, 16, 230), outline=acc + (255,), width=max(3, sub_h // 14))
            d.text((sx + sub_h / 2, sy + sub_h / 2), subtitle, font=sub_font, fill=(255, 255, 255, 255), anchor="lm")

        out = im.convert("RGB")
        return IO.NodeOutput(torch.from_numpy(np.asarray(out).astype(np.float32) / 255.0)[None], "#%02X%02X%02X" % acc)
