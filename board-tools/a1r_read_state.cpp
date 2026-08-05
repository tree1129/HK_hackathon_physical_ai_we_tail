#include "onero_interface_cpp.h"

#include <cstring>
#include <iomanip>
#include <iostream>

int main() {
    onero_api::onero_config_t cfg{};
    std::strncpy(cfg.device, "/dev/ttyACM0", sizeof(cfg.device) - 1);
    std::strncpy(cfg.robot_model, "a1_r", sizeof(cfg.robot_model) - 1);
    std::strncpy(cfg.version, "A1", sizeof(cfg.version) - 1);
    std::strncpy(cfg.mount_orientation, "horizontal",
                 sizeof(cfg.mount_orientation) - 1);

    onero_api::OneroArm arm(cfg);
    if (!arm.valid()) {
        std::cerr << "SDK initialization failed\n";
        return 1;
    }

    std::cout << "SDK initialized (motors remain disabled)\n";
    std::cout << "hardware_connected="
              << (arm.is_hardware_connected() ? "true" : "false") << '\n';

    const auto state = arm.get_arm_state_from_motor();
    if (state.positions.size() != 7 || state.velocities.size() != 7 ||
        state.torques.size() != 7) {
        std::cerr << "No complete 7-joint state received\n";
        return 2;
    }

    std::cout << std::fixed << std::setprecision(6);
    for (std::size_t i = 0; i < 7; ++i) {
        std::cout << "J" << (i + 1) << ": position=" << state.positions[i]
                  << " rad, velocity=" << state.velocities[i]
                  << " rad/s, torque=" << state.torques[i] << " N.m\n";
    }
    return 0;
}
