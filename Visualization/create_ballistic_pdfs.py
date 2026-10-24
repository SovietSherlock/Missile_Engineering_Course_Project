"""Создаёт PDF-таблицу сравнения и PDF-графики расчёта BalSimulation.

Скрипт использует только стандартный модуль csv и ReportLab. Исходный
временной ряд формируется программой проекта в файле
``flat_flight_trajectory.gra``.
"""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path
from typing import Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "Sources"
TRAJECTORY_FILE = ROOT / "flat_flight_trajectory.gra"
TABLE_FILE = SOURCES / "Результаты баллистического расчета.pdf"
GRAPHS_FILE = SOURCES / "Графики прямолинейного полёта.pdf"

PAGE = landscape(A4)
PAGE_WIDTH, PAGE_HEIGHT = PAGE
FONT = "Arial"
FONT_BOLD = "Arial-Bold"


def register_fonts() -> None:
    """Регистрирует шрифт с кириллицей на Windows и Linux."""
    candidates = [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ]
    for regular, bold in candidates:
        if os.path.exists(regular) and os.path.exists(bold):
            pdfmetrics.registerFont(TTFont(FONT, regular))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, bold))
            return
    raise FileNotFoundError("Не найден шрифт с поддержкой кириллицы")


def wrap_text(text: str, font: str, size: float, width: float) -> list[str]:
    """Разбивает строку на строки, которые помещаются в заданную ширину."""
    result: list[str] = []
    for paragraph in str(text).split("\n"):
        words = paragraph.split()
        if not words:
            result.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if pdfmetrics.stringWidth(candidate, font, size) <= width:
                line = candidate
            else:
                result.append(line)
                line = word
        result.append(line)
    return result or [""]


