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


def create_results_table() -> None:
    """Формирует заполненную сравнительную таблицу на одном листе A4."""
    pdf = canvas.Canvas(str(TABLE_FILE), pagesize=PAGE)
    pdf.setTitle("Результаты баллистического расчёта — заполненная таблица")

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
        ("Суммарная относительная масса топлива", "н/д", "0,7000", "н/д"),
        ("Относительная масса топлива разгонного режима", "н/д", "0,1407", "н/д"),
        ("Относительная масса топлива маршевого режима", "н/д", "0,5593", "н/д"),
        ("Коэффициент конструктивно-массового совершенства", "н/д", "1,1290", "н/д"),
        ("Стартовая тяговооруженность", "н/д", "7,5403", "н/д"),
        ("Коэффициент распределения топлива между режимами (Km)", "н/д", "3,9747", "н/д"),
        ("Коэффициент отношения тяг (Kp)", "н/д", "0,0175", "н/д"),
        ("Начальная скорость", "н/д (Mmax≈0,8)*", "0,8 M", "н/д (Mmax≈2,5)*"),
        ("Конечная скорость", "н/д (Mmax≈0,8)*", "2,0 M", "н/д (Mmax≈2,5)*"),
        ("Время полёта, с", "н/д", "1137,48", "н/д"),
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
        "Примечание: «н/д» означает, что параметр не опубликован в открытой официальной карточке; это не нулевое значение.",
        "* Для Х-35У в открытой карточке U.S. Army приведён вариант Kh-35UE; масса зависит от исполнения и пускового ускорителя, скорость — максимальная, а не начальная/конечная.",
        "* Для П-800 «Оникс» приведены открытый диапазон дальности и масса стартового исполнения; эти данные не являются результатом расчёта проекта.",
        "Параметры проектируемой ракеты рассчитаны BalSimulation при H=8000 м, μсумм=0,7, mпн=225 кг, L=700 км; начальная и конечная скорости указаны в числах Маха.",
    ]
    for note in notes:
        note_y = draw_wrapped(pdf, note, margin, note_y, table_width, FONT, 6.5, 7.5) - 1

    pdf.setFont(FONT_BOLD, 6.5)
    pdf.drawString(margin, note_y, "Официальные источники:")
    note_y -= 8
    pdf.setFont(FONT, 6.0)
    source_lines = [
        "[1] U.S. Army, ODIN/WEG, Kh-35UE Russian Short-Range Cruise Missile: https://odin.t2com.army.mil/WEG/Asset/6fcff411c9e671a6f57ade2512aca882",
        "[2] U.S. Army, ODIN/WEG, P-800 Oniks: https://odin.t2com.army.mil/WEG/Asset/ee8265a1ec4f27de72058cf336eff5f6",
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
