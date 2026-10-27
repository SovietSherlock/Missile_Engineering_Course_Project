"""Создаёт PDF-таблицу и графики обновлённого BalSimulation.

Временной ряд формируется программой проекта в файле
``flat_flight_trajectory.gra``. Графики показывают подготовительный,
стартовый и маршевый режимы, а также увеличенное окно первых секунд полёта.
"""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "Sources"
TRAJECTORY_FILE = ROOT / "flat_flight_trajectory.gra"
SUMMARY_FILE = ROOT / "flat_flight_summary.tsv"
TABLE_FILE = SOURCES / "Результаты баллистического расчета.pdf"
GRAPHS_FILE = SOURCES / "Графики прямолинейного полёта.pdf"

PAGE = landscape(A4)
PAGE_WIDTH, PAGE_HEIGHT = PAGE
FONT = "Arial"
FONT_BOLD = "Arial-Bold"

MODE_NAMES = {
    0: "Подготовительный",
    1: "Стартовый",
    2: "Маршевый",
}
MODE_FILL = {
    0: colors.HexColor("#EEEEEE"),
    1: colors.HexColor("#FCE4D6"),
    2: colors.HexColor("#DDEBF7"),
}
MODE_LINE = {
    0: colors.HexColor("#7F7F7F"),
    1: colors.HexColor("#C55A11"),
    2: colors.HexColor("#1F4E79"),
}


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
) -> float:
    """Рисует переносимый текст и возвращает координату после блока."""
    for line in wrap_text(text, font, size, width):
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


def load_summary() -> dict[str, float]:
    if not SUMMARY_FILE.exists():
        raise FileNotFoundError(
            f"Не найден {SUMMARY_FILE.name}; сначала запустите расчёт программы."
        )
    with SUMMARY_FILE.open("r", encoding="utf-8") as file:
        reader = csv.DictReader(file, delimiter="\t")
        result: dict[str, float] = {}
        for row in reader:
            key = row.get("Показатель")
            value = row.get("Значение")
            if key and value:
                result[key] = float(value)
        return result


def load_trajectory() -> list[dict[str, float]]:
    if not TRAJECTORY_FILE.exists():
        raise FileNotFoundError(
            f"Не найден {TRAJECTORY_FILE.name}; сначала запустите расчёт программы."
        )
    with TRAJECTORY_FILE.open("r", encoding="utf-8") as file:
        reader = csv.DictReader(file, delimiter="\t")
        points = [
            {key: float(value) for key, value in row.items() if key and value}
            for row in reader
        ]
        # Поддержка старых временных рядов: до появления отдельного поля
        # накопленное выгорание восстанавливается из максимального остатка.
        if points and "fuel_burned_relative" not in points[0]:
            initial_fuel = max(point.get("mu_summ", 0.0) for point in points)
            for point in points:
                point["fuel_burned_relative"] = max(
                    0.0, initial_fuel - point.get("mu_summ", initial_fuel)
                )
        return points


def downsample(
    points: Sequence[dict[str, float]], limit: int = 1600
) -> list[dict[str, float]]:
    if len(points) <= limit:
        return list(points)
    step = max(1, math.ceil(len(points) / limit))
    # Помимо равномерной выборки сохраняем все точки смены режима. Иначе
    # границы 3 и 8 с могут исчезнуть из PDF при большом маршевом участке.
    selected = set(range(0, len(points), step))
    selected.update({0, len(points) - 1})
    for index in range(1, len(points)):
        if points[index]["flight_mode"] != points[index - 1]["flight_mode"]:
            selected.update({index - 1, index})
    return [points[index] for index in sorted(selected)]


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def approx(value: float, digits: int = 3) -> str:
    return f"≈ {fmt(value, digits)} (Оценочно)"


