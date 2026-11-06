use serde::Serialize;
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{Emitter, Manager, PhysicalPosition, PhysicalSize};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

const OVERLAY_LABEL: &str = "overlay";
const HOTKEY: &str = "Ctrl+Shift+O";

/// Initialize the overlay window and register the Ctrl+Shift+O global hotkey.
///
/// The overlay is created visible (see tauri.conf.json) and is made
/// click-through and parked at 1x1 here. On Windows only a show during the
/// creation of an unfocused window is non-activating: tao uses
/// SW_SHOWNOACTIVATE then, and from 0.37 it clears that marker when creation
/// ends, so a later first show() would be SW_SHOW and take the foreground.
/// The overlay is never hidden and re-shown afterwards: it is moved, sized
/// and parked instead, which never activates it or takes focus from the game.
///
/// Hotkey failure is logged but does not crash the app — overlay still works
/// via present/park commands from JS.
pub fn init_overlay(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        if let Err(e) = window.set_ignore_cursor_events(true) {
            log::error!("Failed to make overlay click-through at startup: {:?}", e);
        }
        if let Err(e) = park(&window) {
            log::warn!("Overlay could not be parked at startup: {}", e);
        }
    }

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

fn apply_click_through(app: &tauri::AppHandle, enabled: bool) -> Result<(), String> {
    if let Some(state) = app.try_state::<OverlayState>() {
        state.click_through.store(enabled, Ordering::SeqCst);
    }
    let window = app
        .get_webview_window(OVERLAY_LABEL)
        .ok_or_else(|| format!("Overlay window '{}' not found", OVERLAY_LABEL))?;
    window
        .set_ignore_cursor_events(enabled)
        .map_err(|e| format!("Failed to set click-through to {}: {:?}", enabled, e))
}

/// Toggle the click-through state on the overlay window and emit the new state to JS.
fn toggle_click_through(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<OverlayState>() {
        let next = !state.click_through.load(Ordering::SeqCst);
        if let Err(e) = apply_click_through(app, next) {
            log::error!("{}", e);
        }

        if let Err(e) = app.emit("overlay:click_through_toggled", next) {
            log::error!("Failed to emit click_through_toggled: {:?}", e);
        }

        log::info!("Overlay click-through toggled to {}", next);
    } else {
        log::error!("OverlayState not managed — cannot toggle click-through");
    }
}

/// Apply the persisted click-through choice natively (called by the overlay
/// page after it loads settings).
#[tauri::command]
pub async fn set_overlay_click_through(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    apply_click_through(&app, enabled)
}

/// A monitor or window rectangle in physical pixels.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

/// Where the overlay was placed, reported back to the page for receipts.
#[derive(Clone, Debug, Serialize)]
pub struct Placement {
    pub window: Rect,
    pub monitor: Rect,
    pub scale: f64,
    pub monitor_name: Option<String>,
}

