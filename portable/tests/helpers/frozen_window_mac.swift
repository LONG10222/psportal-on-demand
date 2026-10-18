// Metadata-only probe for a test-owned frozen application's window and normal
// quit. No screenshots, window titles, Accessibility, AppleScript, or permission
// requests. The caller must supply its exact child PID and executable path.
import AppKit
import CoreGraphics
import Darwin
import Foundation

func fail(_ message: String) -> Never {
    fputs(message + "\n", stderr)
    exit(2)
}

let arguments = CommandLine.arguments
guard arguments.count == 4,
      ["inspect", "quit"].contains(arguments[1]),
      let pid = Int32(arguments[2]), pid > 0 else {
    fail("Usage: frozen-window-helper inspect|quit child-pid exact-executable")
}
let expected = URL(fileURLWithPath: arguments[3]).resolvingSymlinksInPath().standardizedFileURL
let application = NSRunningApplication(processIdentifier: pid)
let actual = application?.executableURL?.resolvingSymlinksInPath().standardizedFileURL
let matched = actual == expected

if arguments[1] == "quit" {
    guard matched, let application = application else {
        fail("The test-owned application PID/executable no longer matches")
    }
    guard application.terminate() else {
        fail("The operating system did not accept a normal quit request")
    }
    print("Normal quit requested for verified test-owned application")
    exit(0)
}

var windows: [[String: Any]] = []
if matched {
    // Apple documents this metadata API as non-prompting. Restricted keys such
    // as the window title are deliberately never accessed, even if available.
    guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                              kCGNullWindowID) as? [[String: Any]] else {
        fail("No GUI session/window metadata is available; no permission request was made")
    }
    for window in list {
        guard (window[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid,
              (window[kCGWindowLayer as String] as? NSNumber)?.intValue == 0,
              let bounds = window[kCGWindowBounds as String] as? [String: Any],
              let width = bounds["Width"] as? NSNumber,
              let height = bounds["Height"] as? NSNumber,
              width.doubleValue > 0, height.doubleValue > 0 else { continue }
        windows.append([
            "window_id": (window[kCGWindowNumber as String] as? NSNumber)?.uint32Value ?? 0,
            "width": width.doubleValue,
            "height": height.doubleValue
        ])
    }
}
let result: [String: Any] = ["pid": pid, "executable_matched": matched, "windows": windows]
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
