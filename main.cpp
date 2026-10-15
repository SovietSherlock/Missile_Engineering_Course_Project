#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <cmath>
#include <chrono>
#include <iomanip>
#include <algorithm>
#include <limits>
#include <thread>
#include <mutex>
#include <atomic>

#include "CalcTrajectory.h"
#include "DataStructs.h"
#include "LibConstFunc.h"
#include "KinematicFunc2D.h"
#include "Atm_GOST4401.h"
#include "GuidanceMethods.h"

// ============================================================================
// СТРУКТУРА ДЛЯ ХРАНЕНИЯ УСПЕШНЫХ НАБОРОВ ПАРАМЕТРОВ
// ============================================================================
struct GorkaSuccessParams {
    double m0;
    double mu;
    double beta;
    double eta;
    double Km;
    double Kp;
    double Kg;
    double k;
    double delta_x_virt;
    double rocket_length;
    double t_gorka;
    bool passed_low_evt = false;
    bool passed_high_evt = false;
    double max_range = 0.0;
    double t_low = 0.0;
    double t_high = 0.0;
};

// ============================================================================
// ГЛОБАЛЬНЫЕ СИНХРОНИЗАЦИИ
// ============================================================================
std::mutex g_best_mutex;
std::mutex g_log_mutex;
std::mutex g_gorka_list_mutex;
std::vector<GorkaSuccessParams> g_gorka_success_list;

// ============================================================================
// РАБОЧИЙ ПОТОК: обрабатывает свой чанк mu
// ============================================================================
void worker_thread(
    size_t thread_id,
    size_t num_threads,
    const std::vector<double>& mu_vals,
    const std::vector<double>& eta_vals,
    const std::vector<double>& km_vals,
    const std::vector<double>& kp_vals,
    const std::vector<double>& kg_vals,
    const std::vector<double>& k_vals,
    const RocketParams& rocket_template,
    const CalcParameters& calc,
    const LimitConditions& limits,
    const C_Data& Cdata,
    const N_Data& Ndata,
    const R_Data& Rdata,
    const InitConditions& init_low,
    double range_min_km,
    double range_max_km,
    double range_step_km,
    OptimizeResult& global_best,
    std::atomic<int>& checked,
    std::atomic<int>& base_ok_count,
    std::atomic<int>& high_ok_count,
    std::ofstream& logFile)
{
    // Каждый поток берёт mu с шагом num_threads (чанкирование)
    for (size_t idx = thread_id; idx < mu_vals.size(); idx += num_threads)
    {
        double mu = mu_vals[idx];
        double m_pn = rocket_template.m_pn();
        double m_0 = m_pn / (1.0 - mu);
        double m_t = mu * m_0;
        double beta = 1.0;

        for (int iter = 0; iter < 5; ++iter)
        {
            beta = calculate_beta(rocket_template.d, m_t);
            if (beta * mu >= 1.0) break;
            m_0 = m_pn / (1.0 - beta * mu);
            m_t = mu * m_0;
        }

        if (beta * mu >= 1.0) continue;
        if (m_0 > 650.0) continue;

        const double ROCKET_DENSITY = 1555.0;      // кг/м³
        const double MAX_LENGTH = 4.1;             // м
        double rocket_volume = m_0 / ROCKET_DENSITY;
        double rocket_length = (24.0 * rocket_volume) / (5.0 * M_PI * rocket_template.d * rocket_template.d);

        if (rocket_length > MAX_LENGTH) {
            checked.fetch_add(1, std::memory_order_relaxed);
            continue;
        }

        RocketParams r = rocket_template;
        r.beta = beta;

        for (double eta : eta_vals)
        {
            for (double km : km_vals)
            {
                for (double kp : kp_vals)
                {
                    for (double kg : kg_vals)
                    {
                        for (double k_val : k_vals)
                        {
                            checked.fetch_add(1, std::memory_order_relaxed);

                            GuidanceMethod_Data mtd;
                            mtd.Method = GuidanceMethod::EVT;
                            mtd.k = k_val;
                            mtd.K_g = kg;

                            // === ШАГ 1: БАЗОВЫЙ СЦЕНАРИЙ ===
                            std::vector<TrajectoryParameters> s_low;
                            std::string code_low = CalcTrajectory(
                                calc, init_low, limits,
                                Cdata, Ndata, Rdata,
                                mtd, r,
                                mu, eta, km, kp, kg,
                                s_low);

                            if (code_low != "0" || s_low.empty() || s_low.back().t > limits.t_r_max)
                            {
                                continue;
                            }

                            base_ok_count.fetch_add(1, std::memory_order_relaxed);

                            // === ШАГ 2: ПЕРЕБОР ДАЛЬНОСТЕЙ ===
                            for (double range_km = range_min_km;
                                 range_km <= range_max_km;
                                 range_km += range_step_km)
                            {
                                double range_m = range_km * 1000.0;

                                InitConditions init_high;
                                init_high.x_g_pusk = 0.0;
                                init_high.y_g_pusk = 10000.0;
                                init_high.v_n0 = 270.0;
                                init_high.Theta_n0 = 0.0;
                                init_high.v_r0 = 270.0;
                                init_high.Theta_r0 = std::nan("");
                                init_high.x_g_c0 = range_m;
                                init_high.y_g_c0 = 0.0;
                                init_high.v_c0 = 18.0 * 0.514444;
                                init_high.Theta_c0 = M_PI;

                                std::vector<TrajectoryParameters> s_high;

                                std::string code_high = CalcTrajectory(
                                    calc, init_high, limits,
                                    Cdata, Ndata, Rdata,
                                    mtd, r,
                                    mu, eta, km, kp, kg,
                                    s_high);

                                if (code_high == "0" && !s_high.empty() && s_high.back().t <= limits.t_r_max)
                                {
                                    high_ok_count.fetch_add(1, std::memory_order_relaxed);

                                    // Потокобезопасное логирование
                                    {
                                        std::lock_guard<std::mutex> lock(g_log_mutex);
                                        logFile << "BOTH_OK: m0=" << m_0
                                                << " mu=" << mu << " beta=" << beta
                                                << " eta=" << eta << " Km=" << km
                                                << " Kp=" << kp << " Kg=" << kg << " k=" << k_val
                                                << " R_max=" << range_km
                                                << " t_low=" << s_low.back().t
                                                << " t_high=" << s_high.back().t << "\n";
                                        logFile.flush();
                                    }

                                    // Потокобезопасное обновление лучшего результата
                                    {
                                        std::lock_guard<std::mutex> lock(g_best_mutex);
                                        if (range_km > global_best.max_range)
                                        {
                                            global_best.max_range = range_km;
                                            global_best.m0 = m_0;
                                            global_best.mu = mu;
                                            global_best.beta = beta;
                                            global_best.eta = eta;
                                            global_best.Km = km;
                                            global_best.Kp = kp;
                                            global_best.Kg = kg;
                                            global_best.k = k_val;
                                            global_best.t_high = s_high.back().t;
                                            global_best.r_high = s_high.back().r_rc;
                                            global_best.t_low = s_low.back().t;
                                            global_best.r_low = s_low.back().r_rc;
                                            global_best.valid = true;
                                            global_best.rocket_length = rocket_length;

                                            std::cout << ">>> НОВЫЙ РЕКОРД: дальность=" << range_km
                                                      << " км, m0=" << m_0
                                                      << " mu=" << mu << " beta=" << beta
                                                      << " eta=" << eta << " Km=" << km
                                                      << " Kp=" << kp << " Kg=" << kg << " k=" << k_val
                                                      << " L=" << rocket_length << " м"
                                                      << " t_high=" << s_high.back().t
                                                      << " t_low=" << s_low.back().t << std::endl;
                                        }
                                    }
                                }
                            } // range_km

                            int current = checked.load(std::memory_order_relaxed);
                            if (current % 1000 == 0)
                            {
                                std::lock_guard<std::mutex> lock(g_log_mutex);
                                std::cout << "Прогресс: " << current
                                          << " | Базовых OK: " << base_ok_count.load()
                                          << " | Высоких OK: " << high_ok_count.load()
                                          << " | Рекорд: " << global_best.max_range << " км" << std::endl;
                            }

                        } // k_val
                    } // kg
                } // kp
            } // km
        } // eta
    } // mu (чанк)
}

