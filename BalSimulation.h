#pragma once

#include <string>
#include <vector>

// Входные данные новой идеализированной модели прямолинейного полёта.
// Значения по умолчанию соответствуют формулам из Sources/Прямолинейный полет.md.
struct BalSimulationConfig
{
    double altitude = 8000.0;
    double initial_mach = 0.8;
    double march_mach = 2.0;
    double target_range = 700000.0;

    double start_specific_impulse = 2650.0;
    double march_specific_impulse = 2620.0;
    double start_duration = 5.0;
    double loss_factor = 0.92;
    double mu_summ_limit = 0.7;
    double payload_mass = 225.0;
    double diameter = 0.4;
    double integration_dt = 0.01;
};

// Расчётные массовые и тяговые параметры, выводимые в итоговой таблице.
struct BalMassParameters
{
    double m0 = 0.0;
    double beta = 0.0;

    double mu_start = 0.0;
    double mu_march = 0.0;
    double mu_march_local = 0.0;
    double mu_summ = 0.0;

    double eta_0 = 0.0;
    double Kp = 0.0;
    double Km = 0.0;

    double v0 = 0.0;
    double v_march = 0.0;
    double delta_v_start = 0.0;
    double start_thrust = 0.0;
    double march_thrust = 0.0;
    double start_distance = 0.0;
    double flight_time = 0.0;
};

// Одна точка временного ряда для последующего построения графиков.
struct BalTrajectoryPoint
{
    double t = 0.0;
    double x_g_r = 0.0;
    double y_g_r = 0.0;
    double v_r = 0.0;
    double mach = 0.0;
    double Theta_r = 0.0;
    double n_xa_r = 0.0;
    double n_ya_r = 0.0;
    double fuel_rate = 0.0;
    double fuel_remaining = 0.0;
    double P_r = 0.0;
    double mass_r = 0.0;
    double mu_summ = 0.0;
    double mu_0 = 0.0;
    double mu_1 = 0.0;
    int flight_mode = 0;
};

struct BalSimulationResult
{
    bool success = false;
    std::string status;
    BalMassParameters parameters;
    std::vector<BalTrajectoryPoint> trajectory;
};

// Выполняет массовый расчёт и идеализированное моделирование двух участков.
BalSimulationResult run_bal_simulation(const BalSimulationConfig& config);

// Выводит итоговую таблицу расчётных параметров в консоль.
void print_bal_simulation_report(
    const BalSimulationConfig& config,
    const BalSimulationResult& result);

// Сохраняет данные для существующего Plotly/Excel-процесса визуализации.
void save_bal_simulation_outputs(
    const BalSimulationConfig& config,
    const BalSimulationResult& result);
