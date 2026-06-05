mod overlay;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::env;
use std::fs::{create_dir_all, OpenOptions};
use std::io::Write;
use std::io::{BufRead, BufReader};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{Emitter, Manager, WindowEvent};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

const PACKAGED_SIDECAR_NAME: &str = "omnicovas-sidecar";
const PACKAGED_SIDECAR_EXE: &str = "omnicovas-sidecar.exe";
const TARGET_TRIPLE: &str = "x86_64-pc-windows-msvc";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct BridgeInfo {
    port: u64,
    http_base: String,
    ws_base: String,
}

static BRIDGE_INFO: OnceLock<Mutex<Option<BridgeInfo>>> = OnceLock::new();
static SIDECAR_CHILD: OnceLock<Mutex<Option<Child>>> = OnceLock::new();
static SIDECAR_LOG_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn bridge_store() -> &'static Mutex<Option<BridgeInfo>> {
    BRIDGE_INFO.get_or_init(|| Mutex::new(None))
}

fn sidecar_child_store() -> &'static Mutex<Option<Child>> {
    SIDECAR_CHILD.get_or_init(|| Mutex::new(None))
}

fn sidecar_log_lock() -> &'static Mutex<()> {
    SIDECAR_LOG_LOCK.get_or_init(|| Mutex::new(()))
}

#[tauri::command]
fn get_bridge_info() -> Option<BridgeInfo> {
    bridge_store().lock().ok()?.clone()
}

fn sidecar_log_path() -> PathBuf {
    let base = env::var_os("APPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(env::temp_dir);

    base.join("OmniCOVAS")
        .join("logs")
        .join("tauri_sidecar.log")
}

fn log_sidecar_diagnostic(message: impl AsRef<str>) {
    let _guard = sidecar_log_lock().lock().ok();
    let path = sidecar_log_path();

    if let Some(parent) = path.parent() {
        let _ = create_dir_all(parent);
    }

    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default();

    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&path) {
        let _ = writeln!(
            file,
            "[{} pid={}] {}",
            timestamp,
            std::process::id(),
            message.as_ref()
        );
    }
}

fn redact_marker_value(text: &str, marker: &str) -> String {
    let mut redacted = String::new();
    let mut rest = text;

    while let Some(index) = rest.find(marker) {
        let value_start = index + marker.len();
        redacted.push_str(&rest[..value_start]);
        redacted.push_str("<redacted>");

        let value_tail = &rest[value_start..];
        let value_len = value_tail
            .find(|ch: char| ch.is_whitespace() || matches!(ch, ',' | '|' | ')' | ']'))
            .unwrap_or(value_tail.len());
        rest = &value_tail[value_len..];
    }

    redacted.push_str(rest);
    redacted
}

fn redact_diagnostic_line(line: &str) -> String {
    let mut redacted = line.to_string();

    for env_key in ["USERPROFILE", "APPDATA", "LOCALAPPDATA"] {
        if let Ok(value) = env::var(env_key) {
            if !value.is_empty() {
                redacted = redacted.replace(&value, &format!("%{}%", env_key));
            }
        }
    }

    redact_marker_value(&redacted, "cmdr=")
}

fn record_bridge_ready(app_handle: &tauri::AppHandle, line: &str) {
    println!("[omnicovas-core] {}", line);
    log_sidecar_diagnostic(format!("sidecar stdout: {}", redact_diagnostic_line(line)));

    if let Ok(json) = serde_json::from_str::<Value>(line) {
        if json.get("status").and_then(|v| v.as_str()) == Some("ready") {
            if let Some(port) = json.get("port").and_then(|v| v.as_u64()) {
                let info = BridgeInfo {
                    port,
                    http_base: format!("http://127.0.0.1:{port}"),
                    ws_base: format!("ws://127.0.0.1:{port}"),
                };

                if let Ok(mut store) = bridge_store().lock() {
                    *store = Some(info.clone());
                }

                match app_handle.emit("bridge-ready", info) {
                    Ok(()) => {
                        log_sidecar_diagnostic(format!(
                            "bridge-ready event emitted: port={}",
                            port
                        ));
                    }
                    Err(error) => {
                        log_sidecar_diagnostic(format!(
                            "bridge-ready event emit failed: port={} error={}",
                            port, error
                        ));
                    }
                }

                println!("OmniCOVAS bridge ready on port {}", port);
                log_sidecar_diagnostic(format!("selected bridge port: {}", port));
            }
        }
    }
}