def draw_wrapped(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    font: str = FONT,
    size: float = 7.0,
    leading: float = 8.5,
    max_lines: int | None = None,
) -> float:
    """Рисует переносимый текст и возвращает координату после блока."""
    lines = wrap_text(text, font, size, width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            lines[-1] = lines[-1].rstrip(" .") + "…"
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def draw_centered_wrapped(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    height: float,
    font: str = FONT,
    size: float = 7.0,
    leading: float = 8.5,
) -> None:
    lines = wrap_text(text, font, size, width - 8)
    total_height = len(lines) * leading
    text_y = y + (height + total_height) / 2.0 - leading
    for line in lines:
        line_width = pdfmetrics.stringWidth(line, font, size)
        pdf.drawString(x + (width - line_width) / 2.0, text_y, line)
        text_y -= leading


def estimate_open_parameters() -> dict[str, dict[str, float]]:
    """Оценивает отсутствующие параметры по открытым данным и допущениям.

    Это не попытка восстановить закрытые паспортные данные. Расчёт нужен
    только для того, чтобы в сравнительной таблице не оставлять пустые ячейки
    без явной маркировки. Формулы для beta, mu и тяговых коэффициентов
    соответствуют используемой в проекте модели.
    """
    sound_speed = 340.0
    gravity = 9.80665
    loss_factor = 0.92
    start_specific_impulse = 2650.0
    march_specific_impulse = 2620.0
    start_duration = 5.0

    def calculate_beta(diameter: float, fuel_mass: float) -> float:
        if diameter <= 0.165:
            k_d = 3.502064 * (2.699929 * diameter) ** 2.2475
            beta_inf = 0.010649 / (0.439973 * diameter) ** 0.962255 + 1.0
        else:
            k_d = 21.423397 * (1.605279 * diameter) ** 2.817663 + 0.079
            beta_inf = 0.10013 / (0.436906 * diameter) ** 0.107262 + 1.0
        return k_d / fuel_mass + beta_inf

    def estimate(
        mass: float,
        mu_total: float,
        diameter: float,
        initial_mach: float,
        booster_end_mach: float,
        calculation_range: float,
        march_speed: float,
    ) -> dict[str, float]:
        delta_v = (booster_end_mach - initial_mach) * sound_speed
        effective_start_velocity = loss_factor * start_specific_impulse
        mu_start = 1.0 - math.exp(-delta_v / effective_start_velocity)
        mu_march = mu_total - mu_start
        eta_0 = delta_v / start_duration / gravity
        km = mu_march / mu_start
        start_distance = (
            (initial_mach + booster_end_mach) * sound_speed
            * start_duration / 2.0
        )
        march_time = (calculation_range - start_distance) / march_speed
        start_thrust = eta_0 * mass * gravity
        march_thrust = mu_march * mass / march_time * march_specific_impulse
        return {
            "mu_total": mu_total,
            "mu_start": mu_start,
            "mu_march": mu_march,
            "beta": calculate_beta(diameter, mu_total * mass),
            "eta_0": eta_0,
            "km": km,
            "kp": march_thrust / start_thrust,
        }

    return {
        "x35": estimate(
            mass=580.0,
            mu_total=0.35,
            diameter=0.42,
            initial_mach=0.35,
            booster_end_mach=0.8,
            calculation_range=260000.0,
            march_speed=0.8 * sound_speed,
        ),
        "oniks": estimate(
            mass=3000.0,
            mu_total=0.55,
            diameter=0.67,
            initial_mach=0.0,
            booster_end_mach=2.0,
            calculation_range=450000.0,
            march_speed=2.0 * sound_speed,
        ),
    }


def create_results_table() -> None:
    """Формирует заполненную сравнительную таблицу на одном листе A4."""
    pdf = canvas.Canvas(str(TABLE_FILE), pagesize=PAGE)
    pdf.setTitle("Результаты баллистического расчёта — заполненная таблица")

    estimates = estimate_open_parameters()
    x35 = estimates["x35"]
    oniks = estimates["oniks"]
    x35_time_min = 260000.0 / 280.0
    x35_time_max = 260000.0 / 270.0
    oniks_time_min = 300000.0 / (2.6 * 340.0)
    oniks_time_max = 600000.0 / (2.0 * 340.0)

    margin = 36.0
    table_x = margin
    table_width = PAGE_WIDTH - 2 * margin
    column_widths = [250.0, 170.0, 170.0, table_width - 590.0]
    headers = [
        "Рассматриваемый образец",
        "Х-35У",
        "Проектируемая ракета",
        "П-800 «Оникс»",
    ]
    rows = [
        ("Суммарная масса ракеты, кг", "550–610*", "1073,04", "≈ 3000*"),
        ("Суммарная относительная масса топлива", f"≈ {x35['mu_total']:.3f} (Оценочно)".replace(".", ","), "0,7000", f"≈ {oniks['mu_total']:.3f} (Оценочно)".replace(".", ",")),
        ("Относительная масса топлива разгонного режима", f"≈ {x35['mu_start']:.3f} (Оценочно)".replace(".", ","), "0,1407", f"≈ {oniks['mu_start']:.3f} (Оценочно)".replace(".", ",")),
        ("Относительная масса топлива маршевого режима", f"≈ {x35['mu_march']:.3f} (Оценочно)".replace(".", ","), "0,5593", f"≈ {oniks['mu_march']:.3f} (Оценочно)".replace(".", ",")),
        ("Коэффициент конструктивно-массового совершенства", f"≈ {x35['beta']:.3f} (Оценочно)".replace(".", ","), "1,1290", f"≈ {oniks['beta']:.3f} (Оценочно)".replace(".", ",")),
        ("Стартовая тяговооруженность", f"≈ {x35['eta_0']:.2f} (Оценочно)".replace(".", ","), "7,5403", f"≈ {oniks['eta_0']:.2f} (Оценочно)".replace(".", ",")),
        ("Коэффициент распределения топлива между режимами (Km)", f"≈ {x35['km']:.3f} (Оценочно)".replace(".", ","), "3,9747", f"≈ {oniks['km']:.3f} (Оценочно)".replace(".", ",")),
        ("Коэффициент отношения тяг (Kp)", f"≈ {x35['kp']:.3f} (Оценочно)".replace(".", ","), "0,0175", f"≈ {oniks['kp']:.3f} (Оценочно)".replace(".", ",")),
        ("Начальная скорость", "≈ 0,35 M (Оценочно)", "0,8 M", "≈ 2,0 M (Оценочно)"),
        ("Конечная скорость", "≈ 0,8 M (Оценочно)", "2,0 M", "≈ 2,5 M (Оценочно)"),
        ("Время полёта, с", f"≈ {x35_time_min:.0f}–{x35_time_max:.0f} (Оценочно)", "1137,48", f"≈ {oniks_time_min:.0f}–{oniks_time_max:.0f} (Оценочно)"),
        ("Дальность полёта, км", "260*", "700", "300–600*"),
    ]

    pdf.setFillColor(colors.HexColor("#17365D"))
    pdf.setFont(FONT_BOLD, 15)
    pdf.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 31,
        "Результаты баллистического расчёта",
    )
    pdf.setFillColor(colors.black)
    pdf.setFont(FONT, 7.5)
    pdf.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 44,
        "Сопоставление открытых паспортных данных и расчёта прямолинейного полёта",
    )

    top = PAGE_HEIGHT - 58.0
    header_height = 32.0
    pdf.setStrokeColor(colors.HexColor("#4F81BD"))
    pdf.setLineWidth(0.6)
    x = table_x
    pdf.setFillColor(colors.HexColor("#D9EAF7"))
    for width in column_widths:
        pdf.rect(x, top - header_height, width, header_height, fill=1, stroke=1)
        x += width
    pdf.setFillColor(colors.black)
    x = table_x
    for header, width in zip(headers, column_widths):
        draw_centered_wrapped(
            pdf, header, x, top - header_height, width, header_height,
            FONT_BOLD, 7.2, 8.5,
        )
        x += width

    y = top - header_height
    label_font_size = 7.0
    value_font_size = 7.0
    for row_index, row in enumerate(rows):
        label_lines = wrap_text(row[0], FONT, label_font_size, column_widths[0] - 8)
        value_lines = [
            wrap_text(value, FONT, value_font_size, width - 8)
            for value, width in zip(row[1:], column_widths[1:])
        ]
        row_lines = max(len(label_lines), *(len(lines) for lines in value_lines))
        row_height = max(23.0, row_lines * 8.5 + 8.0)
        fill = colors.white if row_index % 2 == 0 else colors.HexColor("#F4F8FC")
        x = table_x
        for width in column_widths:
            pdf.setFillColor(fill)
            pdf.rect(x, y - row_height, width, row_height, fill=1, stroke=1)
            x += width
        pdf.setFillColor(colors.black)
        x = table_x
        draw_wrapped(pdf, row[0], x + 4, y - 12, column_widths[0] - 8,
                     FONT, label_font_size, 8.5)
        x += column_widths[0]
        for value, width, lines in zip(row[1:], column_widths[1:], value_lines):
            text_y = y - (row_height + len(lines) * 8.5) / 2.0 + 8.5
            for line in lines:
                line_width = pdfmetrics.stringWidth(line, FONT, value_font_size)
                pdf.drawString(x + (width - line_width) / 2.0, text_y, line)
                text_y -= 8.5
            x += width
        y -= row_height

    note_y = y - 13
    pdf.setFont(FONT, 6.5)
    pdf.setFillColor(colors.HexColor("#333333"))
    notes = [
        "Примечание: «Оценочно» означает расчёт по открытым данным и явно указанным допущениям; это не паспортная характеристика ракеты.",
        "* Для Х-35У в карточке U.S. Army приведён вариант Kh-35UE; масса зависит от исполнения. Для Х-35 открытая карточка также указывает 270–280 м/с, диаметр 0,42 м и БЧ 145 кг.",
        "* Для П-800 «Оникс» приведены открытый диапазон дальности и масса стартового исполнения; карточка «Яхонта» указывает 2,0–2,6 M, БЧ 200–250 кг и сухую массу двигателя 200 кг.",
        "Оценки топлива заданы как инженерная массовая модель: Х-35У — m₀=580 кг, d=0,42 м, μΣ=0,35; «Оникс» — m₀=3000 кг, d=0,67 м, μΣ=0,55. Для разгона приняты M₀/M₁=0,35/0,8 и 0/2,0 соответственно.",
        "Для оценок использованы hi=0,92, Iуд старт=2650 м/с, Iуд марш=2620 м/с, tстарт=5 с; для Kp — средняя дальность «Оникса» 450 км. β вычислен функцией проекта.",
        "Параметры проектируемой ракеты рассчитаны BalSimulation при H=8000 м, μсумм=0,7, mпн=225 кг, L=700 км; начальная и конечная скорости указаны в числах Маха.",
    ]
    for note in notes:
        note_y = draw_wrapped(pdf, note, margin, note_y, table_width, FONT, 6.5, 7.5) - 1

    pdf.setFont(FONT_BOLD, 6.5)
    pdf.drawString(margin, note_y, "Источники:")
    note_y -= 8
    pdf.setFont(FONT, 6.0)
    source_lines = [
        "[1] U.S. Army, ODIN/WEG, Kh-35UE Russian Short-Range Cruise Missile: https://odin.t2com.army.mil/WEG/Asset/6fcff411c9e671a6f57ade2512aca882",
        "[2] U.S. Army, ODIN/WEG, P-800 Oniks: https://odin.t2com.army.mil/WEG/Asset/ee8265a1ec4f27de72058cf336eff5f6",
        "[3] ИС «Ракетная техника», ПКР Х-35 (карточка содержит ссылки на профильные издания и данные комплекса): https://missilery.info/missile/uran",
        "[4] ИС «Ракетная техника», ПКР «Яхонт» (Оникс), данные НПО Машиностроения и «Бастион» №1/2000: https://missilery.info/missile/jakhont",
    ]
    for source in source_lines:
        note_y = draw_wrapped(pdf, source, margin, note_y, table_width, FONT, 6.0, 7.0)

    pdf.showPage()
    pdf.save()


