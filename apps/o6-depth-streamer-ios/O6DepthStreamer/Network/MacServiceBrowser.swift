import Foundation
import Network

struct DiscoveredMacService: Identifiable, Hashable {
    let id: String
    let name: String
    let endpoint: NWEndpoint

    static func == (lhs: Self, rhs: Self) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

@MainActor
final class MacServiceBrowser: ObservableObject {
    @Published private(set) var services: [DiscoveredMacService] = []
    @Published private(set) var isSearching = false
    @Published private(set) var lastError: String?

    private var browser: NWBrowser?

    func start() {
        guard browser == nil else { return }
        let parameters = NWParameters.tcp
        parameters.includePeerToPeer = true
        let browser = NWBrowser(
            for: .bonjour(type: "_o6depth._tcp", domain: nil),
            using: parameters
        )
        self.browser = browser
        isSearching = true
        lastError = nil

        browser.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in
                guard let self else { return }
                switch state {
                case .ready:
                    self.isSearching = true
                case let .failed(error):
                    self.lastError = "Mac 发现失败：\(error.localizedDescription)"
                    self.stop()
                case .cancelled:
                    self.isSearching = false
                default:
                    break
                }
            }
        }
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            let mapped = results.map { result -> DiscoveredMacService in
                let name: String
                if case let .service(serviceName, _, _, _) = result.endpoint {
                    name = serviceName
                } else {
                    name = result.endpoint.debugDescription
                }
                return DiscoveredMacService(
                    id: result.endpoint.debugDescription,
                    name: name,
                    endpoint: result.endpoint
                )
            }.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
            Task { @MainActor in self?.services = mapped }
        }
        browser.start(queue: DispatchQueue(label: "com.duamixu.tailhand.bonjour"))
    }

    func stop() {
        browser?.cancel()
        browser = nil
        isSearching = false
    }

    static func manualEndpoint(host: String, port: String) -> NWEndpoint? {
        let trimmed = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let rawPort = UInt16(port), let nwPort = NWEndpoint.Port(rawValue: rawPort) else {
            return nil
        }
        return .hostPort(host: NWEndpoint.Host(trimmed), port: nwPort)
    }

    deinit {
        browser?.cancel()
    }
}

