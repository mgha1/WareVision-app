from PIL import Image, ImageDraw, ImageFont


WIDTH = 1800
HEIGHT = 1100
BG = "#f5f7f4"
INK = "#10231a"
MUTED = "#486155"
LINE = "#7a8f84"
ACCENT = "#147d64"
ACCENT_2 = "#275d9a"
ACCENT_3 = "#b35c1e"
ACCENT_4 = "#764ba2"
PANEL = "#ffffff"
PANEL_ALT = "#e8f2ed"


def load_font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


TITLE = load_font(44, bold=True)
SUBTITLE = load_font(22)
H2 = load_font(26, bold=True)
BODY = load_font(20)
SMALL = load_font(17)
LABEL = load_font(18, bold=True)


def draw_round_rect(draw, box, fill, outline, radius=22, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_text_block(draw, x, y, width, lines, font, fill, spacing=8):
    cursor_y = y
    for line in lines:
        words = line.split()
        current = ""
        wrapped = []
        for word in words:
            trial = word if not current else current + " " + word
            trial_width = draw.textbbox((0, 0), trial, font=font)[2]
            if trial_width <= width:
                current = trial
            else:
                if current:
                    wrapped.append(current)
                current = word
        if current:
            wrapped.append(current)
        if not wrapped:
            wrapped = [""]
        for wrapped_line in wrapped:
            draw.text((x, cursor_y), wrapped_line, font=font, fill=fill)
            cursor_y += font.size + spacing
    return cursor_y


def draw_box(draw, xy, title, lines, outline, fill=PANEL):
    x1, y1, x2, y2 = xy
    draw_round_rect(draw, xy, fill=fill, outline=outline, radius=26, width=3)
    draw.text((x1 + 24, y1 + 18), title, font=H2, fill=INK)
    draw_text_block(draw, x1 + 24, y1 + 60, x2 - x1 - 48, lines, BODY, MUTED, spacing=6)


def draw_arrow(draw, start, end, color, width=5, label=None, label_offset=(0, 0)):
    draw.line([start, end], fill=color, width=width)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux = dx / length
    uy = dy / length
    arrow_len = 18
    wing = 10
    p1 = (
        end[0] - ux * arrow_len - uy * wing,
        end[1] - uy * arrow_len + ux * wing,
    )
    p2 = (
        end[0] - ux * arrow_len + uy * wing,
        end[1] - uy * arrow_len - ux * wing,
    )
    draw.polygon([end, p1, p2], fill=color)
    if label:
        mid = ((start[0] + end[0]) / 2 + label_offset[0], (start[1] + end[1]) / 2 + label_offset[1])
        text_box = draw.textbbox((0, 0), label, font=SMALL)
        pad_x = 10
        pad_y = 6
        box = (
            mid[0] - (text_box[2] - text_box[0]) / 2 - pad_x,
            mid[1] - (text_box[3] - text_box[1]) / 2 - pad_y,
            mid[0] + (text_box[2] - text_box[0]) / 2 + pad_x,
            mid[1] + (text_box[3] - text_box[1]) / 2 + pad_y,
        )
        draw_round_rect(draw, box, fill="#ffffff", outline=color, radius=14, width=2)
        draw.text((box[0] + pad_x, box[1] + pad_y - 1), label, font=SMALL, fill=INK)


def main():
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((30, 30, WIDTH - 30, HEIGHT - 30), radius=36, outline="#d2ddd7", width=3, fill=BG)
    draw.text((70, 60), "WareVision Architecture", font=TITLE, fill=INK)
    draw.text(
        (72, 118),
        "FastAPI warehouse control room for analytics, slotting, inbound assignment, and demand forecasting",
        font=SUBTITLE,
        fill=MUTED,
    )

    draw_box(
        draw,
        (90, 220, 470, 440),
        "1. Browser SPA",
        [
            "Login and session handling",
            "Analytics dashboard",
            "Live floor map and heatmap",
            "Recommendation queue",
            "Inbound receiving workflow",
            "Forecasting and reorder actions",
        ],
        outline=ACCENT,
        fill=PANEL_ALT,
    )

    draw_box(
        draw,
        (560, 170, 1220, 500),
        "2. FastAPI Application",
        [
            "Serves index.html and static JS/CSS",
            "Session auth with protected APIs",
            "Short-lived response caching for live views",
            "Operational endpoints: floor, assets, heatmap, inventory, recommendations",
            "Inbound endpoints: SKU lookup, slot recommendation, assignment, today's log",
            "Forecast endpoints: summary, SKU detail, reorder queue, reorder signal",
        ],
        outline=ACCENT_2,
    )

    draw_box(
        draw,
        (560, 560, 920, 850),
        "3. Slotting Engine",
        [
            "APScheduler job runs on interval",
            "Finds high-frequency SKUs with long dispatch distance",
            "Scores waste = pick frequency x travel distance",
            "Assigns best candidates to empty fast-pick slots",
            "Writes pending moves to slotting_recommendations",
        ],
        outline=ACCENT_3,
    )

    draw_box(
        draw,
        (980, 560, 1340, 850),
        "4. Forecast Engine",
        [
            "Uses 90-day pick and sales history",
            "Seeds forecast_history when missing",
            "Smooths demand and fits linear regression",
            "Classifies SKUs: stockout, reorder, healthy, slow",
            "Supports reorder initiation workflow",
        ],
        outline=ACCENT_4,
    )

    draw_box(
        draw,
        (1380, 170, 1700, 850),
        "5. Oracle Database",
        [
            "Reads: warehouse_zones, slots, inventory, asset_positions",
            "Reads: pick_history, daily_sales, product, category",
            "Writes: slotting_recommendations",
            "Writes: movement_log and slot_assignments",
            "Writes: forecast_history support data",
            "",
            "Acts as the source of truth for warehouse state",
        ],
        outline=LINE,
    )

    draw_box(
        draw,
        (180, 690, 470, 930),
        "Business Outcomes",
        [
            "Shorter travel paths",
            "Faster putaway decisions",
            "Better fast-pick utilization",
            "Lower stockout risk",
            "Single control room for supervisors",
        ],
        outline=ACCENT,
        fill="#eef7f3",
    )

    draw_arrow(draw, (470, 330), (560, 330), ACCENT, label="JSON APIs / session cookie", label_offset=(0, -28))
    draw_arrow(draw, (1220, 260), (1380, 260), ACCENT_2, label="read warehouse state", label_offset=(0, -24))
    draw_arrow(draw, (1380, 340), (1220, 340), ACCENT_2, label="return live data", label_offset=(0, 22))
    draw_arrow(draw, (920, 650), (1380, 650), ACCENT_3, label="write recommendations", label_offset=(0, -24))
    draw_arrow(draw, (980, 730), (1380, 730), ACCENT_4, label="read history / write forecast support", label_offset=(0, -24))
    draw_arrow(draw, (760, 500), (760, 560), ACCENT_3, label="scheduled analysis", label_offset=(-80, 0))
    draw_arrow(draw, (1100, 500), (1100, 560), ACCENT_4, label="forecast calls", label_offset=(80, 0))
    draw_arrow(draw, (665, 850), (470, 810), ACCENT, label="recommended actions", label_offset=(0, -24))
    draw_arrow(draw, (1080, 850), (470, 850), ACCENT, label="replenishment insight", label_offset=(0, -24))

    legend_y = 980
    draw.text((80, legend_y), "Legend", font=LABEL, fill=INK)
    legend_items = [
        (ACCENT, "UI and operator flow"),
        (ACCENT_2, "Core API and database exchange"),
        (ACCENT_3, "Slotting optimization flow"),
        (ACCENT_4, "Forecasting and replenishment flow"),
    ]
    legend_x = 180
    for color, text in legend_items:
        draw.rounded_rectangle((legend_x, legend_y + 4, legend_x + 28, legend_y + 24), radius=8, fill=color)
        draw.text((legend_x + 40, legend_y), text, font=SMALL, fill=MUTED)
        legend_x += 360

    image.save("/home/opc/myapp_v2/warevision_architecture.jpg", quality=92)


if __name__ == "__main__":
    main()