def create_results_table() -> None:
    """Формирует двухстраничную таблицу с новыми расчётными результатами."""
    summary = load_summary()
    pdf = canvas.Canvas(str(TABLE_FILE), pagesize=PAGE)
    pdf.setTitle("Результаты баллистического расчёта — обновлённая таблица")

    def value(key: str, digits: int = 2) -> str:
        return fmt(summary[key], digits)

    # Открытые данные и ранее выполненные инженерные оценки для сравнения.
    rows = [
        ("Суммарная масса ракеты, кг", "550–610*", value("m0"), "≈ 2500*"),
        ("Обобщённая полезная нагрузка, кг", "н/д", "375", "н/д"),
        ("Суммарная относительная масса топлива", "≈ 0,350 (Оценочно)", value("mu_summ", 4), "≈ 0,550 (Оценочно)"),
        ("Относительная масса топлива стартового режима", "≈ 0,061 (Оценочно)", value("mu_0 (стартовое топливо)", 4), "≈ 0,243 (Оценочно)"),
        ("Относительная масса топлива маршевого режима", "≈ 0,289 (Оценочно)", value("mu_1 (маршевое топливо, относительно m0)", 4), "≈ 0,307 (Оценочно)"),
        ("Коэффициент совершенства стартовой установки (β0)", "≈ 1,155 (Оценочно)", value("beta_start"), "≈ 1,130 (Оценочно)"),
        ("Коэффициент совершенства маршевой установки (β1)", "≈ 1,155 (Оценочно)", value("beta_march"), "≈ 1,130 (Оценочно)"),
        ("Стартовая тяговооружённость", "≈ 3,12 (Оценочно)", value("eta_0"), "≈ 13,87 (Оценочно)"),
        ("Коэффициент распределения топлива (Km)", "≈ 4,754 (Оценочно)", value("Km"), "≈ 1,260 (Оценочно)"),
        ("Коэффициент отношения тяг (Kp)", "≈ 0,026 (Оценочно)", value("Kp (средняя маршевая тяга)"), "≈ 0,009 (Оценочно)"),
        ("Начальная скорость", "≈ 0,35 M (Оценочно)", "0,8 M", "≈ 0 M (Оценочно)"),
        ("Конечная скорость", "≈ 0,8 M (Оценочно)", "2,0 M", "≈ 2,5 M (Оценочно)"),
        ("Подготовительный режим, с", "н/д", value("Время подготовки"), "н/д"),
        ("Время полёта, с", "≈ 930–960 (Оценочно)", value("Время полёта"), "≈ 340–880 (Оценочно)"),
        ("Дальность полёта, км", "260*", "700", "300–600*"),
        ("Нагрузка на мидель стартового режима, Н/м²", "н/д", value("q_m0 проектируемой ракеты", 1), "≈ 69538*"),
        ("Нагрузка на мидель после старта, Н/м²", "н/д", value("q_m1 после старта", 1), "н/д"),
        ("Площадь миделя, м²", "н/д", value("Площадь миделя"), "≈ 0,353*"),
        ("Калибр, м", "0,42*", value("Калибр"), "0,67*"),
        ("Удлинение", "н/д", value("Удлинение"), "н/д"),
        ("Длина ракеты, м", "н/д", value("Длина ракеты"), "6,10*"),
    ]

    margin = 28.0
    table_x = margin
    table_width = PAGE_WIDTH - 2 * margin
    column_widths = [242.0, 165.0, 165.0, table_width - 572.0]
    headers = [
        "Рассматриваемый образец",
        "Х-35У",
        "Проектируемая ракета",
        "П-800 «Оникс»",
    ]

    pdf.setFillColor(colors.HexColor("#17365D"))
    pdf.setFont(FONT_BOLD, 15)
    pdf.drawCentredString(
        PAGE_WIDTH / 2, PAGE_HEIGHT - 27,
        "Результаты баллистического расчёта",
    )
    pdf.setFillColor(colors.black)
    pdf.setFont(FONT, 7.5)
    pdf.drawCentredString(
        PAGE_WIDTH / 2, PAGE_HEIGHT - 41,
        "Трёхрежимный авиационный запуск и расчёт калибра по нагрузке на мидель П-800",
    )

    top = PAGE_HEIGHT - 53.0
    header_height = 31.0
    pdf.setStrokeColor(colors.HexColor("#4F81BD"))
    pdf.setLineWidth(0.55)
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
            FONT_BOLD, 7.0, 8.0,
        )
        x += width

    y = top - header_height
    for row_index, row in enumerate(rows):
        label_lines = wrap_text(row[0], FONT, 6.5, column_widths[0] - 8)
        value_lines = [
            wrap_text(text, FONT, 6.5, width - 8)
            for text, width in zip(row[1:], column_widths[1:])
        ]
        row_lines = max(len(label_lines), *(len(lines) for lines in value_lines))
        row_height = max(19.0, row_lines * 7.5 + 6.0)
        fill = colors.white if row_index % 2 == 0 else colors.HexColor("#F4F8FC")
        x = table_x
        for width in column_widths:
            pdf.setFillColor(fill)
            pdf.rect(x, y - row_height, width, row_height, fill=1, stroke=1)
            x += width
        pdf.setFillColor(colors.black)
        x = table_x
        draw_wrapped(pdf, row[0], x + 4, y - 10, column_widths[0] - 8,
                     FONT, 6.5, 7.5)
        x += column_widths[0]
        for text, width, lines in zip(row[1:], column_widths[1:], value_lines):
            text_y = y - (row_height + len(lines) * 7.5) / 2.0 + 7.5
            for line in lines:
                line_width = pdfmetrics.stringWidth(line, FONT, 6.5)
                pdf.drawString(x + (width - line_width) / 2.0, text_y, line)
                text_y -= 7.5
            x += width
        y -= row_height

    pdf.setFont(FONT, 6.0)
    pdf.setFillColor(colors.HexColor("#555555"))
    pdf.drawRightString(PAGE_WIDTH - margin, 14, "Страница 1")
    pdf.showPage()

    # Вторая страница содержит методику, чтобы основная таблица оставалась
    # читаемой при добавлении геометрических результатов.
    pdf.setFillColor(colors.HexColor("#17365D"))
    pdf.setFont(FONT_BOLD, 14)
    pdf.drawCentredString(
        PAGE_WIDTH / 2, PAGE_HEIGHT - 29,
        "Методика и расчётные параметры проектируемой ракеты",
    )
    pdf.setFillColor(colors.HexColor("#333333"))
    note_y = PAGE_HEIGHT - 53
    pdf.setFont(FONT, 7.0)
    notes = [
        "Подготовительный режим длится 3 с: ракета сходит с пилона самолёта-носителя, двигатель не работает, масса и скорость постоянны.",
        "Стартовый режим длится 5 с и начинается при M=0,8. Маршевый режим выполняется при M=2,0 на высоте 8000 м до дальности 700 км.",
        "Масса обобщённой полезной нагрузки mпр.п.н.=375 кг. В массовом уравнении используются отдельные β0=1,30 и β1=1,20; в основном отчёте β означает β0.",
        "Масса топлива на стартовом и маршевом участках изменяется экспоненциально. Маршевая тяга определяется текущим расходом топлива, а Kp — по средней маршевой тяге.",
        "Нагрузка на мидель проектируемой ракеты приравнена к нагрузке авиационного П-800: mref=2500 кг, dref=0,67 м, q_m0=69537,84 Н/м².",
        "Калибр определяется после расчёта стартовой массы: S_m=m0·g/q_m0, d=sqrt(4·S_m/π). График оптимизации q_m1(q_m0) из расчёта исключён полностью.",
        "Значения в колонках Х-35У и П-800, отмеченные «Оценочно», получены по открытым данным и инженерным допущениям и не являются паспортными характеристиками.",
    ]
    for note in notes:
        note_y = draw_wrapped(pdf, note, margin, note_y, table_width, FONT, 7.0, 9.0) - 2

    pdf.setFont(FONT_BOLD, 7.0)
    pdf.drawString(margin, note_y, "Источники:")
    note_y -= 10
    pdf.setFont(FONT, 6.5)
    source_lines = [
        "[1] U.S. Army, ODIN/WEG, Kh-35UE Russian Short-Range Cruise Missile: https://odin.t2com.army.mil/WEG/Asset/6fcff411c9e671a6f57ade2512aca882",
        "[2] U.S. Army, ODIN/WEG, P-800 Oniks: https://odin.t2com.army.mil/WEG/Asset/ee8265a1ec4f27de72058cf336eff5f6",
        "[3] ИС «Ракетная техника», ПКР Х-35: https://missilery.info/missile/uran",
        "[4] ИС «Ракетная техника», ПКР «Яхонт» (Оникс), данные НПО Машиностроения и «Бастион» №1/2000: https://missilery.info/missile/jakhont",
        "[5] Астахова Н.Е., Толкачёва Е.А. Баллистическое проектирование летательных аппаратов, раздел 2.2 «Массовый анализ», стр. 18–19.",
    ]
    for source in source_lines:
        note_y = draw_wrapped(pdf, source, margin, note_y, table_width, FONT, 6.5, 8.0)

    pdf.setFont(FONT, 6.0)
    pdf.setFillColor(colors.HexColor("#555555"))
    pdf.drawRightString(PAGE_WIDTH - margin, 14, "Страница 2")
    pdf.showPage()
    pdf.save()


