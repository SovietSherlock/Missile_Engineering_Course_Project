import numpy as np
import pandas as pd
import math

import plotly
import plotly.io as pio
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from IPython.display import display, HTML

pio.templates.default = 'plotly_white'

# Чтение основных файлов
Result_C = pd.read_csv('V26_Best_high_C.gra', delimiter="\t")
Result_N = pd.read_csv('V26_Best_high_N.gra', delimiter="\t")
Result_R = pd.read_csv('V26_Best_high_R.gra', delimiter="\t")
Result_Kinematic = pd.read_csv('V26_Best_high_Kinematic.gra', delimiter="\t")

# ============================================================================
# ЧТЕНИЕ ФАЙЛА РАДИОГОРИЗОНТА
# ============================================================================
try:
    Result_Horizon = pd.read_csv('V26_Best_high_Horizon.gra', delimiter="\t")
    print("Файл радиогоризонта успешно загружен")
    print(f"Количество точек: {len(Result_Horizon)}")
    print(f"Колонки: {Result_Horizon.columns.tolist()}")
except FileNotFoundError:
    print("Файл радиогоризонта не найден!")
    Result_Horizon = None

# ============================================================================
# ПОСТРОЕНИЕ ТРАЕКТОРИЙ С ЛИНИЯМИ ВИЗИРОВАНИЯ И РАДИОГОРИЗОНТОМ
# ============================================================================
N_lv = 5  # количество линий визирования для построения

LVs = []

for i in range(0, N_lv):
    LV = dict({
        'x': [],
        'y': []
    })

    t_index = math.floor(len(Result_R['t']) / (N_lv) * (i))
    LV['x'] = [Result_N['x_g_n'][t_index], Result_R['x_g_r'][t_index], Result_C['x_g_c'][t_index]]
    LV['y'] = [Result_N['y_g_n'][t_index], Result_R['y_g_r'][t_index], Result_C['y_g_c'][t_index]]

    LVs.append(LV)

fig = go.Figure()
fig.update_layout(
    title='Траектории',
    xaxis_title=r'$x_g,\ м$',
    yaxis_title=r'$y_g,\ м$',
    legend_orientation="h", legend=dict(x=.5, xanchor="center"), margin=dict(l=0, r=0, t=30, b=0)
)

# Основные траектории
fig.add_trace(go.Scatter(x=Result_R['x_g_r'], y=Result_R['y_g_r'], name=r'Ракета', line=dict(color='#9B1215')))
fig.add_trace(go.Scatter(x=Result_C['x_g_c'], y=Result_C['y_g_c'], name=r'Цель', line=dict(color='#004E9F')))
fig.add_trace(go.Scatter(x=Result_N['x_g_n'], y=Result_N['y_g_n'], name=r'Носитель', line=dict(color='black')))

# Линии визирования
for i in range(0, N_lv):
    fig.add_trace(go.Scatter(x=LVs[i]['x'], y=LVs[i]['y'], name=r'', line=dict(color='black', width=1, dash='dashdot')))

# ============================================================================
# ДОБАВЛЕНИЕ РАДИОГОРИЗОНТА НА ГРАФИК ТРАЕКТОРИИ (x vs y)
# ============================================================================
if Result_Horizon is not None:
    mask_valid = Result_Horizon['y_radar_horizon'] > 0
    if mask_valid.any():
        # Создаем массив x координат для радиогоризонта
        horizon_x = []
        horizon_y = []

        for idx in Result_Horizon.index[mask_valid]:
            t_val = Result_Horizon.loc[idx, 't']
            # Находим ближайшую точку в Result_R по времени
            r_idx = (Result_R['t'] - t_val).abs().idxmin()
            horizon_x.append(Result_R.loc[r_idx, 'x_g_r'])
            horizon_y.append(Result_Horizon.loc[idx, 'y_radar_horizon'])

        # Добавляем радиогоризонт
        fig.add_trace(go.Scatter(
            x=horizon_x,
            y=horizon_y,
            name=r'Радиогоризонт',
            line=dict(color='red', dash='dash', width=2)
        ))