/// Fit a card of `logical_w` x `logical_h` CSS pixels on `monitor`.
///
/// Logical sizes are converted to physical pixels exactly once, with the
/// target monitor's scale factor. Anchors keep clear of the centre reticle
/// and the lower instrument band: top anchors sit about 9% down, bottom
/// anchors about 18% up, 32 logical px from the side edge. On ultrawide
/// monitors (wider than 21:9-ish) the horizontal span is limited to a
/// centred 16:9 region so a warning is not sent to the far periphery.
/// These are starting placements, not a claim that the region is clear in
/// every cockpit or HUD configuration.
pub fn compute_placement(
    monitor: Rect,
    scale: f64,
    anchor: &str,
    logical_w: f64,
    logical_h: f64,
) -> Rect {
    let scale = if scale.is_finite() && scale > 0.0 {
        scale
    } else {
        1.0
    };
    let clamp_logical = |v: f64, max: f64| {
        if v.is_finite() {
            v.clamp(1.0, max)
        } else {
            1.0
        }
    };
    let mon_w = monitor.width.max(1) as i64;
    let mon_h = monitor.height.max(1) as i64;
    let w = ((clamp_logical(logical_w, 2400.0) * scale).round() as i64).clamp(1, mon_w);
    let h = ((clamp_logical(logical_h, 1600.0) * scale).round() as i64).clamp(1, mon_h);

    let (span_x, span_w) = if mon_w * 100 > mon_h * 210 {
        let span = ((mon_h as f64) * 16.0 / 9.0).round() as i64;
        let span = span.min(mon_w);
        (monitor.x as i64 + (mon_w - span) / 2, span)
    } else {
        (monitor.x as i64, mon_w)
    };
    let inset = (32.0 * scale).round() as i64;
    let top = monitor.y as i64 + ((mon_h as f64) * 0.09).round() as i64;
    let bottom = monitor.y as i64 + mon_h - h - ((mon_h as f64) * 0.18).round() as i64;

    let (x, y) = match anchor {
        "tl" | "top-left" => (span_x + inset, top),
        "bl" | "bottom-left" => (span_x + inset, bottom),
        "br" | "bottom-right" => (span_x + span_w - w - inset, bottom),
        // "center" historically meant the middle of a small fixed window;
        // the middle of the screen is the reticle, so it maps to top-centre.
        "tc" | "top-center" | "center" => (span_x + (span_w - w) / 2, top),
        _ => (span_x + span_w - w - inset, top),
    };
    let min_x = monitor.x as i64;
    let min_y = monitor.y as i64;
    Rect {
        x: x.clamp(min_x, min_x + mon_w - w) as i32,
        y: y.clamp(min_y, min_y + mon_h - h) as i32,
        width: w as u32,
        height: h as u32,
    }
}

/// The primary monitor (where a fullscreen game normally runs), else the
/// overlay's current monitor, else the first available one.
fn target_monitor(window: &tauri::WebviewWindow) -> Result<tauri::Monitor, String> {
    if let Ok(Some(m)) = window.primary_monitor() {
        return Ok(m);
    }
    if let Ok(Some(m)) = window.current_monitor() {
        return Ok(m);
    }
    window
        .available_monitors()
        .map_err(|e| format!("No monitor available: {:?}", e))?
        .into_iter()
        .next()
        .ok_or_else(|| "No monitor available".to_string())
}

fn place(
    window: &tauri::WebviewWindow,
    anchor: &str,
    logical_w: f64,
    logical_h: f64,
) -> Result<Placement, String> {
    let monitor = target_monitor(window)?;
    let mon = Rect {
        x: monitor.position().x,
        y: monitor.position().y,
        width: monitor.size().width,
        height: monitor.size().height,
    };
    let scale = monitor.scale_factor();
    let rect = compute_placement(mon, scale, anchor, logical_w, logical_h);
    // Physical units from the target monitor: no second DPI conversion.
    window
        .set_size(PhysicalSize::new(rect.width, rect.height))
        .map_err(|e| format!("Failed to size overlay: {:?}", e))?;
    window
        .set_position(PhysicalPosition::new(rect.x, rect.y))
        .map_err(|e| format!("Failed to place overlay: {:?}", e))?;
    if !window.is_visible().unwrap_or(false) {
        // Only reached once per run (see init_overlay): non-activating.
        window
            .show()
            .map_err(|e| format!("Failed to show overlay: {:?}", e))?;
    }
    Ok(Placement {
        window: rect,
        monitor: mon,
        scale,
        monitor_name: monitor.name().cloned(),
    })
}

fn park(window: &tauri::WebviewWindow) -> Result<Placement, String> {
    place(window, "tr", 1.0, 1.0)
}

fn overlay_window(app: &tauri::AppHandle) -> Result<tauri::WebviewWindow, String> {
    app.get_webview_window(OVERLAY_LABEL)
        .ok_or_else(|| format!("Overlay window '{}' not found", OVERLAY_LABEL))
}

