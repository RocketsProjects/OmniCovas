mod overlay;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::thread;
use tauri::{Emitter, Manager};
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct BridgeInfo {
    port: u64,
    http_base: String,
    ws_base: String,
}

static BRIDGE_INFO: OnceLock<Mutex<Option<BridgeInfo>>> = OnceLock::new();

fn bridge_store() -> &'static Mutex<Option<BridgeInfo>> {
    BRIDGE_INFO.get_or_init(|| Mutex::new(None))
}

#[tauri::command]
fn get_bridge_info() -> Option<BridgeInfo> {
    bridge_store().lock().ok()?.clone()
}

fn record_bridge_ready(app_handle: &tauri::AppHandle, line: &str) {
    println!("[omnicovas-core] {}", line);

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

                app_handle
                    .emit("bridge-ready", info)
                    .expect("failed to emit bridge-ready");

                println!("OmniCOVAS bridge ready on port {}", port);
            }
        }
    }
}

fn log_core_stderr(bytes: &[u8]) {
    let text = String::from_utf8_lossy(bytes);
    for line in text.lines() {
        eprintln!("[omnicovas-core:stderr] {}", line);
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
    });
}

fn launch_packaged_sidecar(app_handle: tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let sidecar_command = app_handle.shell().sidecar("omnicovas-sidecar")?;
    let (mut rx, child) = sidecar_command.spawn()?;

    tauri::async_runtime::spawn(async move {
        let _child = child;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let text = String::from_utf8_lossy(&bytes);
                    for line in text.lines() {
                        record_bridge_ready(&app_handle, line);
                    }
                }
                CommandEvent::Stderr(bytes) => log_core_stderr(&bytes),
                CommandEvent::Error(error) => {
                    eprintln!("[omnicovas-core] sidecar error: {}", error);
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!("[omnicovas-core] sidecar terminated: {:?}", payload);
                }
                _ => {}
            }
        }
    });

    Ok(())
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

            if tauri::is_dev() {
                launch_dev_python_core(app_handle);
            } else {
                launch_packaged_sidecar(app_handle)?;
            }

            Ok(())
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