# Улучшаем масштаб: смещаем ось x вниз (показываем отрицательные значения)
# и увеличиваем масштаб по y для лучшего обзора
x_min = min(Result_R['x_g_r'].min(), Result_N['x_g_n'].min(), Result_C['x_g_c'].min())
x_max = max(Result_R['x_g_r'].max(), Result_N['x_g_n'].max(), Result_C['x_g_c'].max())
y_max = max(Result_R['y_g_r'].max(), Result_N['y_g_n'].max(), Result_C['y_g_c'].max())

fig.update_xaxes(
    range=[0, x_max * 1.05]  # Смещаем ось X вниз (отрицательные значения)
)
fig.update_yaxes(
    scaleanchor="x",
    scaleratio=1,
    range=[0, y_max * 1.2]  # Увеличиваем диапазон по Y для лучшего обзора
)
fig.show()

# ============================================================================
# КООРДИНАТЫ С РАДИОГОРИЗОНТОМ (БЕЗ УВЕЛИЧЕНИЯ МАСШТАБА ПО Y)
# ============================================================================
fig = make_subplots(rows=1, cols=2, subplot_titles=("Координаты X", "Координаты Y с радиогоризонтом"))
fig.update_layout(legend_orientation="h", legend=dict(x=.5, xanchor="center"), margin=dict(l=0, r=0, t=30, b=0))

fig.update_xaxes(title=r'$t,\ с$', row=1, col=1)
fig.update_yaxes(title=r'$x_g,\ м$', row=1, col=1)
fig.add_trace(go.Scatter(x=Result_R['t'], y=Result_R['x_g_r'], name=r'$x_р$', line=dict(color='#9B1215')), 1, 1)
fig.add_trace(go.Scatter(x=Result_C['t'], y=Result_C['x_g_c'], name=r'$x_ц$', line=dict(color='#004E9F')), 1, 1)
fig.add_trace(go.Scatter(x=Result_N['t'], y=Result_N['x_g_n'], name=r'$x_н$', line=dict(color='black')), 1, 1)

fig.update_xaxes(title=r'$t,\ с$', row=1, col=2)
fig.update_yaxes(title=r'$y_g,\ м$', row=1, col=2)  # Без ограничения диапазона
fig.add_trace(go.Scatter(x=Result_R['t'], y=Result_R['y_g_r'], name=r'$y_р$', line=dict(color='#9B1215')), 1, 2)
fig.add_trace(go.Scatter(x=Result_C['t'], y=Result_C['y_g_c'], name=r'$y_ц$', line=dict(color='#004E9F')), 1, 2)
fig.add_trace(go.Scatter(x=Result_N['t'], y=Result_N['y_g_n'], name=r'$y_н$', line=dict(color='black')), 1, 2)

# Добавляем радиогоризонт на график высоты
if Result_Horizon is not None:
    mask_valid = Result_Horizon['y_radar_horizon'] > 0
    if mask_valid.any():
        fig.add_trace(
            go.Scatter(
                x=Result_Horizon['t'][mask_valid],
                y=Result_Horizon['y_radar_horizon'][mask_valid],
                name=r'$y_{рад}$',
                line=dict(color='red', dash='dash', width=2)
            ), 1, 2
        )
fig.show()

# ============================================================================
# ПЕРЕГРУЗКИ
# ============================================================================
fig = make_subplots(rows=1, cols=2, subplot_titles=("Тангенциальная перегрузка", "Нормальная скоростная перегрузка"))
fig.update_layout(legend_orientation="h", legend=dict(x=.5, xanchor="center"), margin=dict(l=0, r=0, t=30, b=0))

