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
use std::sync::atomic::{AtomicBool, Ordering};
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

/// Identity contract for adopting an already-listening local bridge.
/// Must match `omnicovas.core.api_bridge.BRIDGE_APP_IDENTITY` /
/// `BRIDGE_PROTOCOL_VERSION`.
const BRIDGE_APP_IDENTITY: &str = "omnicovas";
const BRIDGE_PROTOCOL_VERSION: u64 = 1;
const BRIDGE_PROBE_CONNECT_TIMEOUT: Duration = Duration::from_millis(400);
const BRIDGE_PROBE_IO_TIMEOUT: Duration = Duration::from_millis(1500);
const BRIDGE_PROBE_MAX_BODY: usize = 64 * 1024;

/// Environment variable that lets a developer pin the dev-mode Python
/// interpreter explicitly. Highest-priority runner source.
const DEV_PYTHON_ENV: &str = "OMNICOVAS_DEV_PYTHON";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct BridgeInfo {
    port: u64,
    http_base: String,
    ws_base: String,
}

static BRIDGE_INFO: OnceLock<Mutex<Option<BridgeInfo>>> = OnceLock::new();
static SIDECAR_CHILD: OnceLock<Mutex<Option<Child>>> = OnceLock::new();
static CORE_STOPPING: AtomicBool = AtomicBool::new(false);
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

/// A resolved way to start the development-mode Python core.
///
/// Resolution is deterministic and ordered (see `resolve_dev_runner`). The
/// launcher never assumes a globally installed `uv`: a repository virtual
/// environment is sufficient, and an explicit override always wins.
#[derive(Debug, Clone, PartialEq, Eq)]
struct DevRunner {
    program: PathBuf,
    args: Vec<String>,
    /// Human-readable provenance for diagnostics, e.g. "repo venv".
    origin: &'static str,
}

impl DevRunner {
    fn interpreter(program: PathBuf, origin: &'static str) -> Self {
        Self {
            program,
            args: vec!["-m".to_string(), "omnicovas.core.main".to_string()],
            origin,
        }
    }

    fn uv(program: PathBuf) -> Self {
        Self {
            program,
            args: vec![
                "run".to_string(),
                "python".to_string(),
                "-m".to_string(),
                "omnicovas.core.main".to_string(),
            ],
            origin: "uv",
        }
    }

    fn describe(&self) -> String {
        format!("{} {}", self.program.display(), self.args.join(" "))
    }
}

/// Candidate interpreter paths inside the repository virtual environment,
/// most specific first. Both layouts are listed so a developer on a
/// POSIX-style venv is served too.
fn venv_interpreter_candidates(repo_root: &Path) -> Vec<PathBuf> {
    vec![
        repo_root.join(".venv").join("Scripts").join("python.exe"),
        repo_root.join(".venv").join("bin").join("python"),
    ]
}

/// Deterministic dev-runner resolution.
///
/// Order:
///   1. `OMNICOVAS_DEV_PYTHON` override (explicit developer intent).
///   2. Repository virtual environment interpreter.
///   3. `uv run python -m ...` when `uv` is resolvable on PATH.
///   4. A bare `python` resolvable on PATH.
///
/// Returns a human-actionable error string when nothing is usable. Kept pure
/// (filesystem and PATH access are injected) so the order is unit-testable.
fn resolve_dev_runner(
    override_path: Option<PathBuf>,
    venv_candidates: &[PathBuf],
    file_exists: &dyn Fn(&Path) -> bool,
    uv_on_path: Option<PathBuf>,
    python_on_path: Option<PathBuf>,
) -> Result<DevRunner, String> {
    if let Some(explicit) = override_path {
        if file_exists(&explicit) {
            return Ok(DevRunner::interpreter(
                explicit,
                "OMNICOVAS_DEV_PYTHON override",
            ));
        }
        return Err(format!(
            "{DEV_PYTHON_ENV} is set to '{}' but no such interpreter exists. \
             Point it at a Python 3.11 executable or unset it to fall back to the \
             repository virtual environment.",
            explicit.display()
        ));
    }

    for candidate in venv_candidates {
        if file_exists(candidate) {
            return Ok(DevRunner::interpreter(candidate.clone(), "repo venv"));
        }
    }

    if let Some(uv) = uv_on_path {
        return Ok(DevRunner::uv(uv));
    }

    if let Some(python) = python_on_path {
        return Ok(DevRunner::interpreter(python, "PATH python"));
    }

    Err(format!(
        "No supported Python runner found for OmniCOVAS development launch. \
         Tried: {DEV_PYTHON_ENV} override, repository virtual environment \
         (.venv/Scripts/python.exe or .venv/bin/python), 'uv' on PATH, and \
         'python' on PATH. Create the repository virtual environment (see \
         README 'Development setup') or set {DEV_PYTHON_ENV} to a Python 3.11 \
         executable."
    ))
}

