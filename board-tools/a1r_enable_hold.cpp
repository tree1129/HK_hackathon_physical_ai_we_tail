#include "onero_interface_cpp.h"

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstring>
#include <iomanip>
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

    const int rc = arm.enable_motors();
    if (rc != 0) {
        std::cerr << "enable_motors failed, rc=" << rc << '\n';
        return 2;
    }

    std::cout << "MOTORS_ENABLED" << std::endl;
    const auto state = arm.get_arm_state_from_motor();
    if (state.positions.size() == 7) {
        std::cout << std::fixed << std::setprecision(6) << "positions=";
        for (std::size_t i = 0; i < state.positions.size(); ++i) {
            if (i) std::cout << ',';
            std::cout << state.positions[i];
        }
        std::cout << std::endl;
    }

    while (running) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
        if (!arm.is_hardware_connected()) {
            std::cerr << "HARDWARE_CONNECTION_LOST" << std::endl;
        }
    }

    // Do not call disable_motors here: this arm has no brakes and is wall-mounted.
    std::cout << "CONTROL_SESSION_ENDED_WITHOUT_DISABLE" << std::endl;
    return 0;
}