def mode_bounds(points: Sequence[dict[str, float]]) -> list[tuple[int, float, float]]:
    bounds: list[tuple[int, float, float]] = []
    for mode in MODE_NAMES:
        mode_points = [p["t"] for p in points if int(p.get("flight_mode", 0)) == mode]
        if mode_points:
            bounds.append((mode, min(mode_points), max(mode_points)))
    return bounds


def draw_mode_background(
    pdf: canvas.Canvas,
    points: Sequence[dict[str, float]],
    left: float,
    bottom: float,
    width: float,
    height: float,
    t_min: float,
    t_max: float,
    annotate: bool = True,
) -> None:
    """Рисует зоны режимов и границы между ними на одном графике."""
    for mode, mode_start, mode_end in mode_bounds(points):
        start = max(t_min, mode_start)
        end = min(t_max, mode_end)
        if end < start:
            continue
        x1 = left + (start - t_min) / (t_max - t_min) * width
        x2 = left + (end - t_min) / (t_max - t_min) * width
        pdf.setFillColor(MODE_FILL[mode])
        pdf.rect(x1, bottom, max(0.1, x2 - x1), height, fill=1, stroke=0)
        if annotate and x2 - x1 > 24:
            pdf.setFillColor(MODE_LINE[mode])
            pdf.setFont(FONT, 5.5)
            pdf.drawCentredString((x1 + x2) / 2.0, bottom + height - 9,
                                  MODE_NAMES[mode])

    pdf.setStrokeColor(colors.HexColor("#7F7F7F"))
    pdf.setLineWidth(0.65)
    pdf.setDash(2, 2)
    for _, _, mode_end in mode_bounds(points)[:-1]:
        if t_min <= mode_end <= t_max:
            x = left + (mode_end - t_min) / (t_max - t_min) * width
            pdf.line(x, bottom, x, bottom + height)
    pdf.setDash()