fig.update_xaxes(title=r'$t,\ с$', row=1, col=1)
fig.update_yaxes(title=r'$n_{x_a}$', row=1, col=1)
fig.add_trace(go.Scatter(x=Result_R['t'], y=Result_R['n_xa_r'], name=r'$n_{x_a р}$ потребная', line=dict(color='#9B1215')), 1, 1)
fig.add_trace(go.Scatter(x=Result_R['t'], y=Result_R['n_y_max'], name=r'$n_{y}^{max}$ располагаемая', line=dict(color='#00684C', dash='dash')), 1, 1)

fig.update_xaxes(title=r'$t,\ с$', row=1, col=2)
fig.update_yaxes(title=r'$n_{y_a}$', row=1, col=2)
fig.add_trace(go.Scatter(x=Result_R['t'], y=Result_R['n_ya_r'], name=r'$n_{y_a р}$ потребная', line=dict(color='#9B1215')), 1, 2)
fig.add_trace(go.Scatter(x=Result_R['t'], y=Result_R['n_y_max'], name=r'$n_{y}^{max}$ располагаемая', line=dict(color='#00684C', dash='dash')), 1, 2)
fig.show()

# ============================================================================
# ПОЛНАЯ ТЯГА
# ============================================================================
fig = go.Figure()
fig.add_trace(go.Scatter(x=Result_R['t'], y=Result_R['P_r'], name=r'$P_{val}$',
                         line=dict(color='#9B1215')))
fig.update_layout(title='Полная тяга ракеты', xaxis_title=r'$t,\ с$',
                  yaxis_title=r'$P_{val},\ Н$',
                  legend_orientation="h", legend=dict(x=.5, xanchor="center"))
fig.show()

# ============================================================================
# СКОРОСТЬ И УГОЛ
# ============================================================================
fig = make_subplots(rows=1, cols=2, subplot_titles=("Скорость", "Угол наклона траектории"))
fig.update_layout(legend_orientation="h", legend=dict(x=.5, xanchor="center"), margin=dict(l=0, r=0, t=30, b=0))

fig.update_xaxes(title=r'$t,\ с$', row=1, col=1)
fig.update_yaxes(title=r'$v,\ м/с$', row=1, col=1)
fig.add_trace(go.Scatter(x=Result_R['t'], y=Result_R['v_r'], name=r'$v_р$', line=dict(color='#9B1215')), 1, 1)
fig.add_trace(go.Scatter(x=Result_C['t'], y=Result_C['v_c'], name=r'$v_ц$', line=dict(color='#004E9F')), 1, 1)
fig.add_trace(go.Scatter(x=Result_N['t'], y=Result_N['v_n'], name=r'$v_н$', line=dict(color='black')), 1, 1)

fig.update_xaxes(title=r'$t,\ с$', row=1, col=2)
fig.update_yaxes(title=r'$\Theta,\ ^\circ$', row=1, col=2)
fig.add_trace(
    go.Scatter(x=Result_R['t'], y=np.rad2deg(Result_R['Theta_r']), name=r'$\Theta_р$', line=dict(color='#9B1215')), 1,
    2)
fig.add_trace(
    go.Scatter(x=Result_C['t'], y=np.rad2deg(Result_C['Theta_c']), name=r'$\Theta_ц$', line=dict(color='#004E9F')), 1,
    2)
fig.add_trace(
    go.Scatter(x=Result_N['t'], y=np.rad2deg(Result_N['Theta_n']), name=r'$\Theta_н$', line=dict(color='black')), 1, 2)
fig.show()

# ============================================================================
# КИНЕМАТИКА: РАССТОЯНИЯ И УГЛЫ
# ============================================================================
fig = make_subplots(rows=1, cols=2, subplot_titles=("Расстояние", "Угол наклона линии визирования"))
fig.update_layout(legend_orientation="h", legend=dict(x=.5, xanchor="center"), margin=dict(l=0, r=0, t=30, b=0))