// ============================================================================
// СТРУКТУРА ДЛЯ ХРАНЕНИЯ РЕЗУЛЬТАТОВ ОПТИМИЗАЦИИ ГОРКА
// ============================================================================
struct GorkaOptimizationResult {
    double range_km;
    double delta_x_virt;
    double t_flight;
    double v_impact;
    double r_final;
    bool success;
    std::string error_code;
};

// ============================================================================
// РЕЗУЛЬТАТЫ ОПТИМИЗАЦИИ МАССЫ ДЛЯ ГОРИЗОНТАЛЬНОГО ПОЛЁТА
// ============================================================================
struct FlatFlightPoint {
    double t = 0.0;
    double x_g_r = 0.0;
    double y_g_r = 0.0;
    double v_r = 0.0;
    double Theta_r = 0.0;
    double n_xa_r = 0.0;
    double fuel_rate = 0.0;
    double fuel_remaining = 0.0;
    double P_r = 0.0;
    double mass_r = 0.0;
    double mu_summ = 0.0;
    double mu_0 = 0.0;
    double mu_1 = 0.0;
};

struct FlatFlightSimulationResult {
    bool reached_range = false;
    double m0 = 0.0;
    double mu_1 = 0.0;
    double beta = 0.0;
    double initial_velocity = 0.0;
    double final_velocity = 0.0;
    double flight_time = 0.0;
    double fuel_remaining = 0.0;
    std::string status;
};

struct FlatFlightOptimizationResult {
    bool valid = false;
    double m0 = 0.0;
    double mu = 0.0;
    double mu_1 = 0.0;
    double beta = 0.0;
    double eta = 0.0;
    double Km = 0.0;
    double Kp = 0.0;
    double Kg = 0.0;
    double k = 0.0;
    double initial_velocity = 0.0;
    double final_velocity = 0.0;
    double flight_time = 0.0;
    double fuel_remaining = 0.0;
    double speed_deficit = std::numeric_limits<double>::max();
};

// Расчёт стартовой массы выполняется по той же зависимости beta(mu),
// которая используется в существующем алгоритме перебора дальности.
bool calculate_flat_flight_mass(
    const RocketParams& rocket,
    double mu,
    double& m0,
    double& beta)
{
    if (!std::isfinite(mu) || mu <= 0.0 || mu >= 1.0 || rocket.d <= 0.0)
        return false;

    const double m_pn = rocket.m_pn();
    m0 = m_pn / (1.0 - mu);
    double m_t = mu * m0;
    beta = 1.0;

    for (int iter = 0; iter < 5; ++iter)
    {
        beta = calculate_beta(rocket.d, m_t);
        if (!std::isfinite(beta) || beta * mu >= 1.0)
            return false;

        m0 = m_pn / (1.0 - beta * mu);
        m_t = mu * m0;
    }

    return std::isfinite(m0) && m0 > 0.0 &&
           std::isfinite(beta) && beta * mu < 1.0;
}

// Специализированное решение уравнения подъёмной силы для горизонтального
// полёта. В отличие от общего find_alpha() используется постоянная n_y = 1,
// поэтому уравнение имеет вид A*alpha + P*sin(alpha) = m*g.
double find_flat_flight_alpha(
    double M,
    double rho,
    double v,
    double d,
    double mass,
    double thrust)
{
    const double alpha_limit = 20.0 * pi / 180.0;
    const double delta_over_alpha = delta_bal_over_alpha(M);
    const double area = S_har(d);
    const double lift_slope =
        (C_y_alpha(M) + C_y_delta(M) * delta_over_alpha) *
        area * rho * v * v / 2.0;
    const double target = mass * g;

    auto residual = [&](double alpha)
    {
        return lift_slope * alpha + thrust * std::sin(alpha) - target;
    };

    double left = -alpha_limit;
    double right = alpha_limit;
    const double residual_left = residual(left);
    const double residual_right = residual(right);
    if (residual_left * residual_right > 0.0)
    {
        return std::abs(residual_left) < std::abs(residual_right)
            ? left
            : right;
    }

    double alpha = target / (lift_slope + thrust);
    if (!std::isfinite(alpha) || alpha <= left || alpha >= right)
        alpha = (left + right) / 2.0;

    // Ньютоновские итерации ускоряют перебор, а ограничение интервалом
    // сохраняет поведение поиска корня в физически допустимой области.
    for (int iter = 0; iter < 8; ++iter)
    {
        const double value = residual(alpha);
        if (std::abs(value) < 1e-6)
            return alpha;

        if (residual_left * value <= 0.0)
            right = alpha;
        else
            left = alpha;

        const double derivative = lift_slope + thrust * std::cos(alpha);
        double next = alpha;
        if (std::isfinite(derivative) && std::abs(derivative) > 1e-12)
            next = alpha - value / derivative;

        if (!std::isfinite(next) || next <= left || next >= right)
            next = (left + right) / 2.0;
        alpha = next;
    }

    return alpha;
}