def draw_series(
    pdf: canvas.Canvas,
    points: Sequence[dict[str, float]],
    key: str,
    color: colors.Color,
    left: float,
    bottom: float,
    width: float,
    height: float,
    t_min: float,
    t_max: float,
    y_min: float,
    y_max: float,
) -> None:
    """Рисует ряд отдельными сегментами, не соединяя разные режимы."""
    for index in range(len(points) - 1):
        p1 = points[index]
        p2 = points[index + 1]
        v1 = p1.get(key)
        v2 = p2.get(key)
        if v1 is None or v2 is None or not math.isfinite(v1) or not math.isfinite(v2):
            continue
        x1 = left + (p1["t"] - t_min) / (t_max - t_min) * width
        x2 = left + (p2["t"] - t_min) / (t_max - t_min) * width
        y1 = bottom + (v1 - y_min) / (y_max - y_min) * height
        y2 = bottom + (v2 - y_min) / (y_max - y_min) * height
        # Цвет ряда сохраняется для различения серий, а фон и границы
        # режима однозначно показывают принадлежность участка полёта.
        pdf.setStrokeColor(color)
        pdf.setLineWidth(1.0)
        pdf.line(x1, y1, x2, y2)


def draw_plot_area(
    pdf: canvas.Canvas,
    points: Sequence[dict[str, float]],
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    y_label: str,
    series: Sequence[tuple[str, str, colors.Color]],
    t_min: float,
    t_max: float,
    y_min: float | None = None,
    y_max: float | None = None,
    inset: bool = False,
) -> None:
    left = x + (30 if inset else 45)
    bottom = y + (18 if inset else 30)
    chart_width = width - (38 if inset else 58)
    chart_height = height - (30 if inset else 55)
    if t_max <= t_min:
        t_max = t_min + 1.0

    all_values = [
        point[key]
        for _, key, _ in series
        for point in points
        if t_min <= point["t"] <= t_max and key in point
        and math.isfinite(point[key])
    ]
    if not all_values:
        return
    if y_min is None:
        y_min = min(all_values)
    if y_max is None:
        y_max = max(all_values)
    if math.isclose(y_min, y_max):
        margin = max(1.0, abs(y_min) * 0.05)
        y_min -= margin
        y_max += margin
    else:
        margin = (y_max - y_min) * 0.08
        y_min -= margin
        y_max += margin

    plot_points = [p for p in points if t_min <= p["t"] <= t_max]
    draw_mode_background(pdf, plot_points, left, bottom, chart_width,
                         chart_height, t_min, t_max, annotate=not inset)

    pdf.setStrokeColor(colors.HexColor("#B7C9D6"))
    pdf.setLineWidth(0.3)
    for i in range(6):
        gy = bottom + chart_height * i / 5
        pdf.line(left, gy, left + chart_width, gy)
        gx = left + chart_width * i / 5
        pdf.line(gx, bottom, gx, bottom + chart_height)
    # Вертикальная ось проходит через t=0. Если диапазон ординат включает
    # отрицательные значения, горизонтальная ось переносится на y=0, чтобы
    # начало координат оставалось видимым, а не совпадало с нижней рамкой.
    pdf.setStrokeColor(colors.HexColor("#425563"))
    pdf.setLineWidth(0.75)
    pdf.line(left, bottom, left, bottom + chart_height)
    zero_y: float | None = None
    if y_min <= 0.0 <= y_max:
        zero_y = bottom + (0.0 - y_min) / (y_max - y_min) * chart_height
        pdf.setLineWidth(1.0)
        pdf.line(left, zero_y, left + chart_width, zero_y)
    else:
        pdf.line(left, bottom, left + chart_width, bottom)

    pdf.setFillColor(colors.black)
    pdf.setFont(FONT_BOLD, 8 if not inset else 5.5)
    pdf.drawString(x, y + height - (10 if not inset else 7), title)
    pdf.setFont(FONT, 6.0 if not inset else 4.5)
    for i in range(6):
        value = y_min + (y_max - y_min) * i / 5
        label_y = bottom + chart_height * i / 5 - (2 if not inset else 1)
        if not inset:
            pdf.drawRightString(left - 4, label_y, fmt(value))
        time_value = t_min + (t_max - t_min) * i / 5
        pdf.drawCentredString(left + chart_width * i / 5,
                              (zero_y if zero_y is not None else bottom) -
                              (11 if not inset else 7),
                              fmt(time_value, 1 if inset else 2))
    if not inset:
        x_axis_y = (zero_y if zero_y is not None else bottom) - 24
        pdf.drawCentredString(left + chart_width / 2, x_axis_y, "t, с")
        pdf.saveState()
        pdf.translate(x + 9, bottom + chart_height / 2)
        pdf.rotate(90)
        pdf.drawCentredString(0, 0, y_label)
        pdf.restoreState()

    for name, key, color in series:
        draw_series(pdf, plot_points, key, color, left, bottom, chart_width,
                    chart_height, t_min, t_max, y_min, y_max)

    if not inset:
        legend_x = left + 5
        legend_y = bottom + chart_height - 12
        pdf.setFont(FONT, 5.8)
        for name, _, color in series:
            pdf.setStrokeColor(color)
            pdf.line(legend_x, legend_y + 2, legend_x + 13, legend_y + 2)
            pdf.setFillColor(colors.black)
            pdf.drawString(legend_x + 16, legend_y, name)
            legend_x += 16 + pdfmetrics.stringWidth(name, FONT, 5.8) + 10