/// Fit the overlay around a card and place it at the anchor, without
/// activating the window.
#[tauri::command]
pub async fn present_overlay(
    app: tauri::AppHandle,
    anchor: String,
    width: f64,
    height: f64,
) -> Result<Placement, String> {
    let window = overlay_window(&app)?;
    let placement = place(&window, &anchor, width, height)?;
    log::debug!("Overlay presented: {:?}", placement.window);
    Ok(placement)
}

/// Empty state: shrink to 1x1 at the anchor instead of hiding.
#[tauri::command]
pub async fn park_overlay(app: tauri::AppHandle) -> Result<Placement, String> {
    park(&overlay_window(&app)?)
}

/// Show the overlay window (kept for the Banner Test Center commands). Never
/// re-shows an already visible window, so it cannot activate it.
#[tauri::command]
pub async fn show_overlay(app: tauri::AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(OVERLAY_LABEL)
        .ok_or_else(|| format!("Overlay window '{}' not found", OVERLAY_LABEL))?;

    if !window.is_visible().unwrap_or(false) {
        window
            .show()
            .map_err(|e| format!("Failed to show overlay: {:?}", e))?;
    }
    log::debug!("Overlay shown.");
    Ok(())
}

/// "Hide" the overlay: park it rather than hiding, because showing a hidden
/// window again would activate it.
#[tauri::command]
pub async fn hide_overlay(app: tauri::AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(OVERLAY_LABEL)
        .ok_or_else(|| format!("Overlay window '{}' not found", OVERLAY_LABEL))?;

    park(&window)?;
    log::debug!("Overlay parked.");
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

#[cfg(test)]
mod tests {
    use super::*;

    const HD: Rect = Rect {
        x: 0,
        y: 0,
        width: 1920,
        height: 1080,
    };

    #[test]
    fn top_right_at_1080p_matches_proposal() {
        let r = compute_placement(HD, 1.0, "tr", 408.0, 116.0);
        assert_eq!(r.width, 408);
        assert_eq!(r.x, 1920 - 408 - 32);
        assert_eq!(r.y, 97);
    }

    #[test]
    fn scale_converts_logical_once() {
        let qhd = Rect {
            x: 0,
            y: 0,
            width: 2560,
            height: 1440,
        };
        let r = compute_placement(qhd, 1.25, "tr", 408.0, 116.0);
        assert_eq!((r.width, r.height), (510, 145));
        assert_eq!(r.x, 2560 - 510 - 40);
    }

    #[test]
    fn ultrawide_uses_centred_span() {
        let uw = Rect {
            x: 0,
            y: 0,
            width: 3440,
            height: 1440,
        };
        let r = compute_placement(uw, 1.0, "tr", 400.0, 100.0);
        let span = 2560;
        let span_x = (3440 - span) / 2;
        assert_eq!(r.x, span_x + span - 400 - 32);
    }

    #[test]
    fn secondary_monitor_offsets_and_clamps() {
        let left = Rect {
            x: -1920,
            y: 0,
            width: 1920,
            height: 1080,
        };
        let r = compute_placement(left, 1.0, "tl", 5000.0, 5000.0);
        assert!(r.x >= -1920 && r.x + r.width as i32 <= 0);
        assert!(r.y >= 0 && r.y + r.height as i32 <= 1080);
    }

    #[test]
    fn legacy_center_never_covers_reticle() {
        let r = compute_placement(HD, 1.0, "center", 400.0, 100.0);
        assert_eq!(r.x, (1920 - 400) / 2);
        assert!(r.y + (r.height as i32) < 540);
    }

    #[test]
    fn invalid_inputs_are_bounded() {
        let r = compute_placement(HD, f64::NAN, "bogus", f64::INFINITY, -3.0);
        assert!(r.width >= 1 && r.height >= 1);
        assert!(r.x >= 0 && r.y >= 0);
    }

    #[test]
    fn bottom_anchor_stays_above_instrument_band() {
        let r = compute_placement(HD, 1.0, "br", 400.0, 100.0);
        assert!(r.y + (r.height as i32) <= 1080 - 194);
    }
}
