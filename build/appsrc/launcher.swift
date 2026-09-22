import Cocoa

// ============================================================
//  MicroFish — native macOS launcher (menu-bar app)
//
//  Responsibilities:
//    * First-run setup: copy bundled source into the per-user
//      Application Support folder and create the Python venv via uv.
//    * Run the Flask backend (:5001) and the UI static server (:3000)
//      from the venv Python — no Node.js required at runtime.
//    * Provide a menu-bar status item, a native API-keys settings
//      window, and clean shutdown of the child servers.
// ============================================================

let home = NSHomeDirectory()
let appSupport = (home as NSString).appendingPathComponent("Library/Application Support/MicroFish")
let logsDir = (appSupport as NSString).appendingPathComponent("logs")
let envPath = (appSupport as NSString).appendingPathComponent(".env")
let markerPath = (appSupport as NSString).appendingPathComponent(".setup_done")
let backendDir = (appSupport as NSString).appendingPathComponent("backend")
let distDir = (appSupport as NSString).appendingPathComponent("frontend/dist")
let venvPython = (backendDir as NSString).appendingPathComponent(".venv/bin/python")
let serveScript = (appSupport as NSString).appendingPathComponent("serve_dist.py")
let backendLog = (logsDir as NSString).appendingPathComponent("backend.log")
let uiLog = (logsDir as NSString).appendingPathComponent("ui.log")
let launcherLog = (logsDir as NSString).appendingPathComponent("launcher.log")
let uiURL = "http://localhost:3000"
let healthURL = "http://127.0.0.1:5001/health"

// MARK: - Filesystem + logging helpers

func ensureDir(_ path: String) {
    try? FileManager.default.createDirectory(atPath: path, withIntermediateDirectories: true)
}

func timestamp() -> String {
    let df = DateFormatter()
    df.dateFormat = "yyyy-MM-dd HH:mm:ss"
    return df.string(from: Date())
}

func appendLog(_ message: String) {
    ensureDir(logsDir)
    let line = "[\(timestamp())] " + message + "\n"
    guard let data = line.data(using: .utf8) else { return }
    if FileManager.default.fileExists(atPath: launcherLog),
       let handle = try? FileHandle(forWritingTo: URL(fileURLWithPath: launcherLog)) {
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: data)
        try? handle.close()
    } else {
        try? data.write(to: URL(fileURLWithPath: launcherLog))
    }
    print(line, terminator: "")
}

// MARK: - Process / environment helpers