def draw_chart(
    pdf: canvas.Canvas,
    points: Sequence[dict[str, float]],
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    y_label: str,
    series: Sequence[tuple[str, str, colors.Color]],
) -> None:
    t_min = points[0]["t"]
    t_max = points[-1]["t"]
    # Полный диапазон и увеличение первых 10 секунд находятся рядом в одном
    # поле графика, поэтому увеличение не закрывает основной временной ряд.
    zoom_end = min(10.0, t_max)
    gap = 8.0
    zoom_width = width * 0.34
    full_width = width - zoom_width - gap
    draw_plot_area(pdf, points, x, y, full_width, height, title, y_label,
                   series, t_min, t_max)
    zoom_x = x + full_width + gap
    draw_plot_area(pdf, points, zoom_x, y, zoom_width, height,
                   "Первые 10 с", y_label, series, 0.0, zoom_end,
                   inset=True)


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
        PAGE_WIDTH / 2, PAGE_HEIGHT - 39,
        "BalSimulation: H=8000 м, подготовка=3 с, старт=5 с, L=700 км, шаг=0,01 с",
    )
    pdf.setFont(FONT, 6.0)
    legend_x = 28.0
    for mode in MODE_NAMES:
        pdf.setFillColor(MODE_FILL[mode])
        pdf.rect(legend_x, PAGE_HEIGHT - 49, 12, 7, fill=1, stroke=1)
        pdf.setFillColor(MODE_LINE[mode])
        pdf.drawString(legend_x + 16, PAGE_HEIGHT - 48,
                       MODE_NAMES[mode])
        legend_x += 94

    margin_x = 28.0
    top = PAGE_HEIGHT - 59.0
    gap_x = 18.0
    gap_y = 20.0
    chart_width = (PAGE_WIDTH - 2 * margin_x - gap_x) / 2
    chart_height = (PAGE_HEIGHT - 80.0 - gap_y - 28.0) / 2
    for index, (title, y_label, series) in enumerate(charts):
        row, column = divmod(index, 2)
        chart_x = margin_x + column * (chart_width + gap_x)
        chart_y = top - (row + 1) * chart_height - row * gap_y
        draw_chart(pdf, points, chart_x, chart_y, chart_width, chart_height,
                   title, y_label, series)
    pdf.setFont(FONT, 6.5)
    pdf.setFillColor(colors.HexColor("#555555"))
    pdf.drawRightString(PAGE_WIDTH - margin_x, 14,
                        f"Страница {pdf.getPageNumber()}")