// Численное моделирование движения при постоянных высоте и угле наклона.
// При theta = 0 для удержания горизонтальной траектории задаётся n_y = 1.
FlatFlightSimulationResult simulate_flat_flight(
    const RocketParams& rocket,
    double mu,
    double eta,
    double km,
    double kp,
    double altitude,
    double target_range,
    double target_velocity,
    double integration_dt,
    std::vector<FlatFlightPoint>* trajectory = nullptr)
{
    FlatFlightSimulationResult result;
    if (trajectory != nullptr)
        trajectory->clear();

    double m0 = 0.0;
    double beta = 0.0;
    if (!calculate_flat_flight_mass(rocket, mu, m0, beta))
    {
        result.status = "invalid_mass_design";
        return result;
    }

    const double atmosphere_height_min = Atm_GOST4401::TablGOST4401.front()[0];
    const double atmosphere_height_max = Atm_GOST4401::TablGOST4401.back()[0];
    if (altitude < atmosphere_height_min || altitude > atmosphere_height_max ||
        target_range <= 0.0 || target_velocity <= 0.0 || integration_dt <= 0.0)
    {
        result.status = "invalid_flight_conditions";
        return result;
    }

    const double rho = Atm_GOST4401::rho_atm(altitude);
    const double speed_of_sound = Atm_GOST4401::a_atm(altitude);
    const double p0 = Atm_GOST4401::p_atm(0.0);
    const double pressure_delta = p0 - Atm_GOST4401::p_atm(altitude);
    const double I_ud = 2650.0;
    const double fuel_epsilon = 1e-12;
    const double angle_ratio_limit = 20.0 * pi / 180.0;
    constexpr double max_start_mass = 650.0;

    if (!std::isfinite(rho) || rho <= 0.0 ||
        !std::isfinite(speed_of_sound) || speed_of_sound <= 0.0)
    {
        result.status = "invalid_atmosphere_data";
        return result;
    }

    result.m0 = m0;
    result.beta = beta;
    result.initial_velocity = 0.8 * speed_of_sound;

    if (m0 >= max_start_mass)
    {
        result.status = "start_mass_limit_exceeded";
        return result;
    }

    double fuel = mu * m0;
    const double dry_mass = m0 - fuel;
    const double fuel_mode_1 = fuel / (1.0 + km);
    const double fuel_mode_2 = fuel - fuel_mode_1;
    const double mu_1 = fuel_mode_2 / m0;
    double x = 0.0;
    double t = 0.0;
    double v = result.initial_velocity;
    result.mu_1 = mu_1;

    if (!std::isfinite(fuel_mode_1) || !std::isfinite(fuel_mode_2) ||
        fuel_mode_1 < 0.0 || fuel_mode_2 < 0.0 || dry_mass <= 0.0)
    {
        result.status = "invalid_fuel_design";
        return result;
    }

    auto append_point = [&](double point_t,
                            double point_x,
                            double point_v,
                            double point_fuel,
                            double point_thrust,
                            double point_fuel_rate,
                            double point_acceleration)
    {
        if (trajectory == nullptr)
            return;

        // В точке траектории point_fuel включает остаток обоих режимов:
        // сначала расходуется топливо стартового режима, а затем маршевого.
        const double fuel_mode_0_remaining = std::max(
            0.0, std::min(fuel_mode_1, point_fuel - fuel_mode_2));
        const double fuel_mode_1_remaining =
            std::min(point_fuel, fuel_mode_2);

        FlatFlightPoint point;
        point.t = point_t;
        point.x_g_r = point_x;
        point.y_g_r = altitude;
        point.v_r = point_v;
        point.Theta_r = 0.0;
        point.n_xa_r = point_acceleration / g;
        point.fuel_rate = point_fuel_rate;
        point.fuel_remaining = point_fuel;
        point.P_r = point_thrust;
        point.mass_r = dry_mass + point_fuel;
        point.mu_summ = point_fuel / m0;
        point.mu_0 = fuel_mode_0_remaining / m0;
        point.mu_1 = fuel_mode_1_remaining / m0;
        trajectory->push_back(point);
    };

    // Ограничение времени предотвращает бесконечный расчёт при потере
    // скорости или при недостижимости заданной дальности.
    constexpr double max_flight_time = 3000.0;
    const std::size_t max_steps = static_cast<std::size_t>(
        std::ceil(max_flight_time / integration_dt));
    for (std::size_t step = 0; step < max_steps; ++step)
    {
        if (t >= max_flight_time)
        {
            result.status = "max_flight_time_exceeded";
            break;
        }

        if (!std::isfinite(v) || v <= 0.0)
        {
            result.status = "speed_nonpositive";
            break;
        }

        const double M = v / speed_of_sound;
        if (!std::isfinite(M) || M < 0.0 || M > 6.0)
        {
            result.status = "speed_limit_exceeding";
            break;
        }

        const double current_mass = dry_mass + fuel;
        const bool mode_1 = fuel > fuel_mode_2 + fuel_epsilon;
        const double tiaga = mode_1 ? eta * m0 * g : eta * m0 * g * kp;
        const double fuel_rate = fuel > fuel_epsilon ? tiaga / I_ud : 0.0;
        const double thrust = fuel > fuel_epsilon
            ? tiaga + pressure_delta * S_a(rocket.d)
            : 0.0;

        // Угол alpha подбирается из условия подъёмной силы, необходимой
        // для компенсации веса при theta = 0.
        const double alpha = find_flat_flight_alpha(
            M, rho, v, rocket.d, current_mass, thrust);
        const double delta = delta_bal_over_alpha(M) * alpha;
        if (!std::isfinite(alpha) || !std::isfinite(delta) ||
            delta - alpha >= angle_ratio_limit)
        {
            result.status = "unvalid_angle_ratio";
            break;
        }

        const double axial_drag = X_a(M, alpha, delta, rho, v, rocket.d, thrust);
        const double acceleration =
            (thrust * std::cos(alpha) - axial_drag) / current_mass;
        if (!std::isfinite(acceleration))
        {
            result.status = "invalid_acceleration";
            break;
        }

        double dt_step = integration_dt;
        if (fuel_rate > fuel_epsilon)
        {
            double time_to_boundary = std::numeric_limits<double>::infinity();
            if (mode_1 && fuel > fuel_mode_2)
                time_to_boundary = (fuel - fuel_mode_2) / fuel_rate;
            else if (!mode_1)
                time_to_boundary = fuel / fuel_rate;

            if (time_to_boundary > fuel_epsilon &&
                time_to_boundary < dt_step)
            {
                dt_step = time_to_boundary;
            }
        }

        append_point(t, x, v, fuel, thrust, fuel_rate, acceleration);

        if (v + acceleration * dt_step <= 0.0)
        {
            result.status = "speed_nonpositive";
            break;
        }

        const double distance_to_target = target_range - x;
        const double distance_full_step =
            v * dt_step + 0.5 * acceleration * dt_step * dt_step;

        if (distance_full_step >= distance_to_target)
        {
            double dt_to_target = dt_step;
            if (std::abs(acceleration) < 1e-12)
            {
                dt_to_target = distance_to_target / v;
            }
            else
            {
                const double discriminant =
                    v * v + 2.0 * acceleration * distance_to_target;
                if (discriminant >= 0.0)
                {
                    dt_to_target =
                        (-v + std::sqrt(discriminant)) / acceleration;
                }
            }

            if (!std::isfinite(dt_to_target) ||
                dt_to_target < 0.0 || dt_to_target > dt_step)
            {
                dt_to_target = dt_step;
            }

            x = target_range;
            t += dt_to_target;
            v += acceleration * dt_to_target;
            fuel = std::max(0.0, fuel - fuel_rate * dt_to_target);
            append_point(t, x, v, fuel, thrust, fuel_rate, acceleration);

            result.reached_range = true;
            result.final_velocity = v;
            result.flight_time = t;
            result.fuel_remaining = fuel;
            result.status = "target_range_reached";
            return result;
        }

        x += distance_full_step;
        t += dt_step;
        v += acceleration * dt_step;
        fuel = std::max(0.0, fuel - fuel_rate * dt_step);
    }

    if (result.status.empty())
        result.status = "max_steps_exceeded";
    result.final_velocity = v;
    result.flight_time = t;
    result.fuel_remaining = fuel;
    return result;
}

void save_flat_flight_trajectory(
    const std::vector<FlatFlightPoint>& trajectory)
{
    std::ofstream file("flat_flight_trajectory.gra");
    file << "t\tx_g_r\ty_g_r\tv_r\tTheta_r\tn_xa_r"
         << "\tfuel_rate\tfuel_remaining\tP_r\tmass_r"
         << "\tmu_summ\tmu_0\tmu_1\n";

    file << std::setprecision(12);
    for (const FlatFlightPoint& point : trajectory)
    {
        file << point.t << "\t"
             << point.x_g_r << "\t"
             << point.y_g_r << "\t"
             << point.v_r << "\t"
             << point.Theta_r << "\t"
             << point.n_xa_r << "\t"
             << point.fuel_rate << "\t"
             << point.fuel_remaining << "\t"
             << point.P_r << "\t"
             << point.mass_r << "\t"
             << point.mu_summ << "\t"
             << point.mu_0 << "\t"
             << point.mu_1 << "\n";
    }
}