fn log_core_stderr(bytes: &[u8]) {
    let text = String::from_utf8_lossy(bytes);
    for line in text.lines() {
        eprintln!("[omnicovas-core:stderr] {}", line);
        log_sidecar_diagnostic(format!("sidecar stderr: {}", redact_diagnostic_line(line)));
    }
}

fn dev_repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("CARGO_MANIFEST_DIR must have a parent repository root")
        .to_path_buf()
}

fn launch_dev_python_core(app_handle: tauri::AppHandle) {
    thread::spawn(move || {
        let repo_root = dev_repo_root();
        log_sidecar_diagnostic(format!(
            "dev core launch requested: command=uv run python -m omnicovas.core.main cwd={}",
            repo_root.display()
        ));
        let mut child = Command::new("uv")
            .args(["run", "python", "-m", "omnicovas.core.main"])
            .current_dir(repo_root)
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("failed to launch OmniCOVAS Python core");

        let stdout = child
            .stdout
            .take()
            .expect("failed to capture OmniCOVAS Python stdout");

        let reader = BufReader::new(stdout);

        for line in reader.lines().map_while(Result::ok) {
            record_bridge_ready(&app_handle, &line);
        }

        log_sidecar_diagnostic("dev core stdout closed");
    });
}

fn packaged_sidecar_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(current_exe) = env::current_exe() {
        if let Some(exe_dir) = current_exe.parent() {
            candidates.push(exe_dir.join(PACKAGED_SIDECAR_EXE));
            candidates
                .push(exe_dir.join(format!("{}-{}.exe", PACKAGED_SIDECAR_NAME, TARGET_TRIPLE)));
        }
    }

    candidates
}

fn try_connect_local_port(port: u64) -> bool {
    let Ok(port) = u16::try_from(port) else {
        return false;
    };

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
}

fn parse_ready_port_from_line(line: &str) -> Option<u64> {
    if let Ok(json) = serde_json::from_str::<Value>(line) {
        if json.get("status").and_then(|v| v.as_str()) == Some("ready") {
            return json.get("port").and_then(|v| v.as_u64());
        }
    }

    if let Some((_, tail)) = line.split_once("Ready signal emitted: port=") {
        return tail
            .chars()
            .take_while(|ch| ch.is_ascii_digit())
            .collect::<String>()
            .parse::<u64>()
            .ok();
    }

    if let Some((_, tail)) = line.split_once("ApiBridge ready at http://127.0.0.1:") {
        return tail
            .chars()
            .take_while(|ch| ch.is_ascii_digit())
            .collect::<String>()
            .parse::<u64>()
            .ok();
    }

    None
}