def load_trajectory() -> list[dict[str, float]]:
    if not TRAJECTORY_FILE.exists():
        raise FileNotFoundError(
            f"Не найден {TRAJECTORY_FILE.name}; сначала запустите расчёт программы."
        )
    with TRAJECTORY_FILE.open("r", encoding="utf-8") as file:
        reader = csv.DictReader(file, delimiter="\t")
        return [
            {key: float(value) for key, value in row.items() if key and value}
            for row in reader
        ]


def downsample(points: Sequence[dict[str, float]], limit: int = 1400) -> list[dict[str, float]]:
    if len(points) <= limit:
        return list(points)
    step = max(1, math.ceil(len(points) / limit))
    result = list(points[::step])
    if result[-1] is not points[-1]:
        result.append(points[-1])
    return result


def fmt(value: float) -> str:
    if abs(value) >= 10000 or (0 < abs(value) < 0.01):
        return f"{value:.2e}".replace("e+", "·10^")
    return f"{value:.2f}".replace(".", ",")


def draw_chart(
    pdf: canvas.Canvas,
    points: Sequence[dict[str, float]],
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    y_label: str,
    series: Iterable[tuple[str, str, colors.Color]],
) -> None:
    left = x + 45
    bottom = y + 30
    chart_width = width - 58
    chart_height = height - 55
    series_list = list(series)
    all_values = [
        point[key]
        for _, key, _ in series_list
        for point in points
        if key in point and math.isfinite(point[key])
    ]
    if not all_values:
        return
    y_min = min(all_values)
    y_max = max(all_values)
    if math.isclose(y_min, y_max):
        margin = max(1.0, abs(y_min) * 0.05)
    else:
        margin = (y_max - y_min) * 0.08
    y_min -= margin
    y_max += margin
    t_min = points[0]["t"]
    t_max = points[-1]["t"]
    if math.isclose(t_min, t_max):
        t_max = t_min + 1.0

    pdf.setStrokeColor(colors.HexColor("#B7C9D6"))
    pdf.setLineWidth(0.35)
    for i in range(6):
        gy = bottom + chart_height * i / 5
        pdf.line(left, gy, left + chart_width, gy)
    for i in range(6):
        gx = left + chart_width * i / 5
        pdf.line(gx, bottom, gx, bottom + chart_height)
    pdf.setStrokeColor(colors.HexColor("#425563"))
    pdf.setLineWidth(0.8)
    pdf.line(left, bottom, left, bottom + chart_height)
    pdf.line(left, bottom, left + chart_width, bottom)

    pdf.setFillColor(colors.black)
    pdf.setFont(FONT_BOLD, 8)
    pdf.drawString(x, y + height - 11, title)
    pdf.setFont(FONT, 6.5)
    for i in range(6):
        value = y_min + (y_max - y_min) * i / 5
        label_y = bottom + chart_height * i / 5 - 2
        pdf.drawRightString(left - 4, label_y, fmt(value))
        time_value = t_min + (t_max - t_min) * i / 5
        pdf.drawCentredString(left + chart_width * i / 5, bottom - 12, fmt(time_value))
    pdf.drawCentredString(left + chart_width / 2, y + 5, "t, с")
    pdf.saveState()
    pdf.translate(x + 9, bottom + chart_height / 2)
    pdf.rotate(90)
    pdf.drawCentredString(0, 0, y_label)
    pdf.restoreState()

    for name, key, color in series_list:
        path = pdf.beginPath()
        started = False
        for point in points:
            value = point.get(key)
            if value is None or not math.isfinite(value):
                started = False
                continue
            px = left + (point["t"] - t_min) / (t_max - t_min) * chart_width
            py = bottom + (value - y_min) / (y_max - y_min) * chart_height
            if not started:
                path.moveTo(px, py)
                started = True
            else:
                path.lineTo(px, py)
        pdf.setStrokeColor(color)
        pdf.setLineWidth(1.1)
        pdf.drawPath(path, stroke=1, fill=0)

    legend_x = left + 5
    legend_y = bottom + chart_height - 12
    pdf.setFont(FONT, 6.2)
    for name, _, color in series_list:
        pdf.setStrokeColor(color)
        pdf.line(legend_x, legend_y + 2, legend_x + 15, legend_y + 2)
        pdf.setFillColor(colors.black)
        pdf.drawString(legend_x + 18, legend_y, name)
        legend_x += 18 + pdfmetrics.stringWidth(name, FONT, 6.2) + 12


