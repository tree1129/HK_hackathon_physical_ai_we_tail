#include <cstdlib>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include "asr_service.h"

int main() {
    SpacemiT::AsrConfig config = SpacemiT::AsrConfig::Preset("sensevoice");
    config.language = "auto";
    config.punctuation = true;
    config.provider = "spacemit";
    config.hotwords = {"挥手", "复位", "摇尾巴", "握手", "挠背", "招手", "点位遍历"};
    config.hotword_boost = 3.0f;

    auto engine = std::make_shared<SpacemiT::AsrEngine>(config);
    if (!engine->IsInitialized()) return 1;

    // Warm up with the same 2-second shape used by the capture loop so the
    // first real command does not pay a one-time accelerator compilation cost.
    std::vector<float> silence(32000, 0.0f);
    engine->Recognize(silence, 16000);
    std::cout << "READY" << std::endl;

    std::string path;
    while (std::getline(std::cin, path)) {
        if (path.empty()) continue;
        auto result = engine->Call(path);
        std::cout << "RESULT\t";
        if (result && !result->IsEmpty()) std::cout << result->GetText();
        std::cout << std::endl;
    }
    return 0;
}
