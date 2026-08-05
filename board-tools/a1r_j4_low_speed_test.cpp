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
    if (arm.enable_motors() != 0) {
        std::cerr << "Enable failed\n";
        return 2;
    }

    const auto before = arm.get_arm_state_from_motor();
    if (before.positions.size() != 7) {
        std::cerr << "No complete joint state\n";
        return 3;
    }

    auto target = before.positions;
    target[3] += 0.05;
    std::cout << std::fixed << std::setprecision(6)
              << "TEST_START J4=" << before.positions[3]
              << " target=" << target[3] << std::endl;

    int rc = arm.movej(target, 0.1, 0);
    if (rc != 0) {
        std::cerr << "Outbound move failed, rc=" << rc << '\n';
        return 4;
    }
    std::cout << "OUTBOUND_OK" << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(1));

    rc = arm.movej(before.positions, 0.1, 0);
    if (rc != 0) {
        std::cerr << "Return move failed, rc=" << rc << '\n';
        return 5;
    }
    const auto after = arm.get_arm_state_from_motor();
    std::cout << "RETURN_OK" << std::endl;
    if (after.positions.size() == 7) {
        std::cout << "J4_FINAL=" << after.positions[3] << std::endl;
    }
    std::cout << "TEST_COMPLETE_MOTORS_HELD" << std::endl;

    while (running) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
        if (!arm.is_hardware_connected())
            std::cerr << "HARDWARE_CONNECTION_LOST" << std::endl;
    }
    return 0;
}