fn appdata_core_log_path() -> PathBuf {
    let base = env::var_os("APPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(env::temp_dir);

    base.join("OmniCOVAS").join("logs").join("omnicovas.log")
}

fn adopt_existing_bridge_from_log(app_handle: &tauri::AppHandle) -> bool {
    let log_path = appdata_core_log_path();
    let Ok(log_text) = std::fs::read_to_string(&log_path) else {
        log_sidecar_diagnostic(format!(
            "existing bridge adoption skipped: core log not readable at {}",
            log_path.display()
        ));
        return false;
    };

    for line in log_text.lines().rev().take(500) {
        if let Some(port) = parse_ready_port_from_line(line) {
            if try_connect_local_port(port) {
                log_sidecar_diagnostic(format!(
                    "existing sidecar bridge detected from log: port={}",
                    port
                ));
                record_bridge_ready(
                    app_handle,
                    &format!(r#"{{"status":"ready","port":{port}}}"#),
                );
                return true;
            }

            log_sidecar_diagnostic(format!(
                "stale bridge log entry ignored: port={} not listening",
                port
            ));
        }
    }

    log_sidecar_diagnostic(format!(
        "existing bridge adoption skipped: no recent ready line in {}",
        log_path.display()
    ));
    false
}

fn spawn_reader_thread(app_handle: tauri::AppHandle, stdout: impl std::io::Read + Send + 'static) {
    thread::spawn(move || {
        let reader = BufReader::new(stdout);

        for line in reader.lines().map_while(Result::ok) {
            record_bridge_ready(&app_handle, &line);
        }

        log_sidecar_diagnostic("sidecar stdout closed");
    });
}

fn spawn_stderr_thread(stderr: impl std::io::Read + Send + 'static) {
    thread::spawn(move || {
        let reader = BufReader::new(stderr);

        for line in reader.lines().map_while(Result::ok) {
            log_core_stderr(line.as_bytes());
        }

        log_sidecar_diagnostic("sidecar stderr closed");
    });
}

fn spawn_sidecar_exit_monitor() {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(1));

        let status = {
            let Ok(mut guard) = sidecar_child_store().lock() else {
                log_sidecar_diagnostic("sidecar exit monitor lock failed");
                return;
            };

            let Some(child) = guard.as_mut() else {
                return;
            };

            match child.try_wait() {
                Ok(Some(status)) => Some(format!("{:?}", status)),
                Ok(None) => None,
                Err(error) => Some(format!("try_wait_error={}", error)),
            }
        };

        if let Some(status) = status {
            log_sidecar_diagnostic(format!("sidecar process exited: {}", status));
            if let Ok(mut guard) = sidecar_child_store().lock() {
                *guard = None;
            }
            return;
        }
    });
}

fn store_packaged_sidecar_child(mut child: Child, app_handle: tauri::AppHandle) {
    if let Some(stdout) = child.stdout.take() {
        spawn_reader_thread(app_handle, stdout);
    } else {
        log_sidecar_diagnostic("sidecar stdout was not captured");
    }

    if let Some(stderr) = child.stderr.take() {
        spawn_stderr_thread(stderr);
    } else {
        log_sidecar_diagnostic("sidecar stderr was not captured");
    }

    let pid = child.id();
    if let Ok(mut guard) = sidecar_child_store().lock() {
        *guard = Some(child);
        log_sidecar_diagnostic(format!("packaged sidecar child stored: pid={}", pid));
    } else {
        log_sidecar_diagnostic(format!(
            "failed to store packaged sidecar child after spawn: pid={}",
            pid
        ));
    }

    spawn_sidecar_exit_monitor();
}

fn packaged_sidecar_already_running() -> bool {
    let Ok(mut guard) = sidecar_child_store().lock() else {
        log_sidecar_diagnostic("duplicate sidecar check failed: child lock unavailable");
        return false;
    };

    let Some(child) = guard.as_mut() else {
        return false;
    };

    match child.try_wait() {
        Ok(None) => {
            log_sidecar_diagnostic(format!(
                "duplicate sidecar start suppressed: existing pid={}",
                child.id()
            ));
            true
        }
        Ok(Some(status)) => {
            log_sidecar_diagnostic(format!(
                "stale sidecar child cleared before restart: status={:?}",
                status
            ));
            *guard = None;
            false
        }
        Err(error) => {
            log_sidecar_diagnostic(format!(
                "sidecar duplicate check error; clearing child handle: {}",
                error
            ));
            *guard = None;
            false
        }
    }
}

