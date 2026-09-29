"""Draws the bridge's job badges (bot/badges/<JOB>.png): a round crest per job in its color, the
job's letters and name, a crystal behind. All drawn here, no game art. The ones in bot/badges were
made with this; change the colors or the font and run it again to make your own.

    python3 -m pip install Pillow
    python3 tools/make_job_badges.py [--font /path/to/a/bold-serif.ttf]
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "bot", "badges")
SIZE = 512
SCALE = 2  # drawn at twice the size, then reduced: smooth edges

# job id (as the game numbers them), letters, name, color
JOBS = [
    (1, "WAR", "Warrior", "#B3261E"),
    (2, "MNK", "Monk", "#D9772B"),
    (3, "WHM", "White Mage", "#EDE6D6"),
    (4, "BLM", "Black Mage", "#1D2555"),
    (5, "RDM", "Red Mage", "#9C1631"),
    (6, "THF", "Thief", "#2F7A3B"),
    (7, "PLD", "Paladin", "#9DAABB"),
    (8, "DRK", "Dark Knight", "#3A2141"),
    (9, "BST", "Beastmaster", "#7A5230"),
    (10, "BRD", "Bard", "#C79C1E"),
    (11, "RNG", "Ranger", "#5B7A2C"),
    (12, "SAM", "Samurai", "#23406B"),
    (13, "NIN", "Ninja", "#262629"),
    (14, "DRG", "Dragoon", "#2C6F8E"),
    (15, "SMN", "Summoner", "#6A3FA0"),
    (16, "BLU", "Blue Mage", "#1F7FC4"),
    (17, "COR", "Corsair", "#A8452A"),
    (18, "PUP", "Puppetmaster", "#8C6A9E"),
    (19, "DNC", "Dancer", "#CF4F8B"),
    (20, "SCH", "Scholar", "#4A5B7B"),
    (21, "GEO", "Geomancer", "#2F8C7A"),
    (22, "RUN", "Rune Fencer", "#6FA3CC"),
]
# a player with no job yet, or one this list does not know
OTHER = (0, "XI", "Adventurer", "#5A5F6E")

FONT = "/System/Library/Fonts/Supplemental/Copperplate.ttc"  # macOS; any bold serif capitals will do
for i, a in enumerate(__import__("sys").argv):
    if a == "--font" and i + 1 < len(__import__("sys").argv):
        FONT = __import__("sys").argv[i + 1]


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def light(rgb):
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b > 150


def font(size, bold=True):
    try:
        return ImageFont.truetype(FONT, size, index=1 if bold else 0)
    except OSError:
        return ImageFont.load_default(size)


def badge(letters, name, color):
    S = SIZE * SCALE
    c = S / 2
    base = hex_rgb(color)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # the face: the job's color, lighter at the top left, darker at the bottom right
    face = Image.new("RGBA", (S, S))
    fd = ImageDraw.Draw(face)
    for i in range(S):
        t = i / S
        fd.line([(0, i), (S, i)], fill=mix(mix(base, (255, 255, 255), 0.22), mix(base, (0, 0, 0), 0.35), t) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([S * 0.055, S * 0.055, S * 0.945, S * 0.945], fill=255)
    img.paste(face, (0, 0), mask)

    # a crystal behind the letters
    ink = (0, 0, 0) if light(base) else (255, 255, 255)
    crystal = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(crystal)
    w, h = S * 0.20, S * 0.36
    pts = [(c, c - h), (c + w, c - h * 0.15), (c + w * 0.7, c + h * 0.55), (c, c + h), (c - w * 0.7, c + h * 0.55), (c - w, c - h * 0.15)]
    cd.polygon(pts, fill=ink + (26,))
    cd.line(pts + [pts[0]], fill=ink + (45,), width=int(S * 0.006))
    cd.line([pts[0], (c, c + h)], fill=ink + (30,), width=int(S * 0.004))
    img.alpha_composite(crystal)

    # the rim: gold, a fine dark line inside it
    gold, gold_dark = (212, 175, 90), (120, 88, 30)
    d.ellipse([S * 0.02, S * 0.02, S * 0.98, S * 0.98], outline=gold_dark, width=int(S * 0.04))
    d.ellipse([S * 0.028, S * 0.028, S * 0.972, S * 0.972], outline=gold, width=int(S * 0.026))
    d.ellipse([S * 0.07, S * 0.07, S * 0.93, S * 0.93], outline=mix(base, (0, 0, 0), 0.55) + (255,), width=int(S * 0.008))
    # four studs on the rim
    for a in range(4):
        ang = math.pi / 4 + a * math.pi / 2
        x, y = c + math.cos(ang) * S * 0.465, c + math.sin(ang) * S * 0.465
        r = S * 0.018
        d.ellipse([x - r, y - r, x + r, y + r], fill=(245, 222, 150), outline=gold_dark, width=int(S * 0.004))

    # the letters, with a soft shadow; the name under them
    text_color = (40, 30, 20) if light(base) else (255, 248, 235)
    shadow_color = (255, 255, 255, 110) if light(base) else (0, 0, 0, 150)
    big = font(int(S * (0.30 if len(letters) == 3 else 0.36)))
    small = font(int(S * 0.072))

    def centered(draw, y, text, f, fill):
        box = draw.textbbox((0, 0), text, font=f)
        draw.text((c - (box[2] - box[0]) / 2 - box[0], y - (box[3] - box[1]) / 2 - box[1]), text, font=f, fill=fill)

    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    centered(ImageDraw.Draw(shadow), c - S * 0.035 + S * 0.012, letters, big, shadow_color)
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(S * 0.008)))
    centered(d, c - S * 0.035, letters, big, text_color)
    centered(d, c + S * 0.215, name.upper(), small, text_color)

    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    for _, letters, name, color in JOBS + [OTHER]:
        badge(letters, name, color).save(os.path.join(OUT, f"{letters}.png"), optimize=True)
    # a sheet of them all, to look at
    cols, cell = 6, 180
    sheet = Image.new("RGBA", (cols * cell, ((len(JOBS) + 1 + cols - 1) // cols) * cell), (54, 57, 63, 255))
    for i, (_, letters, _, _) in enumerate(JOBS + [OTHER]):
        im = Image.open(os.path.join(OUT, f"{letters}.png")).resize((cell - 20, cell - 20), Image.LANCZOS)
        sheet.alpha_composite(im, ((i % cols) * cell + 10, (i // cols) * cell + 10))
    sheet.save(os.path.join(HERE, "..", "docs", "badges.png"))
    print(f"{len(JOBS) + 1} badges in {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
