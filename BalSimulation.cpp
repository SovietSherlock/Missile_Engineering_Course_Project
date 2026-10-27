#include "BalSimulation.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>

#include "Atm_GOST4401.h"
#include "LibConstFunc.h"

namespace
{
constexpr double fuel_epsilon = 1e-12;

bool finite_positive(double value)
{
    return std::isfinite(value) && value > 0.0;
}

bool finite_non_negative(double value)
{
    return std::isfinite(value) && value >= 0.0;
}

// Рассчитывает массовые параметры по массовому уравнению для ЛА
// с двухрежимным двигателем. В отличие от прежней версии, коэффициенты
// совершенства стартовой и маршевой установок задаются отдельно.
bool calculate_mass_parameters(
    const BalSimulationConfig& config,
    double v0,
    double v_march,
    BalMassParameters& parameters)
{
    parameters.v0 = v0;
    parameters.v_march = v_march;
    parameters.delta_v_start = v_march - v0;
    parameters.mu_summ = config.mu_summ_limit;
    parameters.beta_start = config.beta_start;
    parameters.beta_march = config.beta_march;
    parameters.beta = config.beta_start;

    if (!finite_positive(config.payload_mass) ||
        !finite_positive(config.start_specific_impulse) ||
        !finite_positive(config.march_specific_impulse) ||
        !finite_positive(config.start_duration) ||
        !finite_positive(config.loss_factor) ||
        !finite_positive(config.beta_start) ||
        !finite_positive(config.beta_march) ||
        parameters.delta_v_start <= 0.0 ||
        parameters.mu_summ <= 0.0 || parameters.mu_summ > 1.0)
    {
        return false;
    }

    const double effective_start_exhaust_velocity =
        config.loss_factor * config.start_specific_impulse;
    parameters.mu_start = 1.0 - std::exp(
        -parameters.delta_v_start / effective_start_exhaust_velocity);
    parameters.mu_march = parameters.mu_summ - parameters.mu_start;

    if (parameters.mu_march <= 0.0 || parameters.mu_start <= 0.0 ||
        parameters.mu_start >= 1.0)
    {
        return false;
    }

    // mu_march_local относится к массе ракеты после стартового режима.
    parameters.mu_march_local =
        parameters.mu_march / (1.0 - parameters.mu_start);
    parameters.Km = parameters.mu_march / parameters.mu_start;

    const double denominator =
        1.0 - config.beta_start * parameters.mu_start -
        (1.0 - parameters.mu_start) * config.beta_march *
            parameters.mu_march_local;
    if (!finite_positive(denominator))
        return false;

    parameters.m0 = config.payload_mass / denominator;
    parameters.total_fuel_mass = parameters.m0 * parameters.mu_summ;
    parameters.start_fuel_mass = parameters.m0 * parameters.mu_start;
    parameters.march_fuel_mass = parameters.m0 * parameters.mu_march;
    parameters.eta_0 =
        parameters.delta_v_start / config.start_duration / g;
    parameters.start_thrust = parameters.eta_0 * parameters.m0 * g;

    return finite_positive(parameters.m0) &&
           finite_positive(parameters.total_fuel_mass) &&
           finite_positive(parameters.beta);
}

// Определяет площадь миделя и калибр по референсной нагрузке П-800.
// Референсная нагрузка не оптимизируется графиком: она непосредственно
// переносится на проектируемую ракету.
bool calculate_geometry(
    const BalSimulationConfig& config,
    BalMassParameters& parameters)
{
    if (!finite_positive(config.reference_mass) ||
        !finite_positive(config.reference_diameter) ||
        !finite_positive(config.rocket_density))
    {
        return false;
    }

    parameters.reference_midship_area =
        pi * config.reference_diameter * config.reference_diameter / 4.0;
    parameters.reference_midship_load =
        config.reference_mass * g / parameters.reference_midship_area;

    parameters.midship_load_start = parameters.reference_midship_load;
    parameters.midship_area = parameters.m0 * g /
        parameters.midship_load_start;
    parameters.diameter = std::sqrt(
        4.0 * parameters.midship_area / pi);
    parameters.midship_load_march = parameters.midship_load_start *
        (1.0 - parameters.mu_start);

    // Геометрическая оценка соответствует используемой ранее формуле
    // средней плотности ракеты и дополнительно выдаёт удлинение.
    parameters.rocket_length =
        (24.0 * parameters.m0) /
        (5.0 * pi * parameters.diameter * parameters.diameter *
         config.rocket_density);
    parameters.lambda = parameters.rocket_length / parameters.diameter;

    return finite_positive(parameters.midship_area) &&
           finite_positive(parameters.diameter) &&
           finite_positive(parameters.rocket_length);
}

void save_trajectory_file(const std::vector<BalTrajectoryPoint>& trajectory)
{
    std::ofstream file("flat_flight_trajectory.gra");
    file << "t\tx_g_r\ty_g_r\tv_r\tmach\tTheta_r\tn_xa_r\tn_ya_r"
         << "\tfuel_rate\tfuel_remaining\tP_r\tmass_r"
         << "\tmu_summ\tmu_0\tmu_1\tfuel_burned_relative"
         << "\tflight_mode\n";
    file << std::setprecision(12);

    for (const BalTrajectoryPoint& point : trajectory)
    {
        file << point.t << "\t"
             << point.x_g_r << "\t"
             << point.y_g_r << "\t"
             << point.v_r << "\t"
             << point.mach << "\t"
             << point.Theta_r << "\t"
             << point.n_xa_r << "\t"
             << point.n_ya_r << "\t"
             << point.fuel_rate << "\t"
             << point.fuel_remaining << "\t"
             << point.P_r << "\t"
             << point.mass_r << "\t"
             << point.mu_summ << "\t"
             << point.mu_0 << "\t"
             << point.mu_1 << "\t"
             << point.fuel_burned_relative << "\t"
             << point.flight_mode << "\n";
    }
}

void save_summary_file(
    const BalSimulationConfig& config,
    const BalSimulationResult& result)
{
    const BalMassParameters& p = result.parameters;
    std::ofstream file("flat_flight_summary.tsv");
    file << "Показатель\tЗначение\tЕдиницы\n";
    file << std::setprecision(12)
         << "m0\t" << p.m0 << "\tкг\n"
         << "beta_start\t" << p.beta_start << "\t-\n"
         << "beta_march\t" << p.beta_march << "\t-\n"
         << "mu_summ\t" << p.mu_summ << "\t-\n"
         << "mu_0 (стартовое топливо)\t" << p.mu_start << "\t-\n"
         << "mu_1 (маршевое топливо, относительно m0)\t"
         << p.mu_march << "\t-\n"
         << "mu_1_local\t" << p.mu_march_local << "\t-\n"
         << "Масса топлива суммарная\t" << p.total_fuel_mass << "\tкг\n"
         << "Масса стартового топлива\t" << p.start_fuel_mass << "\tкг\n"
         << "Масса маршевого топлива\t" << p.march_fuel_mass << "\tкг\n"
         << "eta_0\t" << p.eta_0 << "\t-\n"
         << "Kp (средняя маршевая тяга)\t" << p.Kp << "\t-\n"
         << "Km\t" << p.Km << "\t-\n"
         << "Начальная тяга\t" << p.start_thrust << "\tН\n"
         << "Средняя маршевая тяга\t" << p.march_thrust << "\tН\n"
         << "Начальная маршевая тяга\t" << p.march_thrust_start << "\tН\n"
         << "Конечная маршевая тяга\t" << p.march_thrust_end << "\tН\n"
         << "q_m0 референсная\t" << p.reference_midship_load << "\tН/м^2\n"
         << "q_m0 проектируемой ракеты\t" << p.midship_load_start << "\tН/м^2\n"
         << "q_m1 после старта\t" << p.midship_load_march << "\tН/м^2\n"
         << "Площадь миделя\t" << p.midship_area << "\tм^2\n"
         << "Калибр\t" << p.diameter << "\tм\n"
         << "Удлинение\t" << p.lambda << "\t-\n"
         << "Длина ракеты\t" << p.rocket_length << "\tм\n"
         << "Подготовительная дальность\t" << p.preparation_distance << "\tм\n"
         << "Стартовая дальность\t" << p.start_distance << "\tм\n"
         << "Маршевая дальность\t" << p.march_distance << "\tм\n"
         << "Время подготовки\t" << config.preparation_duration << "\tс\n"
         << "Время полёта\t" << p.flight_time << "\tс\n";
}
}