def draw_graph_page(
    pdf: canvas.Canvas,
    points: Sequence[dict[str, float]],
    page_title: str,
    charts: Sequence[tuple[str, str, list[tuple[str, str, colors.Color]]]],
) -> None:
    pdf.setFillColor(colors.HexColor("#17365D"))
    pdf.setFont(FONT_BOLD, 14)
    pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 25, page_title)
    pdf.setFillColor(colors.black)
    pdf.setFont(FONT, 7)
    pdf.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 39,
        "BalSimulation: H=8000 м, L=700 км, θ=0°, временной шаг=0,01 с",
    )

    margin_x = 28.0
    top = PAGE_HEIGHT - 52.0
    gap_x = 18.0
    gap_y = 20.0
    chart_width = (PAGE_WIDTH - 2 * margin_x - gap_x) / 2
    chart_height = (PAGE_HEIGHT - 74.0 - gap_y - 28.0) / 2
    for index, (title, y_label, series) in enumerate(charts):
        row, column = divmod(index, 2)
        chart_x = margin_x + column * (chart_width + gap_x)
        chart_y = top - (row + 1) * chart_height - row * gap_y
        draw_chart(pdf, points, chart_x, chart_y, chart_width, chart_height,
                   title, y_label, series)
    pdf.setFont(FONT, 6.5)
    pdf.setFillColor(colors.HexColor("#555555"))
    pdf.drawRightString(PAGE_WIDTH - margin_x, 14, f"Страница {pdf.getPageNumber()}")


