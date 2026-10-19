// SPDX-License-Identifier: GPL-3.0-only
import Foundation
#if compiler(>=6.2)
import BackgroundTasks
#endif

@MainActor
protocol BackgroundSharingDriver: AnyObject {
    var available: Bool { get }
    func begin(minutes: Int, granted: @escaping (Date) -> Void, ended: @escaping (String) -> Void)
    func finish(success: Bool)
}

@MainActor
final class UnavailableBackgroundSharing: BackgroundSharingDriver {
    var available: Bool { false }
    func begin(minutes: Int, granted: @escaping (Date) -> Void, ended: @escaping (String) -> Void) {
        ended("Background sharing requires iOS 26+ on a real device.")
    }
    func finish(success: Bool) {}
}

@MainActor
func makeBackgroundSharingDriver() -> BackgroundSharingDriver {
#if compiler(>=6.2) && !targetEnvironment(simulator)
    if #available(iOS 26.0, *) { return SystemBackgroundSharing() }
#endif
    return UnavailableBackgroundSharing()
}

#if compiler(>=6.2)
@available(iOS 26.0, *)
@MainActor
final class SystemBackgroundSharing: BackgroundSharingDriver {
    var available: Bool { true }
    private var identifier: String?
    private var task: BGContinuedProcessingTask?
    private var timer: Task<Void, Never>?

    func begin(minutes: Int, granted: @escaping (Date) -> Void, ended: @escaping (String) -> Void) {
        finish(success: false)
        let id = (Bundle.main.bundleIdentifier ?? "org.psportal.host.foreground") + ".sharing." + UUID().uuidString
        identifier = id
        let registered = BGTaskScheduler.shared.register(forTaskWithIdentifier: id, using: .main) { [weak self] incoming in
            // Scheduler callbacks are delivered on the main queue selected above.
            MainActor.assumeIsolated {
                guard let self, self.identifier == id,
                      let continued = incoming as? BGContinuedProcessingTask else {
                    incoming.setTaskCompleted(success: false)
                    return
                }
                self.timer?.cancel()
                self.task = continued
                let seconds = max(1, min(minutes, 60)) * 60
                let deadline = Date().addingTimeInterval(TimeInterval(seconds))
                continued.progress.totalUnitCount = Int64(seconds)
                continued.progress.completedUnitCount = 0
                continued.expirationHandler = { [weak self] in
                    Task { @MainActor in
                        guard self?.identifier == id else { return }
                        ended("Background sharing was ended by the system. Start again in the app.")
                    }
                }
                granted(deadline)
                self.timer = Task { @MainActor [weak self] in
                    while !Task.isCancelled {
                        do { try await Task.sleep(nanoseconds: 1_000_000_000) } catch { return }
                        guard let self, self.identifier == id else { return }
                        let remaining = max(0, Int(ceil(deadline.timeIntervalSinceNow)))
                        continued.progress.completedUnitCount = Int64(seconds - remaining)
                        if remaining == 0 {
                            ended("The timed background sharing session finished. Start again in the app.")
                            return
                        }
                    }
                }
            }
        }
        guard registered else {
            finish(success: false)
            ended("Background sharing was not granted. Keep the app open.")
            return
        }
        let request = BGContinuedProcessingTaskRequest(identifier: id, title: "StarPass", subtitle: "Timed LAN sharing · \(minutes) min")
        request.strategy = .fail
        do {
            try BGTaskScheduler.shared.submit(request)
            // Submission is not permission to continue. A missing handler must
            // never leave the UI claiming that a background session is active.
            timer = Task { @MainActor [weak self] in
                do { try await Task.sleep(nanoseconds: 5_000_000_000) } catch { return }
                guard let self, self.identifier == id, self.task == nil else { return }
                self.finish(success: false)
                ended("Background sharing was not granted. Keep the app open.")
            }
        } catch {
            finish(success: false)
            ended("Background sharing was not granted. Keep the app open.")
        }
    }

    func finish(success: Bool) {
        timer?.cancel(); timer = nil
        let previous = identifier
        identifier = nil
        if let previous { BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: previous) }
        task?.setTaskCompleted(success: success)
        task = nil
    }
}
#endif