func fullEnv() -> [String: String] {
    var env = ProcessInfo.processInfo.environment
    let extra = [
        "/usr/local/bin",
        "/opt/homebrew/bin",
        (home as NSString).appendingPathComponent(".local/bin"),
        (home as NSString).appendingPathComponent(".cargo/bin"),
        "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    ]
    let existing = env["PATH"] ?? "/usr/bin:/bin"
    env["PATH"] = extra.joined(separator: ":") + ":" + existing
    return env
}

@discardableResult
func runCapture(_ launchPath: String, _ arguments: [String], _ cwd: String?, _ env: [String: String]?) -> Int32 {
    let process = Process()
    process.launchPath = launchPath
    process.arguments = arguments
    if let env = env { process.environment = env }
    if let cwd = cwd { process.currentDirectoryPath = cwd }
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = pipe
    do {
        try process.run()
        process.waitUntilExit()
    } catch {
        appendLog("run error \(launchPath): \(error)")
        return -1
    }
    return process.terminationStatus
}

func findTool(_ name: String) -> String? {
    let candidates = [
        (home as NSString).appendingPathComponent(".local/bin/" + name),
        (home as NSString).appendingPathComponent(".cargo/bin/" + name),
        "/opt/homebrew/bin/" + name,
        "/usr/local/bin/" + name,
        "/usr/bin/" + name,
    ]
    for candidate in candidates where FileManager.default.isExecutableFile(atPath: candidate) {
        return candidate
    }
    let process = Process()
    process.launchPath = "/usr/bin/env"
    process.arguments = ["which", name]
    process.environment = fullEnv()
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = pipe
    do {
        try process.run()
        process.waitUntilExit()
    } catch {
        return nil
    }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    let resolved = (String(data: data, encoding: .utf8) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    if process.terminationStatus == 0,
       resolved.contains("/"),
       FileManager.default.isExecutableFile(atPath: resolved) {
        return resolved
    }
    return nil
}

func ensureUvAndSync() -> Bool {
    if FileManager.default.isExecutableFile(atPath: venvPython) { return true }
    appendLog("Creating Python environment via uv...")
    var uv = findTool("uv") ?? ""
    if uv.isEmpty {
        appendLog("uv not found; installing from astral.sh...")
        let installer = (NSTemporaryDirectory() as NSString).appendingPathComponent("uv_install.sh")
        guard runCapture("/usr/bin/curl", ["-fsSL", "https://astral.sh/uv/install.sh", "-o", installer], nil, nil) == 0 else {
            appendLog("ERROR: failed to download uv installer")
            return false
        }
        _ = runCapture("/bin/sh", [installer], NSTemporaryDirectory(), fullEnv())
        uv = findTool("uv") ?? ""
    }
    guard !uv.isEmpty else { appendLog("ERROR: uv could not be located/installed"); return false }
    guard runCapture(uv, ["sync"], backendDir, fullEnv()) == 0,
          FileManager.default.isExecutableFile(atPath: venvPython) else {
        appendLog("ERROR: uv sync failed or did not create the Python environment")
        return false
    }
    return true
}

// MARK: - Setup

func doSetup() {
    ensureDir(appSupport)
    ensureDir(logsDir)
    if FileManager.default.fileExists(atPath: markerPath) {
        appendLog("Setup already complete.")
        return
    }
    appendLog("First-run setup: copying bundled source into Application Support...")
    let resourcePath = Bundle.main.resourcePath ?? ""
    let bundledSrc = (resourcePath as NSString).appendingPathComponent("microfish-src")
    if FileManager.default.fileExists(atPath: bundledSrc) {
        let srcDot = (bundledSrc as NSString).appendingPathComponent(".")
        _ = runCapture("/bin/cp", ["-R", srcDot, appSupport + "/"], nil, nil)
    } else {
        appendLog("WARNING: bundled microfish-src not found at \(bundledSrc)")
    }

    if !FileManager.default.fileExists(atPath: envPath) {
        let template = (appSupport as NSString).appendingPathComponent(".env.example")
        if FileManager.default.fileExists(atPath: template) {
            try? FileManager.default.copyItem(atPath: template, toPath: envPath)
        } else {
            let defaults = """
            # MicroFish settings — add your API keys here.
            LLM_API_KEY=your_api_key_here
            LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
            LLM_MODEL_NAME=qwen-plus
            ZEP_API_KEY=your_zep_api_key_here
            """
            try? defaults.write(toFile: envPath, atomically: true, encoding: .utf8)
        }
    }

    for relative in ["backend/uploads", "backend/app/uploads/projects", "backend/app/uploads/simulations"] {
        ensureDir((appSupport as NSString).appendingPathComponent(relative))
    }

    guard ensureUvAndSync() else {
        appendLog("Setup failed; will retry on next launch.")
        return
    }
    try? "done".write(toFile: markerPath, atomically: true, encoding: .utf8)
    appendLog("Setup complete.")
}

// MARK: - App delegate

final class AppDelegate: NSObject, NSApplicationDelegate {

    let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    var backendProc: Process?
    var uiProc: Process?
    var settingsWindow: NSWindow?
    var fields: [String: NSTextField] = [:]
    let settingsKeys = ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_NAME", "ZEP_API_KEY"]

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu(running: false)
        DispatchQueue.global(qos: .userInitiated).async { self.boot() }
    }

    func applicationWillTerminate(_ notification: Notification) { stopAll() }

    // MARK: Boot / lifecycle

    func boot() {
        doSetup()
        startBackend()
        let backendOK = waitHealthy(url: healthURL, timeout: 150)
        appendLog(backendOK ? "Backend healthy." : "Backend did not become healthy in time.")
        startUI()
        let uiOK = waitHealthy(url: uiURL, timeout: 60)
        appendLog(uiOK ? "UI healthy." : "UI did not become healthy in time.")
        DispatchQueue.main.async { self.buildMenu(running: backendOK && uiOK) }
        openBrowser()
    }

    func redirect(_ process: Process, to path: String) {
        ensureDir(logsDir)
        if !FileManager.default.fileExists(atPath: path) {
            FileManager.default.createFile(atPath: path, contents: nil)
        }
        if let handle = try? FileHandle(forWritingTo: URL(fileURLWithPath: path)) {
            _ = try? handle.seekToEnd()
            process.standardOutput = handle
            process.standardError = handle
        }
    }

    func startBackend() {
        stopProcess(&backendProc, port: 5001)
        guard FileManager.default.isExecutableFile(atPath: venvPython) else {
            appendLog("Cannot start backend: venv python missing at \(venvPython)")
            return
        }
        let process = Process()
        process.launchPath = venvPython
        process.arguments = ["run.py"]
        process.currentDirectoryPath = backendDir
        var env = fullEnv()
        env["FLASK_DEBUG"] = "False"
        env["FLASK_HOST"] = "127.0.0.1"
        env["FLASK_PORT"] = "5001"
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        redirect(process, to: backendLog)
        do {
            try process.run()
            backendProc = process
            appendLog("Backend started (pid \(process.processIdentifier)).")
        } catch {
            appendLog("Backend start error: \(error)")
        }
    }

    func startUI() {
        stopProcess(&uiProc, port: 3000)
        guard FileManager.default.isExecutableFile(atPath: venvPython) else { return }
        guard FileManager.default.fileExists(atPath: serveScript) else {
            appendLog("Cannot start UI: \(serveScript) missing")
            return
        }
        let process = Process()
        process.launchPath = venvPython
        process.arguments = [serveScript, "--dir", distDir, "--port", "3000", "--host", "127.0.0.1"]
        process.currentDirectoryPath = appSupport
        var env = fullEnv()
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        redirect(process, to: uiLog)
        do {
            try process.run()
            uiProc = process
            appendLog("UI server started (pid \(process.processIdentifier)).")
        } catch {
            appendLog("UI start error: \(error)")
        }
    }

    func stopProcess(_ process: inout Process?, port: Int) {
        if let running = process {
            if running.isRunning {
                running.terminate()
                running.waitUntilExit()
            }
            process = nil
        }
        let lsof = Process()
        lsof.launchPath = "/usr/sbin/lsof"
        lsof.arguments = ["-ti:\(port)"]
        let pipe = Pipe()
        lsof.standardOutput = pipe
        lsof.standardError = pipe
        do { try lsof.run(); lsof.waitUntilExit() } catch {}
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let pids = (String(data: data, encoding: .utf8) ?? "")
            .split(whereSeparator: { $0.isWhitespace })
            .map(String.init)
        for pid in pids where !pid.isEmpty {
            _ = runCapture("/bin/kill", ["-TERM", pid], nil, nil)
        }
    }

    func stopAll() {
        stopProcess(&backendProc, port: 5001)
        stopProcess(&uiProc, port: 3000)
        appendLog("All servers stopped.")
    }

    func waitHealthy(url: String, timeout: Int) -> Bool {
        let deadline = Date().addingTimeInterval(TimeInterval(timeout))
        repeat {
            let curl = Process()
            curl.launchPath = "/usr/bin/curl"
            curl.arguments = ["--fail", "--silent", "--show-error", "-o", "/dev/null", "-m", "3", url]
            let pipe = Pipe()
            curl.standardOutput = pipe
            curl.standardError = pipe
            do { try curl.run(); curl.waitUntilExit() } catch {}
            if curl.terminationStatus == 0 { return true }
            let remaining = deadline.timeIntervalSinceNow
            if remaining <= 0 { break }
            Thread.sleep(forTimeInterval: min(1.0, remaining))
        } while Date() < deadline
        return false
    }

    func openBrowser() {
        if let target = URL(string: uiURL) { NSWorkspace.shared.open(target) }
    }

    // MARK: Menu

    func buildMenu(running: Bool) {
        statusItem.button?.title = running ? "🐟 MicroFish" : "⏳ MicroFish"
        let menu = NSMenu()
        menu.addItem(menuItem("Open MicroFish", #selector(openUI(_:))))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(menuItem("Edit API Keys…", #selector(showSettings(_:))))
        menu.addItem(menuItem("Reveal Settings (.env)", #selector(revealEnv(_:))))
        menu.addItem(menuItem("Restart Servers", #selector(restart(_:))))
        menu.addItem(menuItem("Show Logs Folder", #selector(showLogs(_:))))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(menuItem("Quit MicroFish", #selector(quit(_:))))
        statusItem.menu = menu
    }

    func menuItem(_ title: String, _ action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        return item
    }

    // MARK: Menu actions

    @objc func openUI(_ sender: Any?) { openBrowser() }

    @objc func showSettings(_ sender: Any?) { showSettingsWindow() }

    @objc func revealEnv(_ sender: Any?) {
        let target = FileManager.default.fileExists(atPath: envPath) ? envPath : appSupport
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: target)])
    }

    @objc func restart(_ sender: Any?) {
        DispatchQueue.global(qos: .userInitiated).async {
            self.stopAll()
            self.startBackend()
            let backendOK = self.waitHealthy(url: healthURL, timeout: 150)
            self.startUI()
            let uiOK = self.waitHealthy(url: uiURL, timeout: 60)
            DispatchQueue.main.async { self.buildMenu(running: backendOK && uiOK) }
        }
    }

    @objc func showLogs(_ sender: Any?) {
        NSWorkspace.shared.open(URL(fileURLWithPath: logsDir, isDirectory: true))
    }

    @objc func quit(_ sender: Any?) { NSApp.terminate(nil) }

    // MARK: Settings window

    func showSettingsWindow() {
        if settingsWindow == nil {
            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 480, height: 270),
                styleMask: [.titled, .closable],
                backing: .buffered,
                defer: false
            )
            window.title = "MicroFish — API Settings"
            let view = NSView(frame: NSRect(x: 0, y: 0, width: 480, height: 270))
            view.autoresizingMask = [.width, .height]

            let info = NSTextField(labelWithString: "Enter your keys, then Save & Restart. Keys are stored in Application Support/MicroFish/.env")
            info.font = NSFont.systemFont(ofSize: 11)
            info.lineBreakMode = .byWordWrapping
            info.frame = NSRect(x: 20, y: 244, width: 440, height: 22)
            view.addSubview(info)

            var y: CGFloat = 210
            for key in settingsKeys {
                let label = NSTextField(labelWithString: key)
                label.frame = NSRect(x: 20, y: y, width: 150, height: 22)
                let field = NSTextField(frame: NSRect(x: 180, y: y, width: 280, height: 22))
                field.stringValue = readEnv()[key] ?? ""
                field.placeholderString = "enter \(key)"
                view.addSubview(label)
                view.addSubview(field)
                fields[key] = field
                y -= 32
            }

            let save = NSButton(title: "Save", target: self, action: #selector(saveSettings(_:)))
            save.frame = NSRect(x: 180, y: 16, width: 90, height: 28)
            let saveRestart = NSButton(title: "Save & Restart", target: self, action: #selector(saveAndRestart(_:)))
            saveRestart.frame = NSRect(x: 280, y: 16, width: 150, height: 28)
            view.addSubview(save)
            view.addSubview(saveRestart)

            window.contentView = view
            window.center()
            settingsWindow = window
        }
        let env = readEnv()
        for key in settingsKeys { fields[key]?.stringValue = env[key] ?? "" }
        settingsWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func saveSettings(_ sender: Any?) {
        var env = readEnv()
        for key in settingsKeys { env[key] = fields[key]?.stringValue ?? "" }
        writeEnv(env)
        appendLog("Settings saved.")
    }

    @objc func saveAndRestart(_ sender: Any?) {
        saveSettings(sender)
        settingsWindow?.close()
        restart(sender)
    }

    // MARK: .env read / write

    func readEnv() -> [String: String] {
        var dict: [String: String] = [:]
        guard let text = try? String(contentsOfFile: envPath, encoding: .utf8) else { return dict }
        for raw in text.split(separator: "\n") {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty || line.hasPrefix("#") { continue }
            guard let equals = line.firstIndex(of: "=") else { continue }
            let key = String(line[..<equals])
            let value = String(line[line.index(after: equals)...])
            dict[key] = value
        }
        return dict
    }

    func writeEnv(_ env: [String: String]) {
        var remaining = env
        let header = """
        # MicroFish settings — add your API keys here.
        # LLM_API_KEY and ZEP_API_KEY are required for simulations.

        """
        var lines: [String] = [header]
        let ordered = ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_NAME", "ZEP_API_KEY",
                       "LLM_BOOST_API_KEY", "LLM_BOOST_BASE_URL", "LLM_BOOST_MODEL_NAME"]
        for key in ordered {
            if let value = remaining.removeValue(forKey: key) {
                lines.append("\(key)=\(value)")
            }
        }
        for (key, value) in remaining.sorted(by: { $0.key < $1.key }) {
            lines.append("\(key)=\(value)")
        }
        try? lines.joined(separator: "\n").write(toFile: envPath, atomically: true, encoding: .utf8)
    }
}

// MARK: - Main entry point

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