def create_graphs() -> None:
    points = downsample(load_trajectory())
    pdf = canvas.Canvas(str(GRAPHS_FILE), pagesize=PAGE)
    pdf.setTitle("Графики прямолинейного полёта")

    blue = colors.HexColor("#1F4E79")
    orange = colors.HexColor("#C55A11")
    green = colors.HexColor("#548235")
    red = colors.HexColor("#A61C00")
    purple = colors.HexColor("#7030A0")

    draw_graph_page(
        pdf,
        points,
        "Прямолинейная траектория и скорость",
        [
            ("Продольная координата", "x, м", [("x ракеты", "x_g_r", blue)]),
            ("Высота полёта", "y, м", [("y ракеты", "y_g_r", green)]),
            ("Скорость", "v, м/с", [("v", "v_r", orange)]),
            ("Число Маха", "M", [("M", "mach", purple)]),
        ],
    )
    pdf.showPage()

    draw_graph_page(
        pdf,
        points,
        "Массовые характеристики и расход топлива",
        [
            ("Относительная масса топлива", "μ", [
                ("μ сумм", "mu_summ", blue),
                ("μ старт", "mu_0", orange),
                ("μ марш", "mu_1", green),
            ]),
            ("Масса ракеты", "m, кг", [("m", "mass_r", red)]),
            ("Остаток топлива", "m топлива, кг", [("топливо", "fuel_remaining", purple)]),
            ("Расход топлива", "G, кг/с", [("G", "fuel_rate", orange)]),
        ],
    )
    pdf.showPage()

    draw_graph_page(
        pdf,
        points,
        "Тяга и перегрузка",
        [
            ("Суммарная тяга", "P, Н", [("P", "P_r", blue)]),
            ("Осевая перегрузка", "nₓₐ", [("nₓₐ", "n_xa_r", red)]),
            ("Нормальная перегрузка", "nᵧₐ", [("nᵧₐ", "n_ya_r", green)]),
            ("Режим полёта", "режим", [("режим", "flight_mode", purple)]),
        ],
    )
    pdf.showPage()
    pdf.save()


def main() -> None:
    register_fonts()
    SOURCES.mkdir(parents=True, exist_ok=True)
    create_results_table()
    create_graphs()
    print(f"Таблица сохранена: {TABLE_FILE}")
    print(f"Графики сохранены: {GRAPHS_FILE}")


if __name__ == "__main__":
    main()