BalSimulationResult run_bal_simulation(const BalSimulationConfig& config)
{
    BalSimulationResult result;

    const double speed_of_sound = Atm_GOST4401::a_atm(config.altitude);
    if (!finite_positive(speed_of_sound) ||
        !finite_positive(config.initial_mach) ||
        !finite_positive(config.march_mach) ||
        !finite_non_negative(config.preparation_duration) ||
        !finite_positive(config.integration_dt) ||
        !finite_positive(config.target_range) ||
        config.target_range < 700000.0)
    {
        result.status = "invalid_flight_conditions";
        return result;
    }

    const double v0 = config.initial_mach * speed_of_sound;
    const double v_march = config.march_mach * speed_of_sound;
    if (!calculate_mass_parameters(config, v0, v_march, result.parameters) ||
        !calculate_geometry(config, result.parameters))
    {
        result.status = "invalid_mass_parameters";
        return result;
    }

    BalMassParameters& p = result.parameters;
    p.preparation_distance = v0 * config.preparation_duration;
    p.start_distance = v0 * config.start_duration +
        0.5 * (p.delta_v_start / config.start_duration) *
        config.start_duration * config.start_duration;
    p.march_distance = config.target_range -
        p.preparation_distance - p.start_distance;

    if (p.march_distance <= 0.0)
    {
        result.status = "invalid_target_range";
        return result;
    }

    const double march_time = p.march_distance / v_march;
    p.flight_time = config.preparation_duration +
        config.start_duration + march_time;
    p.start_mass_end = p.m0 * (1.0 - p.mu_start);
    p.march_mass_end = p.m0 * (1.0 - p.mu_summ);

    if (!finite_positive(march_time) ||
        !finite_positive(p.start_mass_end) ||
        !finite_positive(p.march_mass_end))
    {
        result.status = "invalid_march_parameters";
        return result;
    }

    // Экспоненциальный маршевый расход подбирается так, чтобы за время
    // маршевого участка масса точно перешла от start_mass_end к dry mass.
    const double march_decay = std::log(
        p.start_mass_end / p.march_mass_end) / march_time;
    const double average_march_fuel_rate =
        p.march_fuel_mass / march_time;
    p.march_thrust = average_march_fuel_rate *
        config.march_specific_impulse;
    p.march_thrust_start = march_decay * p.start_mass_end *
        config.march_specific_impulse;
    p.march_thrust_end = march_decay * p.march_mass_end *
        config.march_specific_impulse;
    p.Kp = p.march_thrust / p.start_thrust;

    const double dry_mass = p.march_mass_end;
    const double start_acceleration =
        p.delta_v_start / config.start_duration;
    const double effective_start_exhaust_velocity =
        config.loss_factor * config.start_specific_impulse;

    auto append_point = [&](double t, double x, double velocity,
                            double mass, double fuel_rate, double thrust,
                            double n_xa, double mu_start_remaining,
                            double mu_march_remaining, int mode)
    {
        BalTrajectoryPoint point;
        point.t = t;
        point.x_g_r = x;
        point.y_g_r = config.altitude;
        point.v_r = velocity;
        point.mach = velocity / speed_of_sound;
        point.Theta_r = 0.0;
        point.n_xa_r = n_xa;
        point.n_ya_r = 1.0;
        point.fuel_rate = std::max(0.0, fuel_rate);
        point.fuel_remaining = std::clamp(mass - dry_mass,
                                          0.0, p.total_fuel_mass);
        point.P_r = std::max(0.0, thrust);
        point.mass_r = mass;
        point.mu_summ = point.fuel_remaining / p.m0;
        point.mu_0 = std::max(0.0, mu_start_remaining);
        point.mu_1 = std::max(0.0, mu_march_remaining);
        point.fuel_burned_relative = std::clamp(
            p.mu_summ - point.mu_summ, 0.0, p.mu_summ);
        point.flight_mode = mode;
        result.trajectory.push_back(point);
    };

    // Подготовительный участок: ракета сходит с пилона и движется без тяги.
    double t = 0.0;
    append_point(t, 0.0, v0, p.m0, 0.0, 0.0, 0.0,
                 p.mu_start, p.mu_march, 0);
    while (t < config.preparation_duration - fuel_epsilon)
    {
        const double next_t = std::min(
            config.preparation_duration, t + config.integration_dt);
        t = next_t;
        append_point(t, v0 * t, v0, p.m0, 0.0, 0.0, 0.0,
                     p.mu_start, p.mu_march, 0);
    }

    // Фиксируем точку начала стартового режима отдельно: это позволяет
    // однозначно показать на графике границу t=3 с без временного зазора.
    append_point(t, p.preparation_distance, v0, p.m0,
                 p.m0 * start_acceleration / effective_start_exhaust_velocity,
                 p.start_thrust, p.eta_0, p.mu_start, p.mu_march, 1);

    // Стартовый участок: экспоненциальное изменение массы по Циолковскому.
    const double start_begin_t = config.preparation_duration;
    const double start_end_t = start_begin_t + config.start_duration;
    while (t < start_end_t - fuel_epsilon)
    {
        const double next_t = std::min(
            start_end_t, t + config.integration_dt);
        const double elapsed = next_t - start_begin_t;
        const double velocity = v0 + start_acceleration * elapsed;
        const double mass = p.m0 * std::exp(
            -(velocity - v0) / effective_start_exhaust_velocity);
        const double fuel = std::max(0.0, mass - dry_mass);
        const double start_remaining = std::max(
            0.0, fuel - p.march_fuel_mass) / p.m0;
        const double fuel_rate = mass * start_acceleration /
            effective_start_exhaust_velocity;

        t = next_t;
        append_point(t,
                     p.preparation_distance +
                         v0 * elapsed +
                         0.5 * start_acceleration * elapsed * elapsed,
                     velocity, mass, fuel_rate,
                     mass * start_acceleration,
                     p.eta_0, start_remaining, p.mu_march, 1);
    }

    // Аналогично фиксируем начало маршевого участка в момент окончания
    // стартового разгона, не изменяя массу и координату при переходе.
    append_point(t, p.preparation_distance + p.start_distance, p.v_march,
                 p.start_mass_end, march_decay * p.start_mass_end,
                 p.march_thrust_start, 0.0,
                 0.0, p.mu_march, 2);

    // Маршевый участок: экспоненциальное выгорание топлива при постоянной
    // скорости и высоте. Тяга определяется текущим расходом топлива.
    const double march_start_t = start_end_t;
    while (t < p.flight_time - fuel_epsilon)
    {
        const double next_t = std::min(
            p.flight_time, t + config.integration_dt);
        const double march_elapsed = next_t - march_start_t;
        const double mass = p.start_mass_end * std::exp(
            -march_decay * march_elapsed);
        const double fuel_rate = march_decay * mass;
        const double thrust = fuel_rate * config.march_specific_impulse;
        const double march_remaining = std::max(
            0.0, mass - dry_mass) / p.m0;

        t = next_t;
        append_point(t,
                     p.preparation_distance + p.start_distance +
                         v_march * march_elapsed,
                     v_march, mass, fuel_rate, thrust, 0.0,
                     0.0, march_remaining, 2);
    }

    result.success = !result.trajectory.empty();
    result.status = result.success ? "success" : "empty_trajectory";
    return result;
}

