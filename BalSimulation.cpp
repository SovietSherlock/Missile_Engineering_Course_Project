#include "BalSimulation.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>

#include "Atm_GOST4401.h"
#include "LibConstFunc.h"

namespace
{
constexpr double fuel_epsilon = 1e-12;

bool finite_positive(double value)
{
    return std::isfinite(value) && value > 0.0;
}

// Итерационное решение зависимости стартовой массы от beta и суммарной
// относительной массы топлива. Формула beta берётся из действующей модели
// проекта, а относительные массы участков — из нового исходного файла.
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

    if (!finite_positive(config.payload_mass) ||
        !finite_positive(config.diameter) ||
        !finite_positive(config.start_specific_impulse) ||
        !finite_positive(config.march_specific_impulse) ||
        !finite_positive(config.start_duration) ||
        !finite_positive(config.loss_factor) ||
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

    if (parameters.mu_march <= 0.0 || parameters.mu_start <= 0.0)
        return false;

    parameters.mu_march_local =
        parameters.mu_march / (1.0 - parameters.mu_start);
    parameters.Km = parameters.mu_march / parameters.mu_start;

    double m0 = config.payload_mass / (1.0 - parameters.mu_summ);
    double beta = 1.0;
    for (int iteration = 0; iteration < 20; ++iteration)
    {
        const double fuel_mass = parameters.mu_summ * m0;
        beta = calculate_beta(config.diameter, fuel_mass);
        if (!finite_positive(beta) || beta * parameters.mu_summ >= 1.0)
            return false;

        const double updated_m0 = config.payload_mass /
            (1.0 - beta * parameters.mu_summ);
        if (std::abs(updated_m0 - m0) < 1e-10)
        {
            m0 = updated_m0;
            break;
        }
        m0 = updated_m0;
    }

    parameters.m0 = m0;
    parameters.beta = beta;
    parameters.eta_0 =
        parameters.delta_v_start / config.start_duration / g;
    parameters.start_thrust = parameters.eta_0 * parameters.m0 * g;
    return finite_positive(parameters.m0) && finite_positive(parameters.beta);
}

void save_trajectory_file(const std::vector<BalTrajectoryPoint>& trajectory)
{
    std::ofstream file("flat_flight_trajectory.gra");
    file << "t\tx_g_r\ty_g_r\tv_r\tmach\tTheta_r\tn_xa_r\tn_ya_r"
         << "\tfuel_rate\tfuel_remaining\tP_r\tmass_r"
         << "\tmu_summ\tmu_0\tmu_1\tflight_mode\n";
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
             << point.flight_mode << "\n";
    }
}

void save_summary_file(
    const BalSimulationConfig& config,
    const BalSimulationResult& result)
{
    const BalMassParameters& p = result.parameters;
    const double rocket_density = 1555.0;
    const double rocket_length =
        (24.0 * p.m0) /
        (5.0 * pi * config.diameter * config.diameter * rocket_density);

    std::ofstream file("flat_flight_summary.tsv");
    file << "Показатель\tЗначение\tЕдиницы\n";
    file << std::setprecision(12)
         << "m0\t" << p.m0 << "\tкг\n"
         << "mu_summ\t" << p.mu_summ << "\t-\n"
         << "mu_0 (стартовое топливо)\t" << p.mu_start << "\t-\n"
         << "mu_1 (маршевое топливо)\t" << p.mu_march << "\t-\n"
         << "mu_1_local\t" << p.mu_march_local << "\t-\n"
         << "eta_0\t" << p.eta_0 << "\t-\n"
         << "Kp\t" << p.Kp << "\t-\n"
         << "Km\t" << p.Km << "\t-\n"
         << "beta\t" << p.beta << "\t-\n"
         << "Длина ракеты\t" << rocket_length << "\tм\n"
         << "Калибр\t" << config.diameter << "\tм\n"
         << "v0\t" << p.v0 << "\tм/с\n"
         << "v_march\t" << p.v_march << "\tм/с\n"
         << "Дальность\t" << config.target_range << "\tм\n"
         << "Время полёта\t" << p.flight_time << "\tс\n";
}
}

