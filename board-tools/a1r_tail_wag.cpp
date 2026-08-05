#include "onero_interface_cpp.h"

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstring>
#include <iostream>
#include <thread>

namespace {
std::atomic<bool> running{true};
void stop_handler(int) { running = false; }
}

int main() {
    std::signal(SIGINT, stop_handler);
    std::signal(SIGTERM, stop_handler);

    onero_api::onero_config_t cfg{};
    std::strncpy(cfg.device, "/dev/ttyACM0", sizeof(cfg.device) - 1);
    std::strncpy(cfg.robot_model, "a1_r", sizeof(cfg.robot_model) - 1);
    std::strncpy(cfg.version, "A1", sizeof(cfg.version) - 1);
    std::strncpy(cfg.mount_orientation, "horizontal",
                 sizeof(cfg.mount_orientation) - 1);

    onero_api::OneroArm arm(cfg);
    if (!arm.valid() || !arm.is_hardware_connected()) {
        std::cerr << "Hardware connection failed\n";
        return 1;
    }
    if (arm.enable_motors() != 0) {
        std::cerr << "Enable failed\n";
        return 2;
    }

    const auto state = arm.get_arm_state_from_motor();
    if (state.positions.size() != 7) {
        std::cerr << "No complete joint state\n";
        return 3;
    }

    const auto center = state.positions;
    auto left = center;
    auto right = center;
    left[3] += 0.10;
    left[5] -= 0.14;
    right[3] -= 0.10;
    right[5] += 0.14;

    constexpr double speed = 0.15;
    for (int cycle = 1; cycle <= 3; ++cycle) {
        std::cout << "WAG " << cycle << " LEFT" << std::endl;
        int rc = arm.movej(left, speed, 0);
        if (rc != 0) {
            std::cerr << "Left move failed, rc=" << rc << '\n';
            arm.movej(center, 0.10, 0);
            return 4;
        }
        std::cout << "WAG " << cycle << " RIGHT" << std::endl;
        rc = arm.movej(right, speed, 0);
        if (rc != 0) {
            std::cerr << "Right move failed, rc=" << rc << '\n';
            arm.movej(center, 0.10, 0);
            return 5;
        }
    }

    std::cout << "RETURN_CENTER" << std::endl;
    const int rc = arm.movej(center, 0.10, 0);
    if (rc != 0) {
        std::cerr << "Center return failed, rc=" << rc << '\n';
        return 6;
    }
    std::cout << "TAIL_WAG_COMPLETE_MOTORS_HELD" << std::endl;

    while (running) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
        if (!arm.is_hardware_connected())
            std::cerr << "HARDWARE_CONNECTION_LOST" << std::endl;
    }
    return 0;
}