void print_bal_simulation_report(
    const BalSimulationConfig& config,
    const BalSimulationResult& result)
{
    if (!result.success)
    {
        std::cout << "Ошибка расчёта прямолинейного полёта: "
                  << result.status << std::endl;
        return;
    }

    const BalMassParameters& p = result.parameters;
    std::cout << "\n=== РАСЧЁТ ПРЯМОЛИНЕЙНОГО ПОЛЁТА ===\n";
    std::cout << "Параметр                         Значение       Единицы\n";
    std::cout << std::fixed << std::setprecision(8);
    std::cout << "Режим подготовки                 "
              << config.preparation_duration << "       с\n"
              << "beta_старт                      " << p.beta_start
              << "       -\n"
              << "beta_марш                       " << p.beta_march
              << "       -\n"
              << "mu_старт                        " << p.mu_start
              << "       -\n"
              << "mu_марш                         " << p.mu_march
              << "       -\n"
              << "mu_марш_лок                     " << p.mu_march_local
              << "       -\n"
              << "mu_сумм                         " << p.mu_summ
              << "       -\n"
              << "eta_0                           " << p.eta_0
              << "       -\n"
              << "Kp (средняя маршевая тяга)      " << p.Kp
              << "       -\n"
              << "Km                              " << p.Km
              << "       -\n"
              << "m0                              " << p.m0
              << "       кг\n"
              << "Масса топлива                  " << p.total_fuel_mass
              << "       кг\n"
              << "q_m0                             " << p.midship_load_start
              << "       Н/м^2\n"
              << "q_m1                             " << p.midship_load_march
              << "       Н/м^2\n"
              << "Площадь миделя                  " << p.midship_area
              << "       м^2\n"
              << "Калибр                          " << p.diameter
              << "       м\n"
              << "Удлинение                       " << p.lambda
              << "       -\n"
              << "Длина ракеты                    " << p.rocket_length
              << "       м\n"
              << "v0                              " << p.v0
              << "       м/с\n"
              << "v_марш                          " << p.v_march
              << "       м/с\n"
              << "Дальность                       " << config.target_range / 1000.0
              << "       км\n"
              << "Время полёта                    " << p.flight_time
              << "       с\n";
    std::cout << "==============================================\n";
}

void save_bal_simulation_outputs(
    const BalSimulationConfig& config,
    const BalSimulationResult& result)
{
    if (!result.success)
        return;

    save_trajectory_file(result.trajectory);
    save_summary_file(config, result);
}