fig.update_xaxes(title=r'$t,\ с$', row=1, col=1)
fig.update_yaxes(title=r'$r,\ м$', row=1, col=1)
fig.add_trace(
    go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['r_rc'], name=r'$r_{р-ц}$', line=dict(color='#9B1215')), 1,
    1)
fig.add_trace(
    go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['r_nr'], name=r'$r_{н-р}$', line=dict(color='#004E9F')), 1,
    1)
fig.add_trace(
    go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['r_nc'], name=r'$r_{н-ц}$', line=dict(color='black')), 1, 1)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['Delta_r'], name=r'$\Delta r$',
                         line=dict(color='#00684C', width=4, dash='dash')), 1, 1)

fig.update_xaxes(title=r'$t,\ с$', row=1, col=2)
fig.update_yaxes(title=r'$\epsilon,\ ^\circ$', row=1, col=2)
fig.add_trace(
    go.Scatter(x=Result_Kinematic['t'], y=np.rad2deg(Result_Kinematic['epsilon_rc']), name=r'$\epsilon_{р-ц}$',
               line=dict(color='#9B1215')), 1, 2)
fig.add_trace(
    go.Scatter(x=Result_Kinematic['t'], y=np.rad2deg(Result_Kinematic['epsilon_nr']), name=r'$\epsilon_{н-р}$',
               line=dict(color='#004E9F')), 1, 2)
fig.add_trace(
    go.Scatter(x=Result_Kinematic['t'], y=np.rad2deg(Result_Kinematic['epsilon_nc']), name=r'$\epsilon_{н-ц}$',
               line=dict(color='black')), 1, 2)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=np.rad2deg(Result_Kinematic['epsilon_l']), name=r'$\epsilon_л$',
                         line=dict(color='#00684C', width=4, dash='dash')), 1, 2)
fig.show()

# ============================================================================
# КИНЕМАТИКА: ПЕРВЫЕ ПРОИЗВОДНЫЕ
# ============================================================================
fig = make_subplots(rows=1, cols=2,
                    subplot_titles=("Скорость изменения расстояния", "Угловая скорость вращения линии визирования"))
fig.update_layout(legend_orientation="h", legend=dict(x=.5, xanchor="center"), margin=dict(l=0, r=0, t=30, b=0))

fig.update_xaxes(title=r'$t,\ с$', row=1, col=1)
fig.update_yaxes(title=r'$\dot r,\ м/с$', row=1, col=1)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['dot_r_rc'], name=r'$\dot r_{р-ц}$',
                         line=dict(color='#9B1215')), 1, 1)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['dot_r_nr'], name=r'$\dot r_{н-р}$',
                         line=dict(color='#004E9F')), 1, 1)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['dot_r_nc'], name=r'$\dot r_{н-ц}$',
                         line=dict(color='black')), 1, 1)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['dot_Delta_r'], name=r'$\Delta \dot r$',
                         line=dict(color='#00684C', width=4, dash='dash')), 1, 1)

fig.update_xaxes(title=r'$t,\ с$', row=1, col=2)
fig.update_yaxes(title=r'$\dot \epsilon,\ рад/с$', row=1, col=2)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['dot_epsilon_rc'], name=r'$\dot \epsilon_{р-ц}$',
                         line=dict(color='#9B1215')), 1, 2)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['dot_epsilon_nr'], name=r'$\dot \epsilon_{н-р}$',
                         line=dict(color='#004E9F')), 1, 2)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['dot_epsilon_nc'], name=r'$\dot \epsilon_{н-ц}$',
                         line=dict(color='black')), 1, 2)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['dot_epsilon_l'], name=r'$\dot \epsilon_л$',
                         line=dict(color='#00684C', width=4, dash='dash')), 1, 2)
fig.show()

# ============================================================================
# КИНЕМАТИКА: ВТОРЫЕ ПРОИЗВОДНЫЕ
# ============================================================================
fig = make_subplots(rows=1, cols=2,
                    subplot_titles=("Ускорение изменения расстояния", "Угловое ускорение вращения линии визирования"))
