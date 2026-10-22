from pathlib import Path
from html import escape
import math
import numbers
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def find_result_file() -> Path:
    project_root = Path(__file__).resolve().parent.parent
    file_name = "flat_flight_trajectory.gra"
    candidates = [
        Path.cwd() / file_name,
        project_root / file_name,
        project_root / "build" / file_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Файл {file_name} не найден. Сначала запустите расчёт программы."
    )


def excel_column_name(column_number: int) -> str:
    """Возвращает имя столбца Excel по его номеру, начиная с 1."""
    name = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def save_tables_to_excel(
    tables: list[tuple[str, pd.DataFrame]], destination: Path
) -> None:
    """Сохраняет несколько таблиц в xlsx без дополнительного Excel-модуля."""
    max_excel_rows = 1_048_576

    def worksheet_xml(table: pd.DataFrame) -> str:
        if len(table) + 1 > max_excel_rows:
            raise ValueError("Таблица превышает ограничение Excel по числу строк")

        worksheet = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
            "<sheetData>",
        ]

        def text_cell(reference: str, value: object) -> str:
            return (
                f'<c r="{reference}" t="inlineStr"><is><t>'
                f"{escape(str(value))}</t></is></c>"
            )

        def value_cell(reference: str, value: object) -> str:
            if value is None or bool(pd.isna(value)):
                return f'<c r="{reference}"/>'

            if isinstance(value, numbers.Number) and not isinstance(value, bool):
                number = float(value)
                if not math.isfinite(number):
                    return f'<c r="{reference}"/>'
                number_text = format(number, ".15g")
                if number_text == "-0":
                    number_text = "0"
                return f'<c r="{reference}"><v>{number_text}</v></c>'

            if isinstance(value, bool):
                return f'<c r="{reference}" t="b"><v>{int(value)}</v></c>'

            return text_cell(reference, value)

        header_cells = [
            text_cell(f"{excel_column_name(index)}1", column)
            for index, column in enumerate(table.columns, start=1)
        ]
        worksheet.append('<row r="1">' + "".join(header_cells) + "</row>")

        for row_number, row in enumerate(
            table.itertuples(index=False, name=None), start=2
        ):
            cells = [
                value_cell(f"{excel_column_name(column_number)}{row_number}", value)
                for column_number, value in enumerate(row, start=1)
            ]
            worksheet.append(
                f'<row r="{row_number}">' + "".join(cells) + "</row>"
            )

        worksheet.append("</sheetData></worksheet>")
        return "".join(worksheet)

    worksheets = [
        (sheet_name, worksheet_xml(table)) for sheet_name, table in tables
    ]
    content_type_overrides = "\n".join(
        f'  <Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index, _ in enumerate(worksheets, start=1)
    )
    content_types = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{content_type_overrides}
</Types>"""
    package_relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    sheet_entries = "\n".join(
        f'    <sheet name="{escape(sheet_name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, (sheet_name, _) in enumerate(worksheets, start=1)
    )
    workbook = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
{sheet_entries}
  </sheets>
</workbook>"""
    relationship_entries = "\n".join(
        f'  <Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index, _ in enumerate(worksheets, start=1)
    )
    workbook_relationships = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{relationship_entries}
</Relationships>"""

    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_relationships)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships)
        for index, (_, xml) in enumerate(worksheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", xml)


result_file = find_result_file()
result = pd.read_csv(result_file, delimiter="\t")
summary_file = result_file.with_name("flat_flight_summary.tsv")
if not summary_file.exists():
    raise FileNotFoundError(
        f"Файл {summary_file.name} не найден. "
        "Сначала повторно запустите расчёт программы."
    )
summary = pd.read_csv(summary_file, delimiter="\t")
excel_file = result_file.with_name("flat_flight_trajectory.xlsx")
save_tables_to_excel(
    [("Summary", summary), ("Trajectory", result)],
    excel_file,
)
print(f"Таблица Excel сохранена: {excel_file}")

common_layout = dict(
    template="plotly_white",
    legend=dict(orientation="h", x=0.5, xanchor="center"),
    margin=dict(l=70, r=30, t=55, b=60),
)


# Прямолинейная траектория по времени: координаты x и y.
fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=("Продольная координата", "Высота"),
)
fig.add_trace(
    go.Scatter(x=result["t"], y=result["x_g_r"], name="x ракеты"),
    row=1,
    col=1,
)
fig.add_trace(
    go.Scatter(x=result["t"], y=result["y_g_r"], name="y ракеты"),
    row=1,
    col=2,
)
fig.update_xaxes(title_text="t, с", row=1, col=1)
fig.update_xaxes(title_text="t, с", row=1, col=2)
fig.update_yaxes(title_text="x, м", row=1, col=1)
fig.update_yaxes(title_text="y, м", row=1, col=2)
fig.update_layout(**common_layout, title="Изменение прямолинейной траектории по времени")
fig.show()


# Скорость в м/с и числах Маха на отдельных полях.
fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=("Скорость, м/с", "Скорость, Мах"),
)
fig.add_trace(
    go.Scatter(x=result["t"], y=result["v_r"], name="v, м/с"),
    row=1,
    col=1,
)
fig.add_trace(
    go.Scatter(x=result["t"], y=result["mach"], name="M"),
    row=1,
    col=2,
)
fig.update_xaxes(title_text="t, с", row=1, col=1)
fig.update_xaxes(title_text="t, с", row=1, col=2)
fig.update_yaxes(title_text="v, м/с", row=1, col=1)
fig.update_yaxes(title_text="M", row=1, col=2)
fig.update_layout(
    **common_layout,
    title="Изменение скорости по времени",
)
fig.show()


# Суммарная относительная масса топлива и доли двух режимов.
fig = go.Figure()
fig.add_trace(go.Scatter(x=result["t"], y=result["mu_summ"], name="μ_summ"))
fig.add_trace(go.Scatter(x=result["t"], y=result["mu_0"], name="μ_0 — стартовый режим"))
fig.add_trace(go.Scatter(x=result["t"], y=result["mu_1"], name="μ_1 — маршевый режим"))
fig.update_layout(
    **common_layout,
    title="Изменение относительных масс топлива",
    xaxis_title="t, с",
    yaxis_title="μ, безразмерная величина",
)
fig.show()


# Нормальная перегрузка.
fig = go.Figure()
fig.add_trace(go.Scatter(x=result["t"], y=result["n_ya_r"], name="nᵧₐ"))
fig.update_layout(
    **common_layout,
    title="Изменение нормальной перегрузки по времени",
    xaxis_title="t, с",
    yaxis_title="nᵧₐ, безразмерная величина",
)
fig.show()


# Расход топлива.
fig = go.Figure()
fig.add_trace(go.Scatter(x=result["t"], y=result["fuel_rate"], name="G"))
fig.update_layout(
    **common_layout,
    title="Расход топлива по времени",
    xaxis_title="t, с",
    yaxis_title="G, кг/с",
)
fig.show()


# Суммарная тяга.
fig = go.Figure()
fig.add_trace(go.Scatter(x=result["t"], y=result["P_r"], name="P"))
fig.update_layout(
    **common_layout,
    title="Изменение суммарной тяги по времени",
    xaxis_title="t, с",
    yaxis_title="P, Н",
)
fig.show()


# Общая масса ракеты.
fig = go.Figure()
fig.add_trace(go.Scatter(x=result["t"], y=result["mass_r"], name="m ракеты"))
fig.update_layout(
    **common_layout,
    title="Изменение общей массы ракеты по времени",
    xaxis_title="t, с",
    yaxis_title="m, кг",
)
fig.show()