BalSimulationResult run_bal_simulation(const BalSimulationConfig& config)
{
    BalSimulationResult result;

    const double speed_of_sound = Atm_GOST4401::a_atm(config.altitude);
    if (!finite_positive(speed_of_sound) ||
        !finite_positive(config.integration_dt) ||
        !finite_positive(config.target_range) ||
        config.target_range < 700000.0)
    {
        result.status = "invalid_flight_conditions";
        return result;
    }

    const double v0 = config.initial_mach * speed_of_sound;
    const double v_march = config.march_mach * speed_of_sound;
    if (!calculate_mass_parameters(config, v0, v_march, result.parameters))
    {
        result.status = "invalid_mass_parameters";
        return result;
    }

    BalMassParameters& p = result.parameters;
    p.start_distance = v0 * config.start_duration +
        0.5 * (p.delta_v_start / config.start_duration) *
        config.start_duration * config.start_duration;

    const double march_distance = config.target_range - p.start_distance;
    if (march_distance <= 0.0)
    {
        result.status = "invalid_target_range";
        return result;
    }

    const double march_time = march_distance / v_march;
    const double total_fuel_mass = p.mu_summ * p.m0;
    const double march_fuel_mass = p.mu_march * p.m0;
    const double march_fuel_rate = march_fuel_mass / march_time;
    p.march_thrust = march_fuel_rate * config.march_specific_impulse;
    p.Kp = p.march_thrust / p.start_thrust;
    p.flight_time = config.start_duration + march_time;

    const double dry_mass = p.m0 - total_fuel_mass;
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
        point.fuel_rate = fuel_rate;
        point.fuel_remaining = std::max(0.0, mass - dry_mass);
        point.P_r = thrust;
        point.mass_r = mass;
        point.mu_summ = point.fuel_remaining / p.m0;
        point.mu_0 = std::max(0.0, mu_start_remaining);
        point.mu_1 = std::max(0.0, mu_march_remaining);
        point.flight_mode = mode;
        result.trajectory.push_back(point);
    };

    // Стартовый участок моделируется с постоянным средним ускорением,
    // заданным формулой из исходного документа. Масса изменяется по
    // экспоненциальной зависимости Циолковского.
    double t = 0.0;
    append_point(t, 0.0, v0, p.m0,
                 p.m0 * start_acceleration / effective_start_exhaust_velocity,
                 p.start_thrust, p.eta_0, p.mu_start, p.mu_march, 0);

    while (t < config.start_duration - fuel_epsilon)
    {
        const double next_t = std::min(
            config.start_duration, t + config.integration_dt);
        const double elapsed = next_t;
        const double velocity = v0 + start_acceleration * elapsed;
        const double mass = p.m0 * std::exp(
            -(velocity - v0) / effective_start_exhaust_velocity);
        const double fuel = std::max(0.0, mass - dry_mass);
        const double start_remaining =
            std::max(0.0, fuel - march_fuel_mass) / p.m0;
        const double fuel_rate = mass * start_acceleration /
            effective_start_exhaust_velocity;

        t = next_t;
        append_point(t,
                     v0 * t + 0.5 * start_acceleration * t * t,
                     velocity, mass, fuel_rate,
                     mass * start_acceleration,
                     p.eta_0, start_remaining, p.mu_march, 0);
    }

    // На маршевом участке скорость и высота постоянны. Маршевая тяга
    // определяется расходом всей рассчитанной маршевой массы топлива за
    // время прохождения оставшейся дальности.
    const double march_start_t = config.start_duration;
    while (t < p.flight_time - fuel_epsilon)
    {
        const double next_t = std::min(p.flight_time, t + config.integration_dt);
        const double march_elapsed = next_t - march_start_t;
        const double march_fraction = std::clamp(
            1.0 - march_elapsed / march_time, 0.0, 1.0);
        const double march_remaining = p.mu_march * march_fraction;
        const double fuel = march_remaining * p.m0;
        const double mass = dry_mass + fuel;

        t = next_t;
        append_point(t,
                     p.start_distance + v_march * march_elapsed,
                     v_march, mass, march_fuel_rate, p.march_thrust,
                     0.0, 0.0, march_remaining, 1);
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
    const double rocket_density = 1555.0;
    const double rocket_length =
        (24.0 * p.m0) /
        (5.0 * pi * config.diameter * config.diameter * rocket_density);
    std::cout << "\n=== РАСЧЁТ ПРЯМОЛИНЕЙНОГО ПОЛЁТА ===\n";
    std::cout << "Параметр                         Значение       Единицы\n";
    std::cout << std::fixed << std::setprecision(8);
    std::cout << "mu_старт                        " << p.mu_start << "       -\n"
              << "mu_марш                         " << p.mu_march << "       -\n"
              << "mu_марш_лок                     " << p.mu_march_local << "       -\n"
              << "mu_сумм                         " << p.mu_summ << "       -\n"
              << "eta_0                           " << p.eta_0 << "       -\n"
              << "Kp                              " << p.Kp << "       -\n"
              << "Km                              " << p.Km << "       -\n"
              << "beta                            " << p.beta << "       -\n"
              << "m0                              " << p.m0 << "       кг\n"
              << "Длина ракеты                    " << rocket_length << "       м\n"
              << "Калибр                          " << config.diameter << "       м\n"
              << "v0                              " << p.v0 << "       м/с\n"
              << "v_марш                          " << p.v_march << "       м/с\n"
              << "Дальность                       " << config.target_range / 1000.0 << "       км\n"
              << "Время полёта                    " << p.flight_time << "       с\n";
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