fig.update_layout(legend_orientation="h", legend=dict(x=.5, xanchor="center"), margin=dict(l=0, r=0, t=30, b=0))

fig.update_xaxes(title=r'$t,\ с$', row=1, col=1)
fig.update_yaxes(title=r'$\ddot r,\ м/с^2$', row=1, col=1)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['ddot_r_rc'], name=r'$\ddot r_{р-ц}$',
                         line=dict(color='#9B1215')), 1, 1)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['ddot_r_nr'], name=r'$\ddot r_{н-р}$',
                         line=dict(color='#004E9F')), 1, 1)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['ddot_r_nc'], name=r'$\ddot r_{н-ц}$',
                         line=dict(color='black')), 1, 1)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['ddot_Delta_r'], name=r'$\Delta \ddot r$',
                         line=dict(color='#00684C', width=4, dash='dash')), 1, 1)

fig.update_xaxes(title=r'$t,\ с$', row=1, col=2)
fig.update_yaxes(title=r'$\ddot \epsilon,\ рад/с^2$', row=1, col=2)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['ddot_epsilon_rc'], name=r'$\ddot \epsilon_{р-ц}$',
                         line=dict(color='#9B1215')), 1, 2)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['ddot_epsilon_nr'], name=r'$\ddot \epsilon_{н-р}$',
                         line=dict(color='#004E9F')), 1, 2)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['ddot_epsilon_nc'], name=r'$\ddot \epsilon_{н-ц}$',
                         line=dict(color='black')), 1, 2)
fig.add_trace(go.Scatter(x=Result_Kinematic['t'], y=Result_Kinematic['ddot_epsilon_l'], name=r'$\ddot \epsilon_л$',
                         line=dict(color='#00684C', width=4, dash='dash')), 1, 2)
fig.show()