FlatFlightOptimizationResult optimize_minimum_mass_flat_flight(
    const RocketParams& rocket)
{
    constexpr double altitude = 8000.0;
    constexpr double target_range = 315'000.0;
    constexpr double target_velocity = 700.0;
    constexpr double range_tolerance = 100.0;
    constexpr double max_start_mass = 650.0;
    constexpr double coarse_velocity_window = 10.0;
    constexpr double scan_dt = 0.5;
    constexpr double validation_dt = 0.01;

    // Сетка параметров совпадает с сеткой существующего алгоритма
    // оптимизации максимальной дальности.
    std::vector<double> mu_vals;
    for (double mu = 0.44; mu <= 0.6501; mu += 0.01)
        mu_vals.push_back(mu);

    // std::vector<double> eta_vals = {6.0, 8.0, 10.0, 12.0, 14.0,
    //                                 16.0, 18.0, 20.0, 22.0, 24.0};
    std::vector<double> eta_vals = {1.5, 2.0, 3.0, 4.0, 5.0, 6.0};
    // std::vector<double> km_vals = {10.0, 12.0, 14.0, 16.0,
    //                                18.0, 20.0, 22.0};
    std::vector<double> km_vals = {4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 14.0};
    std::vector<double> kp_vals = {0.25, 0.30, 0.35, 0.40, 0.45, 0.50};
    std::vector<double> kg_vals = {1.05, 1.1, 1.2, 1.3, 1.4, 1.5,
                                   1.6, 1.7, 1.8, 1.9, 2.0};
    std::vector<double> k_vals = {1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0};

    const std::size_t total_combinations =
        mu_vals.size() * eta_vals.size() * km_vals.size() *
        kp_vals.size() * kg_vals.size() * k_vals.size();

    std::ofstream result_file("flat_flight_mass_optimization.txt", std::ios::app);
    result_file << "\n=== FLAT FLIGHT MINIMUM MASS OPTIMIZATION START ===\n";
    result_file << "Altitude_m=" << altitude
                << " Range_m=" << target_range
                << " Initial_Mach=0.8"
                << " Target_velocity_m_s=" << target_velocity << "\n";
    result_file << "Range_tolerance_m=" << range_tolerance
                << " Minimum_velocity_m_s=" << target_velocity
                << " Maximum_start_mass_strict_m0_kg=" << max_start_mass << "\n";
    result_file << "m0\tmu\tmu_1\tbeta\teta\tKm\tKp\tKg\tk"
                << "\tv0\tv_final\tt_flight\tfuel_remaining\tstatus\n";

    FlatFlightOptimizationResult best;
    FlatFlightOptimizationResult closest;
    std::size_t checked_combinations = 0;
    std::size_t simulated_designs = 0;
    std::size_t feasible_combinations = 0;

    auto assign_result = [](FlatFlightOptimizationResult& destination,
                            const FlatFlightSimulationResult& simulation,
                            double mu, double eta, double km, double kp,
                            double kg, double k)
    {
        destination.valid = true;
        destination.m0 = simulation.m0;
        destination.mu = mu;
        destination.mu_1 = simulation.mu_1;
        destination.beta = simulation.beta;
        destination.eta = eta;
        destination.Km = km;
        destination.Kp = kp;
        destination.Kg = kg;
        destination.k = k;
        destination.initial_velocity = simulation.initial_velocity;
        destination.final_velocity = simulation.final_velocity;
        destination.flight_time = simulation.flight_time;
        destination.fuel_remaining = simulation.fuel_remaining;
        destination.speed_deficit = std::max(
            0.0, target_velocity - simulation.final_velocity);
    };

    for (double mu : mu_vals)
    {
        for (double eta : eta_vals)
        {
            for (double km : km_vals)
            {
                for (double kp : kp_vals)
                {
                    FlatFlightSimulationResult simulation =
                        simulate_flat_flight(
                            rocket, mu, eta, km, kp,
                            altitude, target_range, target_velocity, scan_dt);
                    ++simulated_designs;

                    // Уточняем только близкие к целевой скорости решения,
                    // чтобы не снижать скорость полного перебора сетки.
                    if (simulation.reached_range &&
                        simulation.final_velocity >=
                            target_velocity - coarse_velocity_window)
                    {
                        simulation = simulate_flat_flight(
                            rocket, mu, eta, km, kp,
                            altitude, target_range, target_velocity,
                            validation_dt);
                    }

                    for (double kg : kg_vals)
                    {
                        for (double k : k_vals)
                        {
                            ++checked_combinations;
                            if (!simulation.reached_range)
                                continue;

                            const double speed_deficit = std::max(
                                0.0, target_velocity - simulation.final_velocity);
                            if (speed_deficit < closest.speed_deficit)
                            {
                                assign_result(closest, simulation,
                                              mu, eta, km, kp, kg, k);
                            }

                            // Kg и k не входят в уравнения горизонтального
                            // полёта: нормальная перегрузка задана условием
                            // удержания высоты n_y = 1. Они всё же проходят
                            // через общую сетку параметров проекта.
                            if (simulation.final_velocity >= target_velocity)
                            {
                                ++feasible_combinations;
                                if (!best.valid || simulation.m0 < best.m0)
                                {
                                    assign_result(best, simulation,
                                                  mu, eta, km, kp, kg, k);
                                    result_file << std::setprecision(10)
                                                << simulation.m0 << "\t"
                                                << mu << "\t" << simulation.mu_1 << "\t"
                                                << simulation.beta << "\t"
                                                << eta << "\t" << km << "\t"
                                                << kp << "\t" << kg << "\t"
                                                << k << "\t"
                                                << simulation.initial_velocity << "\t"
                                                << simulation.final_velocity << "\t"
                                                << simulation.flight_time << "\t"
                                                << simulation.fuel_remaining << "\tOK\n";
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    result_file << "=== FLAT FLIGHT MINIMUM MASS OPTIMIZATION DONE ===\n";
    result_file << "Simulated designs: " << simulated_designs << "\n";
    result_file << "Checked grid combinations: " << checked_combinations
                << "/" << total_combinations << "\n";
    result_file << "Feasible combinations: " << feasible_combinations << "\n";
    result_file.close();

    std::vector<FlatFlightPoint> best_trajectory;
    if (best.valid)
    {
        FlatFlightSimulationResult detailed_result = simulate_flat_flight(
            rocket, best.mu, best.eta, best.Km, best.Kp,
            altitude, target_range, target_velocity,
            validation_dt, &best_trajectory);

        if (detailed_result.reached_range)
        {
            best.initial_velocity = detailed_result.initial_velocity;
            best.final_velocity = detailed_result.final_velocity;
            best.flight_time = detailed_result.flight_time;
            best.fuel_remaining = detailed_result.fuel_remaining;
            save_flat_flight_trajectory(best_trajectory);
        }
    }

    std::cout << "\n========================================" << std::endl;
    std::cout << "=== ОПТИМИЗАЦИЯ МИНИМАЛЬНОЙ МАССЫ: ГОРИЗОНТАЛЬНЫЙ ПОЛЁТ ==="
              << std::endl;
    std::cout << "Высота: " << altitude << " м" << std::endl;
    std::cout << "Дальность: " << target_range / 1000.0 << " км"
              << " (допуск " << range_tolerance << " м)" << std::endl;
    std::cout << "Начальная скорость: 0.8 Маха" << std::endl;
    std::cout << "Минимальная конечная скорость: " << target_velocity
              << " м/с" << std::endl;
    std::cout << "Ограничение стартовой массы: m0 < " << max_start_mass
              << " кг" << std::endl;
    std::cout << "Проверено комбинаций сетки: " << checked_combinations
              << "/" << total_combinations << std::endl;
    std::cout << "Подходящих комбинаций: " << feasible_combinations << std::endl;

    if (best.valid)
    {
        std::cout << "\n=== МИНИМАЛЬНАЯ СТАРТОВАЯ МАССА ===" << std::endl;
        std::cout << "m0 = " << best.m0 << " кг" << std::endl;
        std::cout << "mu = " << best.mu << ", mu_1 = " << best.mu_1
                  << ", beta = " << best.beta << std::endl;
        constexpr double rocket_density = 1555.0;
        const double rocket_length =
            (24.0 * best.m0) /
            (5.0 * pi * rocket.d * rocket.d * rocket_density);
        std::cout << "Длина ракеты = " << rocket_length << " м" << std::endl;
        std::cout << "Калибр (диаметр) = " << rocket.d << " м ("
                  << rocket.d * 1000.0 << " мм)" << std::endl;
        std::cout << "eta = " << best.eta << ", Km = " << best.Km
                  << ", Kp = " << best.Kp << std::endl;
        std::cout << "Kg = " << best.Kg << ", k = " << best.k << std::endl;
        std::cout << "V0 = " << best.initial_velocity << " м/с"
                  << ", V_final = " << best.final_velocity << " м/с"
                  << ", t = " << best.flight_time << " с" << std::endl;
        std::cout << "Остаток топлива = " << best.fuel_remaining << " кг"
                  << std::endl;
        std::cout << "График временных рядов: flat_flight_trajectory.gra"
                  << std::endl;
    }
    else if (closest.valid)
    {
        std::cout << "\nРешение в заданном допуске не найдено." << std::endl;
        std::cout << "Ближайший результат: m0 = " << closest.m0
                  << " кг, V_final = " << closest.final_velocity
                  << " м/с, недобор = " << closest.speed_deficit << " м/с"
                  << std::endl;
    }
    else
    {
        std::cout << "\nРасчётных траекторий, достигших 700 км, не найдено."
                  << std::endl;
    }
    std::cout << "========================================" << std::endl;

    return best;
}

// ============================================================================
// АЛГОРИТМ ОПТИМИЗАЦИИ ДЛЯ МАНЕВРА GORKA С ПЕРЕБОРОМ ДАЛЬНОСТЕЙ
// ============================================================================
std::vector<GorkaOptimizationResult> optimize_gorka_ranges(
    const RocketParams& rocket,
    const CalcParameters& calc,
    const LimitConditions& limits,
    const C_Data& Cdata,
    const N_Data& Ndata,
    const R_Data& Rdata,
    const InitConditions& init_Gorka,
    double mu, double eta, double km, double kp, double kg, double k,
    double range_start_km,
    double range_end_km,
    double range_step_km,
    const std::vector<double>& delta_x_virt_vals)
{
    std::vector<GorkaOptimizationResult> results;
    
    // Настройка метода Gorka с фиксированными параметрами
    GuidanceMethod_Data mtd_gorka;
    mtd_gorka.Method = GuidanceMethod::Gorka;
    mtd_gorka.K_H_march = 0.35;
    mtd_gorka.K_v_march = 0.38;
    mtd_gorka.K_H_gorka = 0.23;
    mtd_gorka.K_v_gorka = 0.40;
    mtd_gorka.H_march = 5.5;
    mtd_gorka.H_gorka = 200.0;
    mtd_gorka.r_save = 5000.0;
    mtd_gorka.k_dive = 4.0;
    mtd_gorka.H_save = 0.5;
    mtd_gorka.H_ant = 30.0;
    mtd_gorka.k = k;
    mtd_gorka.K_g = kg;
    
    std::cout << "\n========================================" << std::endl;
    std::cout << "=== ОПТИМИЗАЦИЯ МАНЕВРА GORKA ===" << std::endl;
    std::cout << "Фиксированные параметры:" << std::endl;
    std::cout << "  m0 = " << rocket.m0_start << " кг" << std::endl;
    std::cout << "  mu = " << mu << std::endl;
    std::cout << "  beta = " << rocket.beta << std::endl;
    std::cout << "  eta = " << eta << std::endl;
    std::cout << "  Km = " << km << std::endl;
    std::cout << "  Kp = " << kp << std::endl;
    std::cout << "  Kg = " << kg << std::endl;
    std::cout << "  k = " << k << std::endl;
    std::cout << "Диапазон дальностей: " << range_start_km << " - " << range_end_km << " км, шаг " << range_step_km << " км" << std::endl;
    std::cout << "Перебор delta_x_virt: ";
    for (double dx : delta_x_virt_vals) std::cout << dx/1000.0 << " ";
    std::cout << " км" << std::endl;
    std::cout << "========================================" << std::endl;
    
    // Открываем лог-файл
    std::ofstream logFile("gorka_optimization.txt", std::ios::app);
    logFile << "\n=== GORKA OPTIMIZATION (FIXED PARAMS) ===\n";
    logFile << "m0=" << rocket.m0_start << ", mu=" << mu << ", beta=" << rocket.beta 
            << ", eta=" << eta << ", Km=" << km << ", Kp=" << kp 
            << ", Kg=" << kg << ", k=" << k << std::endl;
    logFile << "Range_km\tdelta_x_virt_km\tt_flight\tv_impact\tr_final\tStatus" << std::endl;
    logFile.flush();
    
    int total_combinations = static_cast<int>(
        ((range_end_km - range_start_km) / range_step_km + 1) * delta_x_virt_vals.size()
    );
    int checked = 0;
    int success_count = 0;
    
    std::cout << "\nНачало перебора... (всего " << total_combinations << " комбинаций)" << std::endl;
    
    for (double range_km = range_start_km; range_km <= range_end_km; range_km += range_step_km)
    {
        double range_m = range_km * 1000.0;
        
        // Обновляем начальные условия для текущей дальности
        InitConditions init_current = init_Gorka;
        init_current.x_g_c0 = range_m;
        
        for (double dx_val : delta_x_virt_vals)
        {
            checked++;
            
            // Устанавливаем delta_x_virt
            mtd_gorka.delta_x_virt = dx_val;
            
            std::vector<TrajectoryParameters> s_gorka;
            std::string code = CalcTrajectory(
                calc, init_current, limits,
                Cdata, Ndata, Rdata,
                mtd_gorka, rocket,
                mu, eta, km, kp, kg,
                s_gorka);
            
            GorkaOptimizationResult result;
            result.range_km = range_km;
            result.delta_x_virt = dx_val;
            result.success = false;
            result.error_code = code;
            
            if (code == "0" && !s_gorka.empty() && s_gorka.back().t <= limits.t_r_max)
            {
                result.success = true;
                result.t_flight = s_gorka.back().t;
                result.v_impact = s_gorka.back().v_r;
                result.r_final = s_gorka.back().r_rc;
                success_count++;
                
                // Вывод в консоль
                std::cout << "  R_Gorka = " << std::fixed << std::setprecision(1) << range_km 
                          << " км, delta_x_virt = " << std::setprecision(1) << dx_val/1000.0 
                          << " км, t = " << std::setprecision(2) << result.t_flight 
                          << " с, V = " << std::setprecision(1) << result.v_impact 
                          << " м/с, r_final = " << std::setprecision(1) << result.r_final << " м" << std::endl;
                
                // Запись в лог-файл
                logFile << std::fixed << std::setprecision(1) << range_km << "\t"
                        << std::setprecision(1) << dx_val/1000.0 << "\t"
                        << std::setprecision(2) << result.t_flight << "\t"
                        << std::setprecision(1) << result.v_impact << "\t"
                        << std::setprecision(1) << result.r_final << "\tOK\n";
                logFile.flush();
            }
            else
            {
                // Запись неудачных попыток в лог (опционально)
                logFile << std::fixed << std::setprecision(1) << range_km << "\t"
                        << std::setprecision(1) << dx_val/1000.0 << "\t"
                        << "-\t-\t-\tFAIL(" << code << ")\n";
            }
            
            results.push_back(result);
            
            // Прогресс
            if (checked % 10 == 0 || checked == total_combinations)
            {
                std::cout << "Прогресс: " << checked << "/" << total_combinations 
                          << " | Успешно: " << success_count << std::endl;
            }
        }
    }
    
    logFile << "\n=== DONE ===\n";
    logFile << "Total checked: " << checked << "\n";
    logFile << "Successful: " << success_count << "\n";
    logFile.close();
    
    // Вывод статистики
    std::cout << "\n========================================" << std::endl;
    std::cout << "=== СТАТИСТИКА ОПТИМИЗАЦИИ GORKA ===" << std::endl;
    std::cout << "Всего проверено комбинаций: " << checked << std::endl;
    std::cout << "Успешных: " << success_count << std::endl;
    
    // Находим максимальную дальность
    double max_range = 0.0;
    double max_dx = 0.0;
    double max_t = 0.0;
    double max_v = 0.0;
    
    for (const auto& r : results) {
        if (r.success && r.range_km > max_range) {
            max_range = r.range_km;
            max_dx = r.delta_x_virt;
            max_t = r.t_flight;
            max_v = r.v_impact;
        }
    }
    
    if (max_range > 0) {
        std::cout << "\n=== ЛУЧШИЙ РЕЗУЛЬТАТ ===" << std::endl;
        std::cout << "Максимальная дальность Gorka: " << max_range << " км" << std::endl;
        std::cout << "  delta_x_virt = " << max_dx/1000.0 << " км" << std::endl;
        std::cout << "  Время полета = " << max_t << " с" << std::endl;
        std::cout << "  Скорость подлета = " << max_v << " м/с" << std::endl;
    }
    std::cout << "========================================" << std::endl;
    
    return results;
}


// ============================================================================
// ФУНКЦИЯ ВЫВОДА РЕЗУЛЬТАТОВ ОПТИМИЗАЦИИ GORKA В ТАБЛИЦЕ
// ============================================================================
void print_gorka_results_table(const std::vector<GorkaOptimizationResult>& results) {
    if (results.empty()) {
        std::cout << "\nНет результатов для отображения." << std::endl;
        return;
    }
    
    std::cout << "\n=== ТАБЛИЦА РЕЗУЛЬТАТОВ GORKA ===" << std::endl;
    std::cout << std::setw(12) << "R, км" 
              << std::setw(18) << "dx_virt, км"
              << std::setw(12) << "t, с"
              << std::setw(12) << "V, м/с"
              << std::setw(12) << "r_final, м"
              << std::setw(10) << "Status" << std::endl;
    std::cout << std::string(76, '-') << std::endl;
    
    // Сортируем по дальности
    auto sorted = results;
    std::sort(sorted.begin(), sorted.end(),
        [](const GorkaOptimizationResult& a, const GorkaOptimizationResult& b) {
            return a.range_km < b.range_km;
        });
    
    for (const auto& r : sorted) {
        std::cout << std::setw(12) << std::fixed << std::setprecision(1) << r.range_km
                  << std::setw(18) << std::setprecision(1) << r.delta_x_virt/1000.0;
        
        if (r.success) {
            std::cout << std::setw(12) << std::setprecision(2) << r.t_flight
                      << std::setw(12) << std::setprecision(1) << r.v_impact
                      << std::setw(12) << std::setprecision(1) << r.r_final
                      << std::setw(10) << "OK";
        } else {
            std::cout << std::setw(12) << "-"
                      << std::setw(12) << "-"
                      << std::setw(12) << "-"
                      << std::setw(10) << r.error_code;
        }
        std::cout << std::endl;
    }
}

// ============================================================================
// ОСНОВНАЯ ФУНКЦИЯ ОПТИМИЗАЦИИ (распараллеленная)
// ============================================================================
OptimizeResult optimize_max_range_parallel(
    const RocketParams& rocket_template,
    const CalcParameters& calc,
    const LimitConditions& limits,
    const C_Data& Cdata,
    const N_Data& Ndata,
    const R_Data& Rdata,
    const InitConditions& init_low,
    double range_min_km,
    double range_max_km,
    double range_step_km)
{
    OptimizeResult global_best;
    global_best.valid = false;
    global_best.max_range = 0.0;

    // === СЕТКА ПАРАМЕТРОВ ===
    std::vector<double> mu_vals;
    for (double mu = 0.44; mu <= 0.6501; mu += 0.01)
        mu_vals.push_back(mu);

    std::vector<double> eta_vals = {1.0, 1.5, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0};
    std::vector<double> km_vals = {4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 14.0};
    // std::vector<double> km_vals = {10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0};
    std::vector<double> kp_vals = {0.25, 0.30, 0.35, 0.40, 0.45, 0.50};
    std::vector<double> kg_vals = {1.05, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0};
    std::vector<double> k_vals = {1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0};

    int total_combinations = static_cast<int>(
        mu_vals.size() * eta_vals.size() * km_vals.size() *
        kp_vals.size() * kg_vals.size() * k_vals.size()
    );

    std::atomic<int> checked{0};
    std::atomic<int> base_ok_count{0};
    std::atomic<int> high_ok_count{0};

    std::ofstream logFile("optimization.txt", std::ios::app);
    logFile << "\n=== OPTIMIZATION (MAX RANGE) PARALLEL START ===\n";
    logFile << "Threads: 16\n";
    logFile << "Total param combinations: " << total_combinations << "\n";
    logFile << "Base scenario: 0.2 km, 120 m/s, 150 km\n";
    logFile << "Range scan: " << range_min_km << "-" << range_max_km << " km, step " << range_step_km << "\n";
    logFile << "Mass limit: m0 <= 650 kg\n";
    logFile << "Rocket length limit: <= 4.1 m (density 1555 kg/m³)\n";
    logFile << "Grid: mu[0.44:0.02:0.70] (outer loop), eta[6:18], Km[1:5], Kp[0.25:0.05:0.80], Kg[1.05:0.1:2.0], k[3:10]\n";
    logFile.flush();

    std::cout << "=== НАЧАЛО ОПТИМИЗАЦИИ (16 потоков) ===" << std::endl;
    std::cout << "Всего комбинаций параметров: " << total_combinations << std::endl;
    std::cout << "Базовый сценарий: 0.2 km, 120 m/s, 150 km" << std::endl;
    std::cout << "Перебор дальностей: " << range_min_km << "-" << range_max_km << " км" << std::endl;
    std::cout << "Ограничение по массе: m0 <= 650 кг" << std::endl;
    std::cout << "μ — внешний цикл (чанкирование по потокам)" << std::endl;
    std::cout << std::endl;

    const size_t num_threads = 16;
    std::vector<std::thread> threads;

    for (size_t t = 0; t < num_threads; ++t)
    {
        threads.emplace_back(worker_thread,
                             t, num_threads,
                             std::cref(mu_vals),
                             std::cref(eta_vals),
                             std::cref(km_vals),
                             std::cref(kp_vals),
                             std::cref(kg_vals),
                             std::cref(k_vals),
                             std::cref(rocket_template),
                             std::cref(calc),
                             std::cref(limits),
                             std::cref(Cdata),
                             std::cref(Ndata),
                             std::cref(Rdata),
                             std::cref(init_low),
                             range_min_km, range_max_km, range_step_km,
                             std::ref(global_best),
                             std::ref(checked),
                             std::ref(base_ok_count),
                             std::ref(high_ok_count),
                             std::ref(logFile));
    }

    for (auto& t : threads)
        t.join();

    logFile << "\n=== DONE ===\n";
    logFile << "Checked: " << checked.load() << "/" << total_combinations << "\n";
    logFile << "Base OK: " << base_ok_count.load() << " High OK: " << high_ok_count.load() << "\n";
    logFile.close();

    std::cout << "\n========================================" << std::endl;
    std::cout << "ОПТИМИЗАЦИЯ ЗАВЕРШЕНА" << std::endl;
    std::cout << "Проверено комбинаций: " << checked.load() << "/" << total_combinations << std::endl;
    std::cout << "Успешных базовых: " << base_ok_count.load() << std::endl;
    std::cout << "Успешных высоких: " << high_ok_count.load() << std::endl;

    if (global_best.valid)
    {
        std::cout << "\n=== ЛУЧШИЙ РЕЗУЛЬТАТ ===" << std::endl;
        std::cout << "Максимальная дальность: " << global_best.max_range << " км" << std::endl;
        std::cout << "m0 = " << global_best.m0 << " кг" << std::endl;
        std::cout << "mu = " << global_best.mu << std::endl;
        std::cout << "beta = " << global_best.beta << std::endl;
        std::cout << "eta = " << global_best.eta << std::endl;
        std::cout << "Km = " << global_best.Km << std::endl;
        std::cout << "Kp = " << global_best.Kp << std::endl;
        std::cout << "Kg = " << global_best.Kg << std::endl;
        std::cout << "k = " << global_best.k << std::endl;
        std::cout << "t_low = " << global_best.t_low << " с" << std::endl;
        std::cout << "t_high = " << global_best.t_high << " с" << std::endl;
        std::cout << "Длина ракеты = " << global_best.rocket_length << " м" << std::endl;
    }
    else
    {
        std::cout << "\nРешение не найдено!" << std::endl;
    }
    std::cout << "========================================" << std::endl;

    return global_best;
}
// ============================================================================
// ФУНКЦИЯ ПОСТ-ОБРАБОТКИ С СОЗДАНИЕМ ФАЙЛА РАДИОГОРИЗОНТА
// ============================================================================
void run_and_save(
    const std::string& case_name,
    const CalcParameters& calc,
    const LimitConditions& limits,
    const C_Data& Cdata,
    const N_Data& Ndata,
    const R_Data& Rdata,
    const InitConditions& init,
    GuidanceMethod_Data method,
    const RocketParams& rocket,
    double mu, double eta, double km, double kp, double kg)
{
    std::vector<TrajectoryParameters> result;
    std::string code = CalcTrajectory(
        calc, init, limits,
        Cdata, Ndata, Rdata,
        method, rocket,
        mu, eta, km, kp, kg,
        result);

    std::cout << "[" << case_name << "] Результат: " << code << std::endl;
    if (!result.empty())
    {
        std::cout << "  Время полета: " << result.back().t << " с" << std::endl;
        std::cout << "  Конечная дальность: " << result.back().x_g_r << " м" << std::endl;
        std::cout << "  Конечная высота: " << result.back().y_g_r << " м" << std::endl;
        std::cout << "  Конечная скорость: " << result.back().v_r << " м/с" << std::endl;
    }

    // === Сохранение в файлы ===
    std::ofstream C_File(case_name + "_C.gra");
    std::ofstream N_File(case_name + "_N.gra");
    std::ofstream R_File(case_name + "_R.gra");
    std::ofstream Kinematic_File(case_name + "_Kinematic.gra");
    std::ofstream Horizon_File(case_name + "_Horizon.gra"); // Файл радиогоризонта

    // Заголовки
    C_File << "t\tTheta_c\tv_c\tx_g_c\ty_g_c\tn_xa_c\tn_ya_c";
    N_File << "t\tTheta_n\tv_n\tx_g_n\ty_g_n\tn_xa_n\tn_ya_n";
    R_File << "t\tTheta_r\tv_r\tx_g_r\ty_g_r\tn_xa_r\tn_ya_r\tn_y_max\tmass_r\tP_r\talpha_r\tdelta_r\talpha_residual";
    Kinematic_File << "t\tr_rc\tdot_r_rc\tepsilon_rc\tdot_epsilon_rc"
                   << "\tr_nr\tdot_r_nr\tepsilon_nr\tdot_epsilon_nr"
                   << "\tr_nc\tdot_r_nc\tepsilon_nc\tdot_epsilon_nc";
    Horizon_File << "t\ty_g_r\tr_rc\ty_radar_horizon\tis_visible";

    for (size_t i = 0; i < result.size(); i++)
    {
        N_File << "\n" << result[i].t << "\t" << result[i].Theta_n << "\t"
               << result[i].v_n << "\t" << result[i].x_g_n << "\t"
               << result[i].y_g_n << "\t" << result[i].n_xa_n << "\t"
               << result[i].n_ya_n;

        R_File << "\n" << result[i].t << "\t" << result[i].Theta_r << "\t"
               << result[i].v_r << "\t" << result[i].x_g_r << "\t"
               << result[i].y_g_r << "\t" << result[i].n_xa_r << "\t"
               << result[i].n_ya_r << "\t" << result[i].n_y_max << "\t"
               << result[i].mass_r << "\t"
               << result[i].P_r << "\t" << result[i].alpha_r << "\t"
               << result[i].delta_r << "\t" << result[i].alpha_residual;

        C_File << "\n" << result[i].t << "\t" << result[i].Theta_c << "\t"
               << result[i].v_c << "\t" << result[i].x_g_c << "\t"
               << result[i].y_g_c << "\t" << result[i].n_xa_c << "\t"
               << result[i].n_ya_c;

        Kinematic_File << "\n" << result[i].t << "\t"
                       << result[i].r_rc << "\t" << result[i].dot_r_rc << "\t"
                       << result[i].epsilon_rc << "\t" << result[i].dot_epsilon_rc << "\t"
                       << result[i].r_nr << "\t" << result[i].dot_r_nr << "\t"
                       << result[i].epsilon_nr << "\t" << result[i].dot_epsilon_nr << "\t"
                       << result[i].r_nc << "\t" << result[i].dot_r_nc << "\t"
                       << result[i].epsilon_nc << "\t" << result[i].dot_epsilon_nc;

        // Запись данных радиогоризонта
        Horizon_File << "\n" << result[i].t << "\t"
                     << result[i].y_g_r << "\t"
                     << result[i].r_rc << "\t";
        
        if (result[i].y_radar_horizon.has_value()) {
            Horizon_File << result[i].y_radar_horizon.value() << "\t1";
        } else {
            Horizon_File << "-1\t0";
        }
    }

    C_File.close();
    N_File.close();
    R_File.close();
    Kinematic_File.close();
    Horizon_File.close();

    std::cout << "  Файлы сохранены: " << case_name << "_*.gra" << std::endl;
    std::cout << "  Файл радиогоризонта: " << case_name << "_Horizon.gra" << std::endl;
}

// ============================================================================
// MAIN
// ============================================================================
int main()
{
    C_Data Cdata;
    N_Data Ndata;
    R_Data Rdata;

    Cdata.n_xa_c_potr = {{0.0, 0.0}, {10.0, 0.0}};
    Cdata.n_ya_c_potr = {{0.0, -1.0}, {10.0, -1.0}};

    Ndata.n_xa_n_potr = {{0.0, 0.0}, {10.0, 0.0}};
    Ndata.n_ya_n_potr = {{0.0, 1.0}, {10.0, 1.0}};

    Rdata.n_xa_r_potr = {{0.0, 0.0}, {10.0, 0.0}};

    RocketParams rocket;
    rocket.m_bch = 150.0;
    rocket.m_oun = 65.0;
    rocket.m_np  = 11.0;
    rocket.d     = 0.400;
    rocket.beta  = 1.14128; // ИЗМЕНИТЬ
    
    // Расчет m0_start для корректной работы
    double m_pn = rocket.m_pn();
    double mu_fixed = 0.53; // ИЗМЕНИТЬ
    rocket.m0_start = m_pn / (1.0 - rocket.beta * mu_fixed);

    // === ОПТИМИЗАЦИЯ МИНИМАЛЬНОЙ МАССЫ ДЛЯ ГОРИЗОНТАЛЬНОГО ПОЛЁТА ===
    optimize_minimum_mass_flat_flight(rocket);

    CalcParameters calc;
    calc.dt = 0.01;
    calc.r_por = 15.0;

    LimitConditions limits;
    limits.n_ya_r_max = 40.0;
    limits.t_r_min = 2.0;
    limits.t_r_max = 600.0;
    limits.R_r_min = std::nan("");
    limits.R_r_max = std::nan("");
    limits.y_g_r_min = 0.0;
    limits.y_g_r_max = std::nan("");
    limits.epsilon_nc_min = std::nan("");
    limits.epsilon_nc_max = std::nan("");

    InitConditions init_low;
    init_low.Theta_c0 = M_PI;
    init_low.v_c0 = 18.0 * 0.514444;
    init_low.x_g_c0 = 150000.0; // ИЗМЕНИТЬ
    init_low.y_g_c0 = 0.0;
    init_low.Theta_n0 = 0.0;
    init_low.v_n0 = 120.0;
    init_low.x_g_pusk = 0.0;
    init_low.y_g_pusk = 200.0;
    init_low.Theta_r0 = std::nan("");
    init_low.v_r0 = init_low.v_n0;

    InitConditions init_high;
    init_high.x_g_pusk = 0.0;
    init_high.y_g_pusk = 10000.0; 
    init_high.v_n0 = 270.0;
    init_high.Theta_n0 = 0.0;
    init_high.v_r0 = 270.0;
    init_high.Theta_r0 = std::nan("");
    init_high.x_g_c0 = 550000.0; // ИЗМЕНИТЬ
    init_high.y_g_c0 = 0.0;
    init_high.v_c0 = 18.0 * 0.514444;
    init_high.Theta_c0 = M_PI;

    InitConditions init_Gorka;
    init_Gorka.Theta_c0 = M_PI;
    init_Gorka.v_c0 = 18.0 * 0.514444;
    init_Gorka.x_g_c0 =50000.0; // ИЗМЕНИТЬ
    init_Gorka.y_g_c0 = 0.0;
    init_Gorka.Theta_n0 = 0.0;
    init_Gorka.v_n0 = 120.0;
    init_Gorka.x_g_pusk = 0.0;
    init_Gorka.y_g_pusk = 200.0;
    init_Gorka.Theta_r0 = std::nan("");
    init_Gorka.v_r0 = init_Gorka.v_n0;

    GuidanceMethod_Data method;
    method.Method = GuidanceMethod::EVT;
    method.k = 3.0; // ИЗМЕНИТЬ
    method.K_g = 1.8; // ИЗМЕНИТЬ

    // === 1. ЗАПУСК ОПТИМИЗАЦИИ (закомментирован, так как параметры уже найдены) ===
    
    // OptimizeResult result = optimize_max_range_parallel(
    //     rocket, calc, limits,
    //     Cdata, Ndata, Rdata,
    //     init_low,
    //     400.0,
    //     550.0,
    //     10.0
    // );


    // BOTH_OK: m0=515.099 mu=0.49 beta=1.14541 eta=6 Km=3 Kp=0.25 Kg=1.9 k=3.5 R_max=700 t_low=277.35 t_high=544.93
    // BOTH_OK: m0=515.099 mu=0.49 beta=1.14541 eta=6 Km=5 Kp=0.25 Kg=2 k=5 R_max=800 t_low=394.68 t_high=507.4 +++
    // m0=642.965 mu=0.57 beta=1.13773 eta=6 Km=5 Kp=0.25 Kg=1.5 k=5 R_max=1040 t_low=460.51 t_high=596.33

    // BOTH_OK: m0=571.973 mu=0.53 beta=1.14128 eta=6 Km=1 Kp=0.25 Kg=1.8 k=3 R_max=550 t_low=245.679 t_high=257.889

    // === ПАРАМЕТРЫ ===
    double mu = 0.53; // ИЗМЕНИТЬ
    double eta = 6.0; // ИЗМЕНИТЬ
    double Km = 1.0; // ИЗМЕНИТЬ
    double Kp = 0.25; // ИЗМЕНИТЬ
    double Kg = 1.8; // ИЗМЕНИТЬ
    double k = 3.0; // ИЗМЕНИТЬ

    // ===  ОПТИМИЗАЦИЯ GORKA С ПЕРЕБОРОМ ДАЛЬНОСТЕЙ ===

    // std::vector<double> delta_x_virt_vals = {
    //     10000.0, 15000.0, 20000.0, 25000.0, 30000.0, 35000.0, 40000.0, 45000.0, 
    //     50000.0, 55000.0, 60000.0, 65000.0, 70000.0, 75000.0, 80000.0, 85000.0, 90000.0
    // };

    // std::vector<GorkaOptimizationResult> gorka_results = optimize_gorka_ranges(
    //     rocket, calc, limits,
    //     Cdata, Ndata, Rdata,
    //     init_Gorka,
    //     mu, eta, Km, Kp, Kg, k,
    //     20.0,
    //     100.0,
    //     10,
    //     delta_x_virt_vals
    // );

    // // === ВЫВОД ТАБЛИЦЫ РЕЗУЛЬТАТОВ ===
    // print_gorka_results_table(gorka_results);

    // // === СОХРАНЕНИЕ ТРАЕКТОРИЙ ДЛЯ ЛУЧШИХ РЕЗУЛЬТАТОВ ===
    // // Находим лучший результат
    // double best_range = 0.0;
    // double best_dx = 0.0;
    // for (const auto& r : gorka_results) {
    //     if (r.success && r.range_km > best_range) {
    //         best_range = r.range_km;
    //         best_dx = r.delta_x_virt;
    //     }
    // }

    // === 1. НИЗКОВЫСОТНЫЙ СЦЕНАРИЙ (EVT) ===
    // method.Method = GuidanceMethod::EVT;
    // run_and_save("Best_low", calc, limits,
    //              Cdata, Ndata, Rdata, init_low,
    //              method, rocket,
    //              mu, eta, Km, Kp, Kg);

    // // === 2. ВЫСОКОВЫСОТНЫЙ СЦЕНАРИЙ (EVT) ===
    // method.Method = GuidanceMethod::EVT;
    // run_and_save("Best_high", calc, limits,
    //              Cdata, Ndata, Rdata, init_high,
    //              method, rocket,
    //              mu, eta, Km, Kp, Kg);

    // // === 3. МЕТОД ГОРКИ (GORKA) ===
    // method.Method = GuidanceMethod::Gorka;
    // method.K_H_march = 0.35;
    // method.K_v_march = 0.38;
    // method.K_H_gorka = 0.23;
    // method.K_v_gorka = 0.40;
    // method.H_march = 5.5;
    // method.H_gorka = 200.0;
    // method.r_save = 5000.0;
    // method.k_dive = 4.0;
    // method.H_save = 0.5;
    // method.H_ant = 30.0;
    // method.delta_x_virt = 10000.0; // ИЗМЕНИТЬ
    // method.k = 3.0;
    // method.K_g = 1.8;

    // run_and_save("Best_gorka", calc, limits,
    //              Cdata, Ndata, Rdata, init_Gorka,
    //              method, rocket,
    //              mu, eta, Km, Kp, Kg);

    // return 0;
}
