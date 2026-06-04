use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{Emitter, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

const OVERLAY_LABEL: &str = "overlay";
const HOTKEY: &str = "Ctrl+Shift+O";

/// Initialize the overlay window and register the Ctrl+Shift+O global hotkey.
///
/// Hotkey failure is logged but does not crash the app — overlay still works
/// via show/hide commands from JS events.
pub fn init_overlay(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let handle = app.clone();

    let shortcut: Shortcut = HOTKEY.parse().map_err(|e| {
        log::error!("Failed to parse overlay hotkey '{}': {:?}", HOTKEY, e);
        format!("hotkey parse error: {:?}", e)
    })?;

    app.global_shortcut()
        .on_shortcut(shortcut, move |_app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                toggle_click_through(&handle);
            }
        })
        .map_err(|e| {
            log::error!("Failed to register overlay hotkey '{}': {:?}", HOTKEY, e);
            format!("hotkey register error: {:?}", e)
        })?;

    log::info!("Overlay initialized; {} registered.", HOTKEY);
    Ok(())
}

/// Toggle the click-through state on the overlay window and emit the new state to JS.
fn toggle_click_through(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<OverlayState>() {
        let current = state.click_through.load(Ordering::SeqCst);
        let next = !current;
        state.click_through.store(next, Ordering::SeqCst);

        if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
            if let Err(e) = window.set_ignore_cursor_events(next) {
                log::error!("Failed to set click-through to {}: {:?}", next, e);
            }
        }

        if let Err(e) = app.emit("overlay:click_through_toggled", next) {
            log::error!("Failed to emit click_through_toggled: {:?}", e);
        }

        log::info!("Overlay click-through toggled to {}", next);
    } else {
        log::error!("OverlayState not managed — cannot toggle click-through");
    }
}

/// Show the overlay window. Returns an error if the window cannot be found.
#[tauri::command]
pub async fn show_overlay(app: tauri::AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(OVERLAY_LABEL)
        .ok_or_else(|| format!("Overlay window '{}' not found", OVERLAY_LABEL))?;

    window
        .show()
        .map_err(|e| format!("Failed to show overlay: {:?}", e))?;
    log::debug!("Overlay shown.");
    Ok(())
}

/// Hide the overlay window. Returns an error if the window cannot be found.
#[tauri::command]
pub async fn hide_overlay(app: tauri::AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(OVERLAY_LABEL)
        .ok_or_else(|| format!("Overlay window '{}' not found", OVERLAY_LABEL))?;

    window
        .hide()
        .map_err(|e| format!("Failed to hide overlay: {:?}", e))?;
    log::debug!("Overlay hidden.");
    Ok(())
}

/// Global state for the overlay window.
pub struct OverlayState {
    pub click_through: AtomicBool,
}

impl Default for OverlayState {
    fn default() -> Self {
        OverlayState {
            click_through: AtomicBool::new(true),
        }
    }
}
