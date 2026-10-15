from pathlib import Path

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


result_file = find_result_file()
result = pd.read_csv(result_file, delimiter="\t")

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


# Скорость.
fig = go.Figure()
fig.add_trace(go.Scatter(x=result["t"], y=result["v_r"], name="v ракеты"))
fig.update_layout(
    **common_layout,
    title="Изменение скорости по времени",
    xaxis_title="t, с",
    yaxis_title="v, м/с",
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


# Тангенциальная (осевая) перегрузка.
fig = go.Figure()
fig.add_trace(go.Scatter(x=result["t"], y=result["n_xa_r"], name="nₓₐ"))
fig.update_layout(
    **common_layout,
    title="Изменение тангенциальной (осевой) перегрузки",
    xaxis_title="t, с",
    yaxis_title="nₓₐ, безразмерная величина",
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