def create_graphs() -> None:
    points = downsample(load_trajectory())
    pdf = canvas.Canvas(str(GRAPHS_FILE), pagesize=PAGE)
    pdf.setTitle("Графики прямолинейного полёта — трёхрежимная модель")

    blue = colors.HexColor("#1F4E79")
    orange = colors.HexColor("#C55A11")
    green = colors.HexColor("#548235")
    red = colors.HexColor("#A61C00")
    purple = colors.HexColor("#7030A0")

    draw_graph_page(
        pdf, points, "Прямолинейная траектория и скорость",
        [
            ("Продольная координата", "x, м", [("x ракеты", "x_g_r", blue)]),
            ("Высота полёта", "y, м", [("y ракеты", "y_g_r", green)]),
            ("Скорость", "v, м/с", [("v", "v_r", orange)]),
            ("Число Маха", "M", [("M", "mach", purple)]),
        ],
    )
    pdf.showPage()

    draw_graph_page(
        pdf, points, "Масса и экспоненциальный расход топлива",
        [
            ("Относительная масса топлива", "μ", [
                ("μ израсходованного топлива", "fuel_burned_relative", blue),
            ]),
            ("Масса ракеты", "m, кг", [("m", "mass_r", red)]),
            ("Остаток топлива", "m топлива, кг", [("топливо", "fuel_remaining", purple)]),
            ("Расход топлива", "G, кг/с", [("G", "fuel_rate", orange)]),
        ],
    )
    pdf.showPage()

    draw_graph_page(
        pdf, points, "Тяга и перегрузка",
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
