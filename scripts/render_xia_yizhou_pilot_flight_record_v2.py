from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import argparse
import math
import random


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "xia_yizhou_613_pilot_flight_record_v2.png"
CHINESE_SIGNATURE_ASSET = ROOT / "assets" / "xia_yizhou_chinese_signature.png"
ID_PHOTO_ASSET = ROOT / "assets" / "xia_yizhou_id_photo.jpg"
FLEET_STAMP_ASSET = ROOT / "assets" / "farspace_fleet_stamp_mask.png"
COORD_CODE = ".1263 056 8 6 [0171]"

W, H = 3000, 1900
PAPER = (247, 241, 230)
BG = (225, 222, 212)
INK = (31, 30, 32)
MUTED = (91, 93, 91)
LIGHT = (218, 211, 199)
LINE = (42, 49, 56)
HEADER = (32, 38, 47)
ROUTE = (42, 95, 126)
ROUTE_LIGHT = (210, 111, 54)
ORANGE = (202, 91, 43)
GOLD = (219, 166, 79)
BLUE = (82, 122, 156)
VIOLET = (118, 99, 150)
PINK = (190, 126, 139)

def first_existing(*paths):
    for path in paths:
        if Path(path).exists():
            return path
    return paths[-1]


FONT_HEI = first_existing(
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
FONT_HEI_LIGHT = first_existing(
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
FONT_SONG = first_existing(
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
)
FONT_TIMES = first_existing(
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
)
FONT_TIMES_BOLD = first_existing(
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
)
FONT_SANS = first_existing(
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
FONT_SIGNATURE = first_existing(
    "/System/Library/Fonts/Supplemental/Savoye LET.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
)


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def fit_font(path, text, max_width, start_size, min_size=18):
    size = start_size
    while size >= min_size:
        candidate = font(path, size)
        bbox = candidate.getbbox(text)
        if bbox[2] - bbox[0] <= max_width:
            return candidate
        size -= 2
    return font(path, min_size)


def draw_fitted_text(draw, xy, text, font_path, max_width, start_size, min_size, fill):
    fitted = fit_font(font_path, text, max_width, start_size, min_size)
    draw.text(xy, text, font=fitted, fill=fill)
    return fitted


def paper_texture(size, seed=626):
    random.seed(seed)
    img = Image.new("RGBA", size, PAPER + (255,))
    d = ImageDraw.Draw(img, "RGBA")
    w, h = size
    for _ in range(2600):
        x = random.randrange(w)
        y = random.randrange(h)
        alpha = random.randrange(6, 22)
        col = random.choice([(255, 250, 238, alpha), (179, 164, 146, alpha), (70, 65, 66, alpha // 2)])
        d.point((x, y), fill=col)
    return img


def hydrangea_wash(size, seed=26):
    random.seed(seed)
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    palette = [
        ORANGE + (45,),
        GOLD + (38,),
        BLUE + (40,),
        VIOLET + (36,),
        PINK + (28,),
        (50, 58, 70, 24),
    ]
    for _ in range(70):
        cx = random.randint(-70, w + 70)
        cy = random.randint(-50, h + 50)
        base = random.choice(palette)
        for _ in range(random.randint(3, 8)):
            r = random.randint(18, 54)
            x = cx + random.randint(-76, 76)
            y = cy + random.randint(-48, 48)
            d.ellipse((x - r, y - r, x + r, y + r), fill=base)
    return img.filter(ImageFilter.GaussianBlur(2.2))


def draw_grid(draw, box, step=58):
    x1, y1, x2, y2 = box
    for x in range(x1, x2 + 1, step):
        draw.line((x, y1, x, y2), fill=(204, 197, 184, 92), width=1)
    for y in range(y1, y2 + 1, step):
        draw.line((x1, y, x2, y), fill=(204, 197, 184, 92), width=1)


def field(
    draw,
    x,
    y,
    w,
    label,
    value=None,
    blank=False,
    line_offset=82,
    line_width=3,
    value_size=42,
    value_min_size=22,
    value_font_path=FONT_HEI,
):
    draw.text((x, y), label, font=font(FONT_HEI_LIGHT, 23), fill=MUTED)
    line_y = y + line_offset
    draw.line((x, line_y, x + w, line_y), fill=LINE, width=line_width)
    if value:
        value_font = fit_font(value_font_path, value, w - 16, value_size, value_min_size)
        bbox = draw.textbbox((0, 0), value, font=value_font)
        draw.text((x + 8, line_y - bbox[3] - 3), value, font=value_font, fill=INK)
    if blank:
        return


def checkbox(draw, x, y, text, checked=True):
    draw.rectangle((x, y, x + 28, y + 28), outline=LINE, width=3)
    if checked:
        draw.line((x + 5, y + 14, x + 12, y + 23), fill=ORANGE, width=3)
        draw.line((x + 12, y + 23, x + 25, y + 5), fill=ORANGE, width=3)
    draw.text((x + 42, y - 4), text, font=font(FONT_HEI_LIGHT, 28), fill=MUTED)


def draw_plane(draw, cx, cy, scale=1.0, fill=INK):
    pts = [
        (cx + 72 * scale, cy),
        (cx - 70 * scale, cy - 25 * scale),
        (cx - 45 * scale, cy),
        (cx - 70 * scale, cy + 25 * scale),
    ]
    draw.polygon(pts, fill=fill)
    draw.polygon([(cx - 5 * scale, cy - 6 * scale), (cx - 56 * scale, cy - 72 * scale), (cx + 15 * scale, cy - 15 * scale)], fill=fill)
    draw.polygon([(cx - 5 * scale, cy + 6 * scale), (cx - 56 * scale, cy + 72 * scale), (cx + 15 * scale, cy + 15 * scale)], fill=fill)
    draw.polygon([(cx - 57 * scale, cy - 10 * scale), (cx - 96 * scale, cy - 44 * scale), (cx - 78 * scale, cy - 3 * scale)], fill=fill)
    draw.polygon([(cx - 57 * scale, cy + 10 * scale), (cx - 96 * scale, cy + 44 * scale), (cx - 78 * scale, cy + 3 * scale)], fill=fill)


def draw_coordinate_symbol(draw, cx, cy, r, fill, width=3):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=fill, width=width)
    draw.line((cx - r * 0.62, cy + r * 0.62, cx + r * 0.62, cy - r * 0.62), fill=fill, width=width)


def draw_coordinate_line(draw, x, y, size=30, fill=MUTED, coord_code=COORD_CODE):
    r = int(size * 0.43)
    cy = y + int(size * 0.55)
    draw_coordinate_symbol(draw, x + r, cy, r, fill, max(2, int(size * 0.08)))
    draw.text((x + size * 1.08, y), coord_code, font=font(FONT_SANS, size), fill=fill)


def cubic(p0, p1, p2, p3, steps=38):
    points = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def draw_caleb_signature(canvas, x, y, scale=0.54):
    # Clean redraw based on the supplied grey Caleb signature reference.
    hi = 3
    w, h = 560, 250
    layer = Image.new("RGBA", (w * hi, h * hi), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sig = (154, 151, 134, 218)

    def pts(seq):
        return [(int(px * hi), int(py * hi)) for px, py in seq]

    strokes = [
        cubic((22, 178), (12, 128), (72, 54), (150, 82), 42),
        cubic((150, 82), (105, 83), (64, 152), (112, 143), 34),
        cubic((82, 150), (142, 131), (178, 122), (220, 122), 30),
        cubic((218, 123), (190, 112), (197, 88), (229, 97), 24),
        cubic((229, 97), (212, 105), (202, 135), (231, 124), 24),
        cubic((234, 125), (266, 76), (300, 26), (315, 34), 42),
        cubic((315, 34), (288, 60), (262, 102), (252, 128), 34),
        cubic((252, 128), (286, 111), (310, 114), (321, 126), 28),
        cubic((321, 126), (346, 78), (385, 32), (402, 40), 42),
        cubic((402, 40), (376, 66), (348, 105), (340, 126), 34),
        cubic((340, 126), (376, 124), (399, 91), (430, 85), 28),
        cubic((390, 118), (444, 102), (494, 66), (535, 54), 40),
    ]
    for stroke in strokes:
        d.line(pts(stroke), fill=sig, width=6 * hi, joint="curve")
    # The reference has a long, faint lower sweep through the word.
    sweep = cubic((118, 147), (210, 132), (330, 117), (442, 86), 58)
    d.line(pts(sweep), fill=(154, 151, 134, 112), width=4 * hi, joint="curve")

    layer = layer.filter(ImageFilter.GaussianBlur(0.22 * hi))
    bbox = layer.getbbox()
    if bbox:
        layer = layer.crop(bbox)
    target = (max(1, int(layer.width * scale / hi)), max(1, int(layer.height * scale / hi)))
    layer = layer.resize(target, Image.Resampling.LANCZOS)
    canvas.alpha_composite(layer, (int(x), int(y)))


def paste_caleb_mark(canvas, x, y, width=350):
    hi = 4
    layer = Image.new("RGBA", (660 * hi, 235 * hi), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    sig = (154, 151, 134, 126)
    coord = (126, 121, 116, 190)
    plane = (231, 148, 70, 182)

    def pts(seq):
        return [(int(px * hi), int(py * hi)) for px, py in seq]

    strokes = [
        cubic((162, 83), (96, 36), (42, 78), (72, 116), 50),
        cubic((72, 116), (106, 158), (170, 126), (190, 105), 42),
        cubic((190, 105), (209, 88), (232, 103), (206, 118), 32),
        cubic((205, 118), (250, 117), (290, 94), (326, 101), 42),
        cubic((326, 101), (362, 108), (404, 90), (448, 77), 52),
    ]
    for stroke in strokes:
        d.line(pts(stroke), fill=sig, width=5 * hi, joint="curve")
    d.ellipse((344 * hi, 62 * hi, 351 * hi, 69 * hi), fill=sig)
    draw_plane(d, 508 * hi, 92 * hi, 0.40 * hi, fill=plane)

    draw_coordinate_symbol(d, 92 * hi, 165 * hi, 23 * hi, coord, width=4 * hi)
    d.text((136 * hi, 132 * hi), COORD_CODE, font=font(FONT_SANS, 50 * hi), fill=coord)

    layer = layer.filter(ImageFilter.GaussianBlur(0.10 * hi))
    bbox = layer.getbbox()
    if bbox:
        layer = layer.crop(bbox)
    ratio = width / layer.width
    layer = layer.resize((width, max(1, int(layer.height * ratio))), Image.Resampling.LANCZOS)
    canvas.alpha_composite(layer, (int(x), int(y)))


def paste_chinese_signature(canvas, x, y, width=322, opacity=0.82):
    if CHINESE_SIGNATURE_ASSET.exists():
        sig = Image.open(CHINESE_SIGNATURE_ASSET).convert("RGBA")
        bbox = sig.getbbox()
        if bbox:
            sig = sig.crop(bbox)
        ratio = width / sig.width
        sig = sig.resize((width, max(1, int(sig.height * ratio))), Image.Resampling.LANCZOS)
        sig.putalpha(sig.getchannel("A").point(lambda a: int(a * opacity)))
        canvas.alpha_composite(sig, (int(x), int(y)))
        return

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((x, y), "夏以昼", font=font(FONT_HEI_LIGHT, 92), fill=(39, 42, 45, int(220 * opacity)))


def paste_id_photo(canvas, x, y, width=260, height=340):
    if not ID_PHOTO_ASSET.exists():
        return
    pad = 10
    layer = Image.new("RGBA", (width + pad * 2, height + pad * 2), (246, 241, 230, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    d.rectangle((0, 0, layer.width - 1, layer.height - 1), fill=(247, 241, 230, 238), outline=LINE + (230,), width=3)
    d.rectangle((pad - 1, pad - 1, pad + width, pad + height), outline=(255, 255, 255, 235), width=3)

    photo = Image.open(ID_PHOTO_ASSET).convert("RGBA")
    photo.thumbnail((width, height), Image.Resampling.LANCZOS)
    photo_x = pad + (width - photo.width) // 2
    photo_y = pad + (height - photo.height) // 2
    d.rectangle((pad, pad, pad + width, pad + height), fill=HEADER + (246,))
    layer.alpha_composite(photo, (photo_x, photo_y))
    canvas.alpha_composite(layer, (int(x), int(y)))


def paste_emboss_stamp(canvas, x, y, width=126, opacity=0.78):
    if not FLEET_STAMP_ASSET.exists():
        return
    stamp = Image.open(FLEET_STAMP_ASSET).convert("RGBA")
    bbox = stamp.getbbox()
    if bbox:
        stamp = stamp.crop(bbox)
    ratio = width / stamp.width
    stamp = stamp.resize((width, max(1, int(stamp.height * ratio))), Image.Resampling.LANCZOS)
    alpha = stamp.getchannel("A").point(lambda a: int(a * opacity))
    margin = 10
    layer = Image.new("RGBA", (stamp.width + margin * 2, stamp.height + margin * 2), (0, 0, 0, 0))

    def add_pass(offset, color, scale, blur=0):
        mask = alpha.point(lambda a: int(a * scale))
        if blur:
            mask = mask.filter(ImageFilter.GaussianBlur(blur))
        color_layer = Image.new("RGBA", mask.size, color)
        color_layer.putalpha(mask)
        layer.alpha_composite(color_layer, (margin + offset[0], margin + offset[1]))

    add_pass((3, 3), (92, 98, 90, 255), 0.34, 0.45)
    add_pass((-2, -2), (255, 252, 238, 255), 0.56, 0.35)
    add_pass((0, 0), (174, 178, 164, 255), 0.22, 0)
    add_pass((1, 1), (128, 134, 123, 255), 0.16, 0)
    canvas.alpha_composite(layer, (int(x - margin), int(y - margin)))


def draw_route_map(draw, box, coord_code=COORD_CODE):
    x1, y1, x2, y2 = box
    dark = (24, 30, 39)
    grid_blue = (87, 134, 169)
    star = (238, 220, 167)
    draw.rectangle(box, fill=dark + (255,), outline=LINE, width=4)
    draw.text((x1 + 34, y1 + 28), "INTERSTELLAR COORDINATE MAP", font=font(FONT_TIMES_BOLD, 30), fill=(246, 241, 228))
    confirmed = "TARGET CONFIRMED"
    confirmed_font = fit_font(FONT_TIMES_BOLD, confirmed, 260, 22, 16)
    confirmed_box = draw.textbbox((0, 0), confirmed, font=confirmed_font)
    confirmed_w = confirmed_box[2] - confirmed_box[0]
    draw.text((x2 - 76 - confirmed_w, y1 + 30), confirmed, font=confirmed_font, fill=(210, 196, 176))

    random.seed(260613)
    for _ in range(150):
        sx = random.randint(x1 + 34, x2 - 34)
        sy = random.randint(y1 + 76, y2 - 44)
        r = random.choice([1, 1, 1, 2, 2, 3])
        alpha = random.randint(82, 210)
        col = random.choice([star + (alpha,), (156, 188, 211, alpha), (209, 112, 62, alpha)])
        draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=col)

    cx, cy = x1 + 620, y1 + 335
    max_r = 252
    for r in range(58, max_r + 1, 48):
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=grid_blue + (86,), width=2)
    for angle in range(0, 360, 15):
        rad = math.radians(angle)
        ex = cx + math.cos(rad) * max_r
        ey = cy + math.sin(rad) * max_r
        width = 2 if angle % 45 == 0 else 1
        fill = ORANGE + (122,) if angle % 45 == 0 else grid_blue + (70,)
        draw.line((cx, cy, ex, ey), fill=fill, width=width)
    draw.line((cx - max_r - 40, cy, cx + max_r + 40, cy), fill=grid_blue + (110,), width=2)
    draw.line((cx, cy - max_r - 30, cx, cy + max_r + 30), fill=grid_blue + (110,), width=2)
    draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=ORANGE)
    draw.text((cx + 18, cy - 28), "GRAVITY ORIGIN", font=font(FONT_TIMES_BOLD, 22), fill=(210, 196, 176))

    worm_x, worm_y = x2 - 330, y1 + 305
    for r, color, width in [
        (132, ORANGE, 5),
        (104, GOLD, 3),
        (78, grid_blue, 2),
        (44, (246, 241, 228), 2),
    ]:
        draw.ellipse((worm_x - r, worm_y - r, worm_x + r, worm_y + r), outline=color + (210,), width=width)
    for angle in range(-35, 225, 26):
        rad = math.radians(angle)
        px = worm_x + math.cos(rad) * 150
        py = worm_y + math.sin(rad) * 74
        draw.line((worm_x, worm_y, px, py), fill=ORANGE + (75,), width=2)
    vector_label = "FIXED TARGET VECTOR"
    vector_font = fit_font(FONT_TIMES_BOLD, vector_label, 260, 20, 16)
    vector_box = draw.textbbox((0, 0), vector_label, font=vector_font)
    vector_w = vector_box[2] - vector_box[0]
    vector_x = min(worm_x - 128, x2 - 76 - vector_w)
    draw.text((vector_x, worm_y - 172), vector_label, font=vector_font, fill=(246, 241, 228))

    path = [
        (x1 + 110, y2 - 105),
        (x1 + 330, y1 + 385),
        (cx - 22, cy + 36),
        (x1 + 930, y1 + 170),
        (worm_x - 118, worm_y + 54),
        (worm_x, worm_y),
    ]
    for i in range(len(path) - 1):
        a = path[i]
        b = path[i + 1]
        bend = -48 if i % 2 == 0 else 52
        for step in range(42):
            u1 = step / 42
            u2 = (step + 1) / 42
            xa = a[0] * (1 - u1) + b[0] * u1
            ya = a[1] * (1 - u1) + b[1] * u1 + math.sin(u1 * math.pi) * bend
            xb = a[0] * (1 - u2) + b[0] * u2
            yb = a[1] * (1 - u2) + b[1] * u2 + math.sin(u2 * math.pi) * bend
            draw.line((xa, ya, xb, yb), fill=BLUE, width=7)
            draw.line((xa, ya + 11, xb, yb + 11), fill=ORANGE, width=3)
    node_coordinates = [
        (path[1], "3621-456-56", (36, -64)),
        (path[2], "78654-007019", (-215, 40)),
        (path[3], "I s358G 1504s32.", (36, -64)),
    ]
    for (nx, ny), label, (dx, dy) in node_coordinates:
        draw.ellipse((nx - 26, ny - 26, nx + 26, ny + 26), fill=dark + (255,), outline=ORANGE, width=5)
        lx, ly = nx + dx, ny + dy
        label_font = font(FONT_SANS, 22)
        bbox = draw.textbbox((lx, ly), label, font=label_font)
        pad_x, pad_y = 12, 6
        tag = (bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y)
        draw.rounded_rectangle(tag, radius=4, fill=(24, 30, 39, 212), outline=ORANGE + (172,), width=2)
        draw.line((nx, ny, tag[0] if dx > 0 else tag[2], (tag[1] + tag[3]) / 2), fill=ORANGE + (150,), width=2)
        draw.text((lx, ly), label, font=label_font, fill=(246, 241, 228))
    draw_plane(draw, worm_x - 122, worm_y + 72, 0.62, fill=(246, 241, 228))

    title_text = "DESTINATION COORDINATE / 目的地坐标"
    title_font = fit_font(FONT_HEI, title_text, 390, 24, 18)
    coord_font = font(FONT_SANS, 36)
    coord_bbox = draw.textbbox((0, 0), coord_code, font=coord_font)
    coord_w = coord_bbox[2] - coord_bbox[0]
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    symbol_r = 16
    panel_pad_x = 32
    coord_text_offset = symbol_r * 2 + 16
    panel_w = int(max(panel_pad_x * 2 + coord_text_offset + coord_w, title_w + 126))
    panel_h = 142
    panel_shift_left = 130
    panel = (x2 - 38 - panel_shift_left - panel_w, y2 - 34 - panel_h, x2 - 38 - panel_shift_left, y2 - 34)
    px1, py1, px2, py2 = panel
    draw.rounded_rectangle((px1 + 10, py1 + 12, px2 + 10, py2 + 12), radius=6, fill=(0, 0, 0, 82))
    draw.rounded_rectangle(panel, radius=6, fill=PAPER + (238,), outline=ORANGE + (235,), width=3)
    draw.rectangle((px1, py1, px2, py1 + 48), fill=HEADER + (246,))
    draw.rectangle((px1, py1, px1 + 10, py2), fill=ORANGE + (246,))
    draw.text((px1 + 28, py1 + 11), title_text, font=title_font, fill=(246, 241, 228))
    for i in range(3):
        x = px2 - 82 + i * 23
        draw.rectangle((x, py1 + 20, x + 13, py1 + 26), fill=GOLD + (210,))

    for gx in range(px1 + 34, px2 - 26, 44):
        draw.line((gx, py1 + 58, gx, py2 - 22), fill=(183, 176, 162, 30), width=1)
    for gy in range(py1 + 64, py2 - 16, 30):
        draw.line((px1 + 24, gy, px2 - 22, gy), fill=(183, 176, 162, 30), width=1)

    tick = 22
    for sx, sy in [(px1 + 24, py1 + 64), (px2 - 24, py1 + 64), (px1 + 24, py2 - 24), (px2 - 24, py2 - 24)]:
        x_dir = 1 if sx < (px1 + px2) / 2 else -1
        y_dir = 1 if sy < (py1 + py2) / 2 else -1
        draw.line((sx, sy, sx + tick * x_dir, sy), fill=ORANGE + (190,), width=2)
        draw.line((sx, sy, sx, sy + tick * y_dir), fill=ORANGE + (190,), width=2)

    coord_y = py1 + 80
    draw_coordinate_symbol(draw, px1 + panel_pad_x + symbol_r, coord_y + 22, symbol_r, ORANGE + (232,), width=3)
    draw.text((px1 + panel_pad_x + coord_text_offset, coord_y), coord_code, font=coord_font, fill=(58, 56, 54, 235))
    draw.line((px1 + 30, py2 - 29, px2 - 30, py2 - 29), fill=LINE + (125,), width=2)

    draw.text((x1 + 52, y2 - 70), "ORIGIN: MISSING YEAR", font=font(FONT_TIMES_BOLD, 26), fill=(210, 196, 176))


def draw_table(draw, box):
    x1, y1, x2, y2 = box
    draw.rectangle(box, fill=(244, 245, 236, 135), outline=LINE, width=4)
    cols = [x1, x1 + 330, x1 + 710, x1 + 1160, x2]
    headers = ["DATE", "CHECKPOINT", "LANDING SITE", "NOTE"]
    for x in cols[1:-1]:
        draw.line((x, y1, x, y2), fill=LIGHT, width=3)
    row_h = 78
    for i in range(1, 6):
        y = y1 + i * row_h
        draw.line((x1, y, x2, y), fill=LIGHT, width=3)
    for i, h in enumerate(headers):
        draw.text((cols[i] + 22, y1 + 22), h, font=font(FONT_TIMES_BOLD, 22), fill=MUTED)
    rows = [
        ("2024.06.25-07.10", "ENTWINED SHADOWS", "SHADOW'S HAVEN", "If my shadow belongs anywhere, it must be by your side."),
        ("2024.08.07-08.27", "MISTY INVASION", "MISTED PROXIMITY", "It's already misting over. Are you still pretending you can see clearly?"),
        ("2024.11.12-11.30", "YES, CAT CARETAKER", "TAME SIGNAL", "At your command. But this time... I make the rules."),
        ("2024.12.31-2025.01.20", "NIGHTLY RENDEZVOUS", "DAYBREAK'S EDGE", "If the darkness of that day took me from you, let this dawn bring me back."),
    ]
    for r, row in enumerate(rows, start=1):
        y = y1 + r * row_h + 19
        if not any(row):
            continue
        cell_pad = 22
        draw_fitted_text(draw, (cols[0] + cell_pad, y), row[0], FONT_TIMES_BOLD, cols[1] - cols[0] - cell_pad * 2, 25, 15, INK)
        draw_fitted_text(draw, (cols[1] + cell_pad, y), row[1], FONT_TIMES_BOLD, cols[2] - cols[1] - cell_pad * 2, 25, 15, INK)
        draw_fitted_text(draw, (cols[2] + cell_pad, y), row[2], FONT_TIMES_BOLD, cols[3] - cols[2] - cell_pad * 2, 25, 15, INK)
        draw_fitted_text(draw, (cols[3] + cell_pad, y), row[3], FONT_TIMES_BOLD, cols[4] - cols[3] - cell_pad * 2, 25, 15, MUTED)


def draw_instrument(draw, cx, cy, r, label, value):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=LINE, width=4, fill=PAPER + (150,))
    for i in range(12):
        angle = -math.pi / 2 + i * math.tau / 12
        x1 = cx + math.cos(angle) * (r - 12)
        y1 = cy + math.sin(angle) * (r - 12)
        x2 = cx + math.cos(angle) * (r - 28)
        y2 = cy + math.sin(angle) * (r - 28)
        draw.line((x1, y1, x2, y2), fill=ORANGE if i % 3 == 0 else LINE, width=2)
    draw.text((cx - r + 24, cy - 22), value, font=font(FONT_TIMES_BOLD, 38), fill=INK)
    draw.text((cx - r + 24, cy + 24), label, font=font(FONT_TIMES, 22), fill=MUTED)


def generate_record(
    destination_name="",
    destination_coordinate=COORD_CODE,
    out_path=OUT,
    pdf_path=None,
    show_callsign=False,
    show_stamp=True,
):
    destination_name = (destination_name or "").strip()
    destination_coordinate = (destination_coordinate or COORD_CODE).strip()
    out_path = Path(out_path)
    canvas = Image.new("RGBA", (W, H), BG + (255,))
    draw = ImageDraw.Draw(canvas, "RGBA")
    for x in range(0, W, 34):
        draw.line((x, 0, x, H), fill=(246, 248, 239, 52), width=1)
    for y in range(0, H, 34):
        draw.line((0, y, W, y), fill=(246, 248, 239, 52), width=1)

    page_box = (150, 115, W - 150, H - 115)
    shadow = Image.new("RGBA", (page_box[2] - page_box[0] + 44, page_box[3] - page_box[1] + 44), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.rectangle((24, 24, shadow.width - 20, shadow.height - 20), fill=(0, 0, 0, 42))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    canvas.alpha_composite(shadow, (page_box[0] - 16, page_box[1] - 16))

    page = paper_texture((page_box[2] - page_box[0], page_box[3] - page_box[1]))
    page.alpha_composite(hydrangea_wash(page.size), (0, 0))
    canvas.alpha_composite(page, page_box[:2])
    draw.rectangle(page_box, outline=LINE, width=7)

    x1, y1, x2, y2 = page_box
    draw.rectangle((x1, y1, x2, y1 + 210), fill=HEADER + (242,))
    draw.rectangle((x1, y1 + 190, x2, y1 + 210), fill=ORANGE + (238,))
    draw.rectangle((x1 + 72, y1 + 34, x1 + 92, y1 + 164), fill=ORANGE + (230,))
    draw.text((x1 + 72, y1 + 48), "PILOT FLIGHT RECORD", font=font(FONT_TIMES_BOLD, 58), fill=(248, 249, 238))
    draw.text((x1 + 76, y1 + 122), "飞行纪录", font=font(FONT_HEI_LIGHT, 36), fill=(217, 224, 211))
    if show_callsign:
        callsign = "CALEB"
        callsign_font = font(FONT_TIMES_BOLD, 52)
        callsign_box = draw.textbbox((0, 0), callsign, font=callsign_font)
        callsign_x = x2 - 94 - (callsign_box[2] - callsign_box[0])
        draw.text((callsign_x, y1 + 74), callsign, font=callsign_font, fill=(248, 249, 238))
    body_top = y1 + 260
    field(draw, x1 + 76, body_top, 470, "PILOT / 飞行员", "CALEB / 夏以昼")
    field(draw, x1 + 620, body_top, 360, "AIRCRAFT MODEL / 飞机型号", "FY26")
    field(draw, x1 + 1055, body_top, 420, "LOG NO. / 记录编号", "00100011100110111")
    field(draw, x1 + 1550, body_top, 360, "DATE / 日期", "6/13")

    dest_y = body_top + 140
    mission_x1 = x1 + 76
    mission_x2 = x1 + 510
    field(
        draw,
        mission_x1,
        dest_y + 12,
        mission_x2 - mission_x1,
        "MISSION / 任务",
        "RETURN / 返航",
        line_offset=124,
        line_width=4,
        value_size=42,
    )

    name_x1 = x1 + 590
    name_x2 = x1 + 1680
    field(
        draw,
        name_x1,
        dest_y + 12,
        name_x2 - name_x1,
        "MISSION TARGET / 任务目标",
        destination_name if destination_name else None,
        blank=not destination_name,
        line_offset=124,
        line_width=4,
        value_size=48,
        value_min_size=24,
    )

    map_box = (x1 + 76, dest_y + 210, x1 + 1680, dest_y + 820)
    draw_route_map(draw, map_box, destination_coordinate)

    side_x = x1 + 1745
    panel_top = dest_y + 24
    panel_bottom = dest_y + 820
    panel_box = (side_x, panel_top, x2 - 76, panel_bottom)
    draw.rectangle(panel_box, fill=(244, 245, 236, 122), outline=LINE, width=4)
    draw.text((side_x + 34, panel_top + 34), "RECORD REVIEW / 记录审核", font=font(FONT_HEI, 31), fill=INK)
    photo_slot_x = side_x + 550
    photo_outer_w = 240 + 20
    photo_x = photo_slot_x + ((x2 - 110) - photo_slot_x - photo_outer_w) // 2
    paste_id_photo(canvas, photo_x, panel_top + 28, width=240, height=320)
    checkbox(draw, side_x + 38, panel_top + 106, "COORDINATE LOGGED", True)
    checkbox(draw, side_x + 38, panel_top + 162, "ROUTE TRACE FILED", True)
    checkbox(draw, side_x + 38, panel_top + 218, "CHECKPOINT RECORDED", True)
    checkbox(draw, side_x + 38, panel_top + 274, "SIGNATURE FILED", True)
    draw.line((side_x + 34, panel_top + 392, x2 - 110, panel_top + 392), fill=LIGHT, width=3)

    data_x = side_x + 38
    data_y = panel_top + 482
    data_w = 390
    draw.text((data_x, data_y), "ATTACHMENTS", font=font(FONT_TIMES_BOLD, 24), fill=MUTED)
    rows = [("MAP", "COORDINATE"), ("LOG", "FLIGHT ENTRY"), ("SIGN", "ARCHIVED")]
    for i, (label, value) in enumerate(rows):
        y = data_y + 45 + i * 50
        draw.text((data_x, y), label, font=font(FONT_TIMES_BOLD, 21), fill=MUTED)
        draw.text((data_x + 178, y - 4), value, font=font(FONT_TIMES_BOLD, 31), fill=INK)
        draw.line((data_x, y + 35, data_x + data_w, y + 35), fill=LIGHT, width=2)

    stamp_w = 440
    stamp_x = x2 - 98 - stamp_w
    stamp_y = panel_top + 666
    draw.text((side_x + 585, panel_top + 470), "SIGNATURE", font=font(FONT_TIMES_BOLD, 24), fill=MUTED)
    draw.line((side_x + 555, panel_top + 660, x2 - 118, panel_top + 660), fill=LINE, width=3)
    paste_chinese_signature(canvas, side_x + 520, panel_top + 512, width=330, opacity=0.83)

    table_box = (x1 + 76, y2 - 460, x2 - 76, y2 - 70)
    draw_table(draw, table_box)
    if show_stamp:
        paste_emboss_stamp(canvas, stamp_x, stamp_y, width=stamp_w, opacity=0.58)
        footer = "PILOT RECORD SEALED."
        footer_font = font(FONT_TIMES, 24)
        footer_w = draw.textbbox((0, 0), footer, font=footer_font)[2]
        draw.text((x2 - 76 - footer_w, y2 - 40), footer, font=footer_font, fill=MUTED)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    outer_trim = 7
    crop_box = (
        page_box[0] + outer_trim,
        page_box[1] + outer_trim,
        page_box[2] - outer_trim,
        page_box[3] - outer_trim,
    )
    final_image = canvas.crop(crop_box).convert("RGB")
    final_image.save(out_path, quality=95)
    if pdf_path:
        pdf_path = Path(pdf_path)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        final_image.save(pdf_path, "PDF", resolution=300.0)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Render Xia Yizhou pilot flight record.")
    parser.add_argument("--destination-name", default="", help="Name to place on the destination line.")
    parser.add_argument("--destination-coordinate", default=COORD_CODE, help="Destination coordinate string.")
    parser.add_argument("--output", default=str(OUT), help="PNG output path.")
    parser.add_argument("--pdf", default="", help="Optional PDF output path.")
    parser.add_argument("--show-callsign", action="store_true", help="Show the standalone CALEB header label.")
    parser.add_argument("--no-stamp", action="store_true", help="Render without the embossed fleet stamp.")
    args = parser.parse_args()
    output = generate_record(
        destination_name=args.destination_name,
        destination_coordinate=args.destination_coordinate,
        out_path=args.output,
        pdf_path=args.pdf or None,
        show_callsign=args.show_callsign,
        show_stamp=not args.no_stamp,
    )
    print(output)


if __name__ == "__main__":
    main()