fn spawn_explicit_packaged_sidecar(
    app_handle: tauri::AppHandle,
    sidecar_path: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    let current_dir = sidecar_path
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(env::temp_dir);

    log_sidecar_diagnostic(format!(
        "spawning packaged sidecar: path={} cwd={}",
        sidecar_path.display(),
        current_dir.display()
    ));

    let mut command = Command::new(sidecar_path);
    command
        .current_dir(current_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    let child = command.spawn()?;
    log_sidecar_diagnostic(format!(
        "packaged sidecar spawn success: pid={}",
        child.id()
    ));
    store_packaged_sidecar_child(child, app_handle);

    Ok(())
}

fn launch_packaged_sidecar(app_handle: tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    log_sidecar_diagnostic(format!(
        "packaged sidecar launch requested: name={} exe={}",
        PACKAGED_SIDECAR_NAME, PACKAGED_SIDECAR_EXE
    ));

    if packaged_sidecar_already_running() {
        return Ok(());
    }

    if adopt_existing_bridge_from_log(&app_handle) {
        return Ok(());
    }

    let candidates = packaged_sidecar_candidates();
    for candidate in &candidates {
        log_sidecar_diagnostic(format!(
            "checking packaged sidecar candidate: {} exists={}",
            candidate.display(),
            candidate.exists()
        ));

        if candidate.is_file() {
            return spawn_explicit_packaged_sidecar(app_handle, candidate);
        }
    }

    log_sidecar_diagnostic(format!(
        "packaged sidecar not found; candidates={}",
        candidates
            .iter()
            .map(|path| path.display().to_string())
            .collect::<Vec<_>>()
            .join("; ")
    ));

    Err(format!("packaged sidecar not found: {}", PACKAGED_SIDECAR_EXE).into())
}

#[cfg(windows)]
fn kill_packaged_sidecar_process_tree(pid: u32) -> bool {
    let pid_arg = pid.to_string();
    let mut command = Command::new("taskkill");
    command.args(["/PID", pid_arg.as_str(), "/T", "/F"]);
    command.creation_flags(CREATE_NO_WINDOW);

    match command.output() {
        Ok(output) => {
            log_sidecar_diagnostic(format!(
                "sidecar process tree stop requested: pid={} status={:?}",
                pid, output.status
            ));

            for line in String::from_utf8_lossy(&output.stdout).lines() {
                log_sidecar_diagnostic(format!("taskkill stdout: {}", line));
            }

            for line in String::from_utf8_lossy(&output.stderr).lines() {
                log_sidecar_diagnostic(format!("taskkill stderr: {}", line));
            }

            output.status.success()
        }
        Err(error) => {
            log_sidecar_diagnostic(format!(
                "sidecar process tree stop failed to start: pid={} error={}",
                pid, error
            ));
            false
        }
    }
}

#[cfg(not(windows))]
fn kill_packaged_sidecar_process_tree(pid: u32) -> bool {
    log_sidecar_diagnostic(format!(
        "sidecar process tree stop unavailable on this platform: pid={}",
        pid
    ));
    false
}

fn stop_packaged_sidecar() {
    let Ok(mut guard) = sidecar_child_store().lock() else {
        log_sidecar_diagnostic("sidecar stop skipped: child lock unavailable");
        return;
    };

    let Some(mut child) = guard.take() else {
        log_sidecar_diagnostic("sidecar stop skipped: no owned child");
        return;
    };

    let pid = child.id();
    log_sidecar_diagnostic(format!("stopping packaged sidecar: pid={}", pid));

    let tree_stopped = kill_packaged_sidecar_process_tree(pid);
    if !tree_stopped {
        log_sidecar_diagnostic(format!("falling back to direct sidecar kill: pid={}", pid));
    }

    if !tree_stopped {
        if let Err(error) = child.kill() {
            log_sidecar_diagnostic(format!(
                "sidecar kill returned error: pid={} error={}",
                pid, error
            ));
        }
    }

    match child.wait() {
        Ok(status) => log_sidecar_diagnostic(format!(
            "sidecar wait after stop: pid={} status={:?}",
            pid, status
        )),
        Err(error) => log_sidecar_diagnostic(format!(
            "sidecar wait after stop failed: pid={} error={}",
            pid, error
        )),
    }
}

fn close_secondary_windows(app_handle: &tauri::AppHandle, main_label: &str) {
    log_sidecar_diagnostic("overlay/window cleanup start");

    let mut closed_count = 0;
    for (label, webview_window) in app_handle.webview_windows() {
        if label == main_label {
            continue;
        }

        log_sidecar_diagnostic(format!(
            "closing secondary window before app exit: label={}",
            label
        ));

        match webview_window.close() {
            Ok(()) => {
                closed_count += 1;
            }
            Err(error) => {
                log_sidecar_diagnostic(format!(
                    "secondary window close failed before app exit: label={} error={}",
                    label, error
                ));
            }
        }
    }

    log_sidecar_diagnostic(format!(
        "overlay/window cleanup complete: closed_count={}",
        closed_count
    ));
}

fn log_startup_context(is_dev: bool) {
    log_sidecar_diagnostic(format!(
        "tauri setup start: is_dev={} current_exe={:?}",
        is_dev,
        env::current_exe().ok()
    ));
}

#[tauri::command]
async fn show_overlay_test_banner(app: tauri::AppHandle) -> Result<(), String> {
    println!("[tauri] show_overlay_test_banner requested");
    app.emit("overlay:show_test_banner", ())
        .map_err(|e| e.to_string())?;
    overlay::show_overlay(app).await
}

#[tauri::command]
async fn show_overlay_named_test_banner(
    app: tauri::AppHandle,
    event_type: String,
) -> Result<(), String> {
    const KNOWN: &[&str] = &[
        "HULL_CRITICAL_10",
        "SHIELDS_DOWN",
        "HULL_CRITICAL_25",
        "FUEL_CRITICAL",
        "MODULE_CRITICAL",
        "FUEL_LOW",
        "HEAT_WARNING",
        "HEAT_DAMAGE",
        "OMNICOVAS_TEST",
    ];
    if !KNOWN.contains(&event_type.as_str()) {
        return Err(format!("Unknown event type: {}", event_type));
    }
    println!("[tauri] show_overlay_named_test_banner: {}", event_type);
    app.emit("overlay:show_named_test_banner", &event_type)
        .map_err(|e| e.to_string())?;
    overlay::show_overlay(app).await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            app.handle()
                .plugin(tauri_plugin_window_state::Builder::default().build())?;

            app.handle()
                .plugin(tauri_plugin_global_shortcut::Builder::default().build())?;

            app.manage(overlay::OverlayState::default());
            overlay::init_overlay(app.handle())?;

            let app_handle = app.handle().clone();
            let is_dev = tauri::is_dev();
            log_startup_context(is_dev);

            if is_dev {
                log_sidecar_diagnostic("tauri dev branch selected");
                launch_dev_python_core(app_handle);
            } else {
                log_sidecar_diagnostic("tauri packaged branch selected");
                launch_packaged_sidecar(app_handle)?;
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                if window.label() == "main" {
                    log_sidecar_diagnostic("main window close requested");
                    log_sidecar_diagnostic("sidecar cleanup start");
                    stop_packaged_sidecar();
                    log_sidecar_diagnostic("sidecar cleanup complete");

                    let app_handle = window.app_handle().clone();
                    close_secondary_windows(&app_handle, window.label());

                    log_sidecar_diagnostic("app exit requested");
                    app_handle.exit(0);
                } else {
                    log_sidecar_diagnostic(format!(
                        "non-main window close ignored for sidecar lifecycle: label={}",
                        window.label()
                    ));
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            overlay::show_overlay,
            overlay::hide_overlay,
            show_overlay_test_banner,
            show_overlay_named_test_banner,
            get_bridge_info
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