# ============================================================================
# СПЕЦИАЛЬНЫЙ ГРАФИК: РАДИОГОРИЗОНТ (ДЕТАЛЬНЫЙ)
# ============================================================================
if Result_Horizon is not None:
    fig = make_subplots(rows=2, cols=2,
                        subplot_titles=("Высота и радиогоризонт", "Видимость цели",
                                        "Расстояние до цели", "Граница радиогоризонта vs расстояние"),
                        vertical_spacing=0.15)
    fig.update_layout(legend_orientation="h", legend=dict(x=.5, xanchor="center"),
                      margin=dict(l=0, r=0, t=30, b=0), height=800)

    # График 1: Высота и радиогоризонт
    fig.update_xaxes(title=r'$t,\ с$', row=1, col=1)
    fig.update_yaxes(title=r'$y,\ м$', row=1, col=1, range=[0, 500])  # Увеличенный масштаб для детального обзора
    fig.add_trace(
        go.Scatter(x=Result_Horizon['t'], y=Result_Horizon['y_g_r'],
                   name=r'$y_{ракеты}$', line=dict(color='#9B1215')), 1, 1)

    # Маршевая высота
    fig.add_trace(
        go.Scatter(x=[Result_Horizon['t'].min(), Result_Horizon['t'].max()], y=[5.5, 5.5],
                   name=r'$H_{марш}$', line=dict(color='green', dash='dash', width=2)), 1, 1)

    # Радиогоризонт (только валидные значения)
    mask_valid = Result_Horizon['y_radar_horizon'] > 0
    if mask_valid.any():
        fig.add_trace(
            go.Scatter(x=Result_Horizon['t'][mask_valid],
                       y=Result_Horizon['y_radar_horizon'][mask_valid],
                       name=r'$y_{рад}$', line=dict(color='red', dash='dash', width=2)), 1, 1)

    # График 2: Видимость цели
    fig.update_xaxes(title=r'$t,\ с$', row=1, col=2)
    fig.update_yaxes(title=r'$Видимость$', row=1, col=2, range=[-0.1, 1.1])
    fig.add_trace(
        go.Scatter(x=Result_Horizon['t'], y=Result_Horizon['is_visible'],
                   name=r'$Видимость$', line=dict(color='#00684C'), mode='lines+markers'), 1, 2)

    # График 3: Расстояние до цели
    fig.update_xaxes(title=r'$t,\ с$', row=2, col=1)
    fig.update_yaxes(title=r'$r_{р-ц},\ м$', row=2, col=1)
    fig.add_trace(
        go.Scatter(x=Result_Horizon['t'], y=Result_Horizon['r_rc'],
                   name=r'$r_{р-ц}$', line=dict(color='#9B1215')), 2, 1)

    # График 4: Радиогоризонт vs расстояние
    fig.update_xaxes(title=r'$r_{р-ц},\ м$', row=2, col=2)
    fig.update_yaxes(title=r'$y,\ м$', row=2, col=2, range=[-50, 500])
    if mask_valid.any():
        fig.add_trace(
            go.Scatter(x=Result_Horizon['r_rc'][mask_valid],
                       y=Result_Horizon['y_radar_horizon'][mask_valid],
                       name=r'$y_{рад}(r)$', line=dict(color='red', dash='dash', width=2)), 2, 2)
    fig.add_trace(
        go.Scatter(x=Result_Horizon['r_rc'], y=Result_Horizon['y_g_r'],
                   name=r'$y_{ракеты}(r)$', line=dict(color='#9B1215')), 2, 2)

    fig.show()

    # ============================================================================
    # СТАТИСТИКА РАДИОГОРИЗОНТА
    # ============================================================================
    print("\n" + "=" * 60)
    print("СТАТИСТИКА РАДИОГОРИЗОНТА")
    print("=" * 60)

    total_points = len(Result_Horizon)
    visible_points = Result_Horizon['is_visible'].sum()
    hidden_points = total_points - visible_points

    print(f"Всего точек траектории: {total_points}")
    print(f"Точек с видимой целью: {visible_points} ({100 * visible_points / total_points:.1f}%)")
    print(f"Точек со скрытой целью: {hidden_points} ({100 * hidden_points / total_points:.1f}%)")

    # Поиск проблемных участков
    mask_problem = (Result_Horizon['y_g_r'] < 5.5) & (Result_Horizon['is_visible'] == 1) & (
                Result_Horizon['y_radar_horizon'] > 0)
    problem_points = mask_problem.sum()
    if problem_points > 0:
        print(f"\n!!! ОБНАРУЖЕНА ПРОБЛЕМА РАДИОГОРИЗОНТА !!!")
        print(f"Точек, где ракета ниже маршевой высоты, но выше радиогоризонта: {problem_points}")
        problem_idx = mask_problem.idxmax() if mask_problem.any() else None
        if problem_idx is not None:
            print(f"Первая проблемная точка: t={Result_Horizon.loc[problem_idx, 't']:.2f}с, "
                  f"y_ракеты={Result_Horizon.loc[problem_idx, 'y_g_r']:.2f}м, "
                  f"y_рад={Result_Horizon.loc[problem_idx, 'y_radar_horizon']:.2f}м")
    else:
        print("\nПроблем радиогоризонта не обнаружено.")

    valid_horizon = Result_Horizon[Result_Horizon['y_radar_horizon'] > 0]
    if len(valid_horizon) > 0:
        print(f"\nСтатистика радиогоризонта (валидные значения):")
        print(f"  Минимальное значение: {valid_horizon['y_radar_horizon'].min():.2f} м")
        print(f"  Максимальное значение: {valid_horizon['y_radar_horizon'].max():.2f} м")
        print(f"  Среднее значение: {valid_horizon['y_radar_horizon'].mean():.2f} м")

    print("=" * 60)

else:
    print("\nФайл радиогоризонта не найден. Пропускаем построение графиков радиогоризонта.")