/// Locate an executable on PATH without spawning it.
fn find_on_path(program: &str) -> Option<PathBuf> {
    let path_var = env::var_os("PATH")?;
    let exts: Vec<String> = if cfg!(windows) {
        env::var("PATHEXT")
            .unwrap_or_else(|_| ".EXE;.CMD;.BAT;.COM".to_string())
            .split(';')
            .filter(|e| !e.is_empty())
            .map(|e| e.to_ascii_lowercase())
            .collect()
    } else {
        vec![String::new()]
    };

    for dir in env::split_paths(&path_var) {
        let direct = dir.join(program);
        if direct.is_file() {
            return Some(direct);
        }
        for ext in &exts {
            if ext.is_empty() {
                continue;
            }
            let candidate = dir.join(format!("{program}{ext}"));
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }

    None
}

fn resolve_dev_runner_from_environment(repo_root: &Path) -> Result<DevRunner, String> {
    let override_path = env::var_os(DEV_PYTHON_ENV)
        .map(PathBuf::from)
        .filter(|p| !p.as_os_str().is_empty());

    resolve_dev_runner(
        override_path,
        &venv_interpreter_candidates(repo_root),
        &|p: &Path| p.is_file(),
        find_on_path("uv"),
        find_on_path("python3").or_else(|| find_on_path("python")),
    )
}

fn launch_dev_python_core(app_handle: tauri::AppHandle) {
    thread::spawn(move || {
        let repo_root = dev_repo_root();

        let runner = match resolve_dev_runner_from_environment(&repo_root) {
            Ok(runner) => runner,
            Err(error) => {
                // A missing developer tool is a routine, recoverable condition.
                // Report it clearly and leave the shell running so the UI can
                // show a bridge-unavailable state instead of taking the whole
                // application down with a panic.
                log_sidecar_diagnostic(format!("dev core launch failed: {error}"));
                eprintln!("[omnicovas-core] {error}");
                return;
            }
        };

        log_sidecar_diagnostic(format!(
            "dev core launch requested: runner_origin={} command={} cwd={}",
            runner.origin,
            runner.describe(),
            repo_root.display()
        ));

        // Share the existing core ownership/cleanup path with packaged launches.
        // Serialize spawn with close so an immediately closed window cannot
        // leave a newly spawned dev core behind.
        let Ok(mut owner) = sidecar_child_store().lock() else {
            log_sidecar_diagnostic("dev core spawn skipped: child lock unavailable");
            return;
        };
        if CORE_STOPPING.load(Ordering::SeqCst) {
            return;
        }
        let spawned = Command::new(&runner.program)
            .args(&runner.args)
            .current_dir(&repo_root)
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn();

        let mut child = match spawned {
            Ok(child) => child,
            Err(error) => {
                log_sidecar_diagnostic(format!(
                    "dev core spawn failed: runner_origin={} command={} error={}",
                    runner.origin,
                    runner.describe(),
                    error
                ));
                eprintln!(
                    "[omnicovas-core] Failed to start the OmniCOVAS Python core using {} ({}): {}",
                    runner.describe(),
                    runner.origin,
                    error
                );
                return;
            }
        };

        let stdout = child.stdout.take();
        *owner = Some(child);
        drop(owner);
        let Some(stdout) = stdout else {
            log_sidecar_diagnostic("dev core stdout unavailable; abandoning readiness watch");
            return;
        };

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

/// Outcome of probing a loopback port for an adoptable OmniCOVAS bridge.
///
/// Anything other than `Healthy` means "do not adopt": a stale log entry, a
/// recycled port held by an unrelated process, an incompatible sidecar, or a
/// server that answers but is not us.
#[derive(Debug, Clone, PartialEq, Eq)]
enum BridgeProbe {
    Healthy,
    NotListening,
    /// Something answered but did not identify as an OmniCOVAS bridge.
    NotOmniCovas(String),
    /// An OmniCOVAS bridge answered but speaks a different protocol version.
    IncompatibleProtocol(u64),
    /// Reachable but the response could not be understood.
    Malformed(String),
}

impl BridgeProbe {
    fn is_adoptable(&self) -> bool {
        matches!(self, BridgeProbe::Healthy)
    }

    fn reason(&self) -> String {
        match self {
            BridgeProbe::Healthy => "healthy".to_string(),
            BridgeProbe::NotListening => "not listening".to_string(),
            BridgeProbe::NotOmniCovas(detail) => {
                format!("not an OmniCOVAS bridge ({detail})")
            }
            BridgeProbe::IncompatibleProtocol(found) => format!(
                "incompatible bridge protocol (found {found}, expected {BRIDGE_PROTOCOL_VERSION})"
            ),
            BridgeProbe::Malformed(detail) => format!("malformed health response ({detail})"),
        }
    }
}

/// Classify a `/health` response body against the bridge identity contract.
///
/// Pure so the negative cases (generic listener, HTML error page, wrong app,
/// wrong protocol, truncated JSON) are unit-testable without sockets.
fn classify_health_body(body: &str) -> BridgeProbe {
    let json: Value = match serde_json::from_str(body) {
        Ok(value) => value,
        Err(error) => {
            return BridgeProbe::NotOmniCovas(format!("non-JSON response: {error}"));
        }
    };

    let Some(object) = json.as_object() else {
        return BridgeProbe::NotOmniCovas("response was not a JSON object".to_string());
    };

    match object.get("app").and_then(|v| v.as_str()) {
        Some(BRIDGE_APP_IDENTITY) => {}
        Some(other) => {
            return BridgeProbe::NotOmniCovas(format!("app={other}"));
        }
        None => {
            return BridgeProbe::NotOmniCovas("missing app identity field".to_string());
        }
    }

    let Some(protocol) = object.get("bridge_protocol").and_then(|v| v.as_u64()) else {
        return BridgeProbe::Malformed("missing or non-numeric bridge_protocol".to_string());
    };

    if protocol != BRIDGE_PROTOCOL_VERSION {
        return BridgeProbe::IncompatibleProtocol(protocol);
    }

    match object.get("status").and_then(|v| v.as_str()) {
        Some("ok") => BridgeProbe::Healthy,
        Some(other) => BridgeProbe::Malformed(format!("status={other}")),
        None => BridgeProbe::Malformed("missing status".to_string()),
    }
}

/// Split an HTTP/1.x response into (status_code, body).
fn split_http_response(raw: &str) -> Result<(u16, &str), String> {
    let mut lines = raw.split("\r\n");
    let status_line = lines.next().ok_or_else(|| "empty response".to_string())?;
    let mut parts = status_line.split_whitespace();
    let _version = parts
        .next()
        .ok_or_else(|| "missing HTTP version".to_string())?;
    let code: u16 = parts
        .next()
        .ok_or_else(|| "missing status code".to_string())?
        .parse()
        .map_err(|_| "unparseable status code".to_string())?;

    let body = raw
        .split_once("\r\n\r\n")
        .map(|(_, body)| body)
        .ok_or_else(|| "missing header/body separator".to_string())?;

    Ok((code, body))
}

/// Minimal loopback HTTP GET. Deliberately dependency-free: this runs on the
/// startup path and must not pull an HTTP client into the shell.
fn loopback_http_get(port: u16, path: &str) -> Result<(u16, String), String> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&addr, BRIDGE_PROBE_CONNECT_TIMEOUT)
        .map_err(|error| error.to_string())?;
    stream
        .set_read_timeout(Some(BRIDGE_PROBE_IO_TIMEOUT))
        .map_err(|error| error.to_string())?;
    stream
        .set_write_timeout(Some(BRIDGE_PROBE_IO_TIMEOUT))
        .map_err(|error| error.to_string())?;

    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;

    let mut raw = Vec::new();
    let mut chunk = [0_u8; 4096];
    loop {
        match std::io::Read::read(&mut stream, &mut chunk) {
            Ok(0) => break,
            Ok(n) => {
                raw.extend_from_slice(&chunk[..n]);
                if raw.len() >= BRIDGE_PROBE_MAX_BODY {
                    break;
                }
            }
            Err(error) => return Err(error.to_string()),
        }
    }

    let text = String::from_utf8_lossy(&raw).to_string();
    let (code, body) = split_http_response(&text)?;
    Ok((code, body.to_string()))
}

/// Probe a loopback port for an adoptable OmniCOVAS bridge.
///
/// Replaces the previous bare `TcpStream::connect` check, which would adopt any
/// process holding the port recorded in a prior run's log.
fn probe_local_bridge(port: u64) -> BridgeProbe {
    let Ok(port) = u16::try_from(port) else {
        return BridgeProbe::NotListening;
    };

    match loopback_http_get(port, "/health") {
        Err(_) => BridgeProbe::NotListening,
        Ok((code, body)) if code == 200 => classify_health_body(&body),
        Ok((code, _)) => BridgeProbe::NotOmniCovas(format!("HTTP {code} from /health")),
    }
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
            let probe = probe_local_bridge(port);
            if probe.is_adoptable() {
                log_sidecar_diagnostic(format!(
                    "existing sidecar bridge adopted after identity check: port={} app={} protocol={}",
                    port, BRIDGE_APP_IDENTITY, BRIDGE_PROTOCOL_VERSION
                ));
                record_bridge_ready(
                    app_handle,
                    &format!(r#"{{"status":"ready","port":{port}}}"#),
                );
                return true;
            }

            log_sidecar_diagnostic(format!(
                "bridge log entry rejected: port={} reason={}",
                port,
                probe.reason()
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
    CORE_STOPPING.store(true, Ordering::SeqCst);
    let Ok(mut guard) = sidecar_child_store().lock() else {
        log_sidecar_diagnostic("sidecar stop skipped: child lock unavailable");
        return;
    };

    let Some(mut child) = guard.take() else {
        log_sidecar_diagnostic("sidecar stop skipped: no owned child");
        return;
    };

    let pid = child.id();
    log_sidecar_diagnostic(format!("stopping owned core: pid={}", pid));

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

        // destroy(), not close(): the overlay refuses close requests so that
        // nothing but app exit can remove the in-game warning surface.
        match webview_window.destroy() {
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

            // The overlay's geometry is owned by present/park placement, and a
            // restored "visible" state would show it activated at launch.
            app.handle().plugin(
                tauri_plugin_window_state::Builder::default()
                    .with_denylist(&["overlay"])
                    .build(),
            )?;

            app.handle()
                .plugin(tauri_plugin_global_shortcut::Builder::default().build())?;

            app.manage(overlay::OverlayState::default());
            // A hotkey owned by another program must not stop OmniCOVAS from
            // starting; the overlay is already click-through and parked.
            if let Err(e) = overlay::init_overlay(app.handle()) {
                log::error!(
                    "Overlay hotkey unavailable; overlay continues without it: {}",
                    e
                );
            }

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
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "overlay" {
                    // A stray WM_CLOSE (or a tool closing "the first visible
                    // window") must not destroy the warning surface for the
                    // rest of the session. App exit destroys it explicitly.
                    api.prevent_close();
                    log_sidecar_diagnostic(
                        "overlay close request ignored; overlay stays available",
                    );
                    return;
                }
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
            overlay::present_overlay,
            overlay::park_overlay,
            overlay::set_overlay_click_through,
            show_overlay_test_banner,
            show_overlay_named_test_banner,
            get_bridge_info
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read as _;
    use std::net::TcpListener;

    fn exists_none(_: &Path) -> bool {
        false
    }

    // ---- dev runner resolution order (PB10-R2) ----

    #[test]
    fn override_wins_over_every_other_source() {
        let override_path = PathBuf::from("C:/custom/python.exe");
        let venv = vec![PathBuf::from("C:/repo/.venv/Scripts/python.exe")];

        let runner = resolve_dev_runner(
            Some(override_path.clone()),
            &venv,
            &|_: &Path| true,
            Some(PathBuf::from("C:/tools/uv.exe")),
            Some(PathBuf::from("C:/py/python.exe")),
        )
        .expect("override should resolve");

        assert_eq!(runner.program, override_path);
        assert_eq!(runner.origin, "OMNICOVAS_DEV_PYTHON override");
        assert_eq!(runner.args, vec!["-m", "omnicovas.core.main"]);
    }

    #[test]
    fn missing_override_target_is_an_actionable_error_not_a_silent_fallback() {
        let error = resolve_dev_runner(
            Some(PathBuf::from("C:/nope/python.exe")),
            &[PathBuf::from("C:/repo/.venv/Scripts/python.exe")],
            &|_: &Path| false,
            Some(PathBuf::from("C:/tools/uv.exe")),
            None,
        )
        .expect_err("a bad explicit override must not fall through");

        assert!(error.contains(DEV_PYTHON_ENV));
        assert!(error.contains("C:/nope/python.exe"));
    }

    #[test]
    fn repo_venv_is_preferred_over_uv() {
        let venv = PathBuf::from("C:/repo/.venv/Scripts/python.exe");
        let runner = resolve_dev_runner(
            None,
            &[venv.clone()],
            &|p: &Path| p == venv,
            Some(PathBuf::from("C:/tools/uv.exe")),
            Some(PathBuf::from("C:/py/python.exe")),
        )
        .expect("venv should resolve");

        assert_eq!(runner.program, venv);
        assert_eq!(runner.origin, "repo venv");
    }

    #[test]
    fn uv_is_used_only_when_no_venv_exists() {
        let uv = PathBuf::from("C:/tools/uv.exe");
        let runner = resolve_dev_runner(
            None,
            &[PathBuf::from("C:/repo/.venv/Scripts/python.exe")],
            &exists_none,
            Some(uv.clone()),
            Some(PathBuf::from("C:/py/python.exe")),
        )
        .expect("uv should resolve");

        assert_eq!(runner.program, uv);
        assert_eq!(runner.origin, "uv");
        assert_eq!(
            runner.args,
            vec!["run", "python", "-m", "omnicovas.core.main"]
        );
    }

    #[test]
    fn path_python_is_the_last_resort() {
        let python = PathBuf::from("C:/py/python.exe");
        let runner = resolve_dev_runner(None, &[], &exists_none, None, Some(python.clone()))
            .expect("PATH python should resolve");

        assert_eq!(runner.program, python);
        assert_eq!(runner.origin, "PATH python");
    }

    /// The regression this repair exists for: no `uv`, no PATH python, and a
    /// missing venv used to panic through `.expect()` at startup.
    #[test]
    fn missing_runner_returns_actionable_error_instead_of_panicking() {
        let error = resolve_dev_runner(
            None,
            &[PathBuf::from("C:/repo/.venv/Scripts/python.exe")],
            &exists_none,
            None,
            None,
        )
        .expect_err("no runner should be resolvable");

        assert!(error.contains("No supported Python runner"));
        assert!(error.contains(DEV_PYTHON_ENV));
        assert!(error.contains(".venv"));
    }

    #[test]
    fn venv_candidates_cover_windows_and_posix_layouts() {
        let candidates = venv_interpreter_candidates(Path::new("C:/repo"));
        assert_eq!(candidates.len(), 2);
        assert!(candidates[0].ends_with("python.exe"));
        assert!(candidates[1].ends_with("python"));
    }

    // ---- bridge adoption identity (PB10-R3) ----

    fn healthy_body() -> String {
        format!(
            "{{\"status\":\"ok\",\"app\":\"{}\",\"bridge_protocol\":{},\"version\":\"0.1.0\"}}",
            BRIDGE_APP_IDENTITY, BRIDGE_PROTOCOL_VERSION
        )
    }

    #[test]
    fn healthy_omnicovas_health_body_is_adoptable() {
        let probe = classify_health_body(&healthy_body());
        assert_eq!(probe, BridgeProbe::Healthy);
        assert!(probe.is_adoptable());
    }

    #[test]
    fn foreign_json_service_is_rejected() {
        let probe = classify_health_body("{\"status\":\"ok\",\"app\":\"grafana\"}");
        assert!(!probe.is_adoptable());
        assert!(matches!(probe, BridgeProbe::NotOmniCovas(_)));
    }

    #[test]
    fn health_body_without_identity_is_rejected() {
        // The pre-repair /health shape: reachable and "ok", but anonymous.
        let probe = classify_health_body("{\"status\":\"ok\",\"version\":\"0.1.0\"}");
        assert!(!probe.is_adoptable());
        assert_eq!(
            probe,
            BridgeProbe::NotOmniCovas("missing app identity field".to_string())
        );
    }

    #[test]
    fn incompatible_protocol_version_is_rejected() {
        let other = BRIDGE_PROTOCOL_VERSION + 41;
        let body = format!(
            "{{\"status\":\"ok\",\"app\":\"{}\",\"bridge_protocol\":{}}}",
            BRIDGE_APP_IDENTITY, other
        );
        let probe = classify_health_body(&body);
        assert!(!probe.is_adoptable());
        assert_eq!(probe, BridgeProbe::IncompatibleProtocol(other));
    }

    #[test]
    fn non_json_response_is_rejected() {
        let probe = classify_health_body("<html><body>hello</body></html>");
        assert!(!probe.is_adoptable());
        assert!(matches!(probe, BridgeProbe::NotOmniCovas(_)));
    }

    #[test]
    fn omnicovas_reporting_non_ok_status_is_not_adopted() {
        let body = format!(
            "{{\"status\":\"starting\",\"app\":\"{}\",\"bridge_protocol\":{}}}",
            BRIDGE_APP_IDENTITY, BRIDGE_PROTOCOL_VERSION
        );
        let probe = classify_health_body(&body);
        assert!(!probe.is_adoptable());
        assert!(matches!(probe, BridgeProbe::Malformed(_)));
    }

    #[test]
    fn closed_port_is_not_listening() {
        // Bind then drop to obtain a port that is almost certainly free.
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();
        drop(listener);

        assert_eq!(
            probe_local_bridge(u64::from(port)),
            BridgeProbe::NotListening
        );
    }

    /// End-to-end negative test: a generic TCP listener that accepts a
    /// connection but is not an OmniCOVAS bridge must never be adopted.
    #[test]
    fn generic_tcp_listener_is_never_adopted() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();

        let handle = thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut scratch = [0_u8; 1024];
                let _ = stream.read(&mut scratch);
                let payload =
                    "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nPONG";
                let _ = stream.write_all(payload.as_bytes());
            }
        });

        let probe = probe_local_bridge(u64::from(port));
        let _ = handle.join();

        assert!(
            !probe.is_adoptable(),
            "a generic listener must not be adopted, got {probe:?}"
        );
    }

    #[test]
    fn http_response_splitting_extracts_code_and_body() {
        let raw = "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}";
        let (code, body) = split_http_response(raw).expect("split");
        assert_eq!(code, 200);
        assert_eq!(body, "{}");
    }

    #[test]
    fn ready_line_port_parsing_is_preserved() {
        assert_eq!(
            parse_ready_port_from_line("{\"status\":\"ready\",\"port\":51119}"),
            Some(51119)
        );
        assert_eq!(
            parse_ready_port_from_line("Ready signal emitted: port=63330"),
            Some(63330)
        );
        assert_eq!(parse_ready_port_from_line("unrelated log line"), None);
    }
}
