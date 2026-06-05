/**
 * Phase 3 Week 13 — First-Run Onboarding Controller
 *
 * Manages the three-path onboarding flow:
 *  A. Easy Mode (60-second preset)
 *  B. Custom Setup (5-15 minute wizard)
 *  C. Power User (full Settings + Privacy)
 *
 * Startup sequence: shell.js checks /week13/license/status and
 * /week13/onboarding/status after bridge discovery.  The license gate fires
 * first; the path-selection wizard is only reachable after license acceptance.
 */

class OnboardingController {
  constructor() {
    this.currentPath = null;
    this.customStepIndex = 0;
    this.customSteps = [
      "preset",
      "ai",
      "privacy",
      "output",
      "overlay",
    ];
    this.powerUserSeen = {
      settings: false,
      privacy: false,
    };
    this._licenseAccepted = false;
    this.init();
  }

  get apiBase() {
    if (window.Shell?.httpBase) return window.Shell.httpBase;
    if (window.OMNICOVAS_PORT) return `http://127.0.0.1:${window.OMNICOVAS_PORT}`;
    return null;
  }

  apiUrl(path) {
    const base = this.apiBase;
    return base ? `${base}${path}` : null;
  }

  init() {
    this.bindLicenseButtons();
    this.bindPathButtons();
    this.bindStepButtons();
  }

  /** Show the wizard starting at the license screen. */
  showLicenseScreen() {
    const container = document.getElementById("onboarding-container");
    if (container) container.style.display = "flex";
    this._loadLicenseText();
    this.hideAll();
    document.getElementById("onboarding-license").style.display = "block";
    document.getElementById("onboarding-license-agree-btn")?.focus();
  }

  /** Show the wizard starting at the path-selection screen (license already accepted). */
  show() {
    const container = document.getElementById("onboarding-container");
    if (container) container.style.display = "flex";
    this.showPathSelection();
    const firstControl = document.querySelector(
      "#onboarding-path-selection .path-button, #onboarding-path-selection button"
    );
    if (firstControl) firstControl.focus();
  }

  async _loadLicenseText() {
    const el = document.getElementById("onboarding-license-text");
    if (!el) return;
    try {
      const res = await fetch("/assets/legal/LICENSE.md");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      el.textContent = text;
    } catch (err) {
      el.textContent = "License text could not be loaded. Review LICENSE.md in the application directory before agreeing.";
      console.warn("[Onboarding] Failed to load bundled license:", err);
    }
  }

  bindLicenseButtons() {
    const checkbox = document.getElementById("onboarding-license-checkbox");
    const agreeBtn = document.getElementById("onboarding-license-agree-btn");
    const declineBtn = document.getElementById("onboarding-license-decline-btn");

    checkbox?.addEventListener("change", () => {
      if (agreeBtn) agreeBtn.disabled = !checkbox.checked;
    });

    agreeBtn?.addEventListener("click", () => {
      if (!checkbox?.checked) return;
      this._acceptLicense();
    });

    declineBtn?.addEventListener("click", () => {
      this._declineLicense();
    });
  }

  showPathSelection() {
    this.hideAll();
    document.getElementById("onboarding-path-selection").style.display = "block";
  }

  hideAll() {
    const licenseEl = document.getElementById("onboarding-license");
    if (licenseEl) licenseEl.style.display = "none";
    document.getElementById("onboarding-path-selection").style.display = "none";
    document.getElementById("onboarding-easy-mode").style.display = "none";
    document.getElementById("onboarding-custom-mode").style.display = "none";
    document.getElementById("onboarding-power-user").style.display = "none";
  }

  async _acceptLicense() {
    const url = this.apiUrl("/week13/license/accept");
    if (!url) {
      console.warn("[Onboarding] Bridge not ready; cannot persist license acceptance.");
      return;
    }
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this._licenseAccepted = true;
      this.show();
    } catch (err) {
      console.error("[Onboarding] Failed to persist license acceptance:", err);
    }
  }

  _declineLicense() {
    const invoke = window.__TAURI__?.core?.invoke;
    if (typeof invoke === "function") {
      invoke("plugin:window|close").catch(() => {});
    } else {
      window.close();
    }
  }

  bindPathButtons() {
    // Path A: Easy Mode
    document.getElementById("path-easy-btn")?.addEventListener("click", () => {
      this.currentPath = "easy";
      this.showEasyMode();
    });

    // Path B: Custom Setup
    document.getElementById("path-custom-btn")?.addEventListener("click", () => {
      this.currentPath = "custom";
      this.showCustomStep(0);
    });

    // Path C: Power User
    document.getElementById("path-power-user-btn")?.addEventListener("click", () => {
      this.currentPath = "power";
      this.showPowerUser();
    });

    // Skip button (applies Easy Mode defaults)
    document.getElementById("onboarding-skip-btn")?.addEventListener("click", () => {
      this.completeOnboarding();
    });
  }

  // ── EASY MODE ──

  showEasyMode() {
    this.hideAll();
    document.getElementById("onboarding-easy-mode").style.display = "block";
    document.querySelector('input[name="easy-preset"]')?.focus();
  }

  bindStepButtons() {
    // Easy Mode
    document.getElementById("onboarding-easy-complete-btn")?.addEventListener("click", () => {
      const preset = document.querySelector('input[name="easy-preset"]:checked')?.value
        || "casual";
      this.completeWithPreset(preset);
    });

    document.getElementById("onboarding-easy-back-btn")?.addEventListener("click", () => {
      this.showPathSelection();
    });

    // Custom Mode — Preset step
    document.getElementById("onboarding-custom-preset-next-btn")?.addEventListener("click", () => {
      this.customStepIndex = 1;
      this.showCustomStep(1);
    });

    document.getElementById("onboarding-custom-preset-skip-btn")?.addEventListener("click", () => {
      this.customStepIndex = 1;
      this.showCustomStep(1);
    });

    // Custom Mode — AI step
    document.getElementById("onboarding-custom-ai-next-btn")?.addEventListener("click", () => {
      this.customStepIndex = 2;
      this.showCustomStep(2);
    });

    document.getElementById("onboarding-custom-ai-back-btn")?.addEventListener("click", () => {
      this.customStepIndex = 0;
      this.showCustomStep(0);
    });

    // Custom Mode — Privacy step
    document.getElementById("onboarding-custom-privacy-next-btn")?.addEventListener("click", () => {
      this.customStepIndex = 3;
      this.showCustomStep(3);
    });

    document.getElementById("onboarding-custom-privacy-back-btn")?.addEventListener("click", () => {
      this.customStepIndex = 1;
      this.showCustomStep(1);
    });

    // Custom Mode — Output step
    document.getElementById("onboarding-custom-output-next-btn")?.addEventListener("click", () => {
      this.customStepIndex = 4;
      this.showCustomStep(4);
    });

    document.getElementById("onboarding-custom-output-back-btn")?.addEventListener("click", () => {
      this.customStepIndex = 2;
      this.showCustomStep(2);
    });

    // Custom Mode — Overlay step
    document.getElementById("onboarding-custom-complete-btn")?.addEventListener("click", () => {
      this.completeCustomSetup();
    });

    document.getElementById("onboarding-custom-overlay-back-btn")?.addEventListener("click", () => {
      this.customStepIndex = 3;
      this.showCustomStep(3);
    });

    // Power User
    document.getElementById("onboarding-power-user-settings-btn")?.addEventListener("click", () => {
      this.powerUserSeen.settings = true;
      this.updatePowerUserProgress();
      // In a real app, navigate to /settings; here we simulate
      window.location.hash = "#/settings";
    });

    document.getElementById("onboarding-power-user-privacy-btn")?.addEventListener("click", () => {
      this.powerUserSeen.privacy = true;
      this.updatePowerUserProgress();
      // In a real app, navigate to /privacy
      window.location.hash = "#/privacy";
    });

    document.getElementById("onboarding-power-user-complete-btn")?.addEventListener("click", () => {
      this.completeOnboarding();
    });
  }

  showCustomStep(stepIndex) {
    const steps = [
      "onboarding-custom-preset",
      "onboarding-custom-ai",
      "onboarding-custom-privacy",
      "onboarding-custom-output",
      "onboarding-custom-overlay",
    ];

    this.hideAll();
    document.getElementById("onboarding-custom-mode").style.display = "block";

    // Hide all steps
    steps.forEach((stepId) => {
      const el = document.getElementById(stepId);
      if (el) el.style.display = "none";
    });

    // Show current step
    const currentStepId = steps[stepIndex];
    if (currentStepId) {
      document.getElementById(currentStepId).style.display = "block";
    }
  }

  completeWithPreset(preset) {
    this.savePreset(preset).then(() => {
      this.completeOnboarding();
    });
  }

  async completeCustomSetup() {
    const preset = document.querySelector('input[name="custom-preset"]:checked')?.value
      || "casual";
    const aiProvider = document.querySelector('input[name="custom-ai"]:checked')?.value
      || "null";
    const overlayAnchor = document.querySelector('input[name="custom-overlay"]:checked')?.value
      || "center";

    // Save privacy toggles
    const toggles = document.querySelectorAll(".privacy-toggle:checked");
    for (const toggle of toggles) {
      const key = toggle.dataset.toggle;
      await this.setPrivacyToggle(key, true);
    }

    // Save settings
    await this.saveSettings({
      preset,
      ai_provider: aiProvider,
      overlay: {
        anchor: overlayAnchor,
      },
    });

    this.completeOnboarding();
  }

  updatePowerUserProgress() {
    const settingsCheck = document.getElementById("power-user-settings-check");
    const privacyCheck = document.getElementById("power-user-privacy-check");
    const completeBtn = document.getElementById("onboarding-power-user-complete-btn");

    if (settingsCheck && this.powerUserSeen.settings) {
      settingsCheck.textContent = "✓ Command Center opened";
    }
    if (privacyCheck && this.powerUserSeen.privacy) {
      privacyCheck.textContent = "✓ Privacy & Security opened";
    }

    // Enable complete button only if both are seen
    if (completeBtn) {
      completeBtn.disabled = !(this.powerUserSeen.settings && this.powerUserSeen.privacy);
    }
  }

  showPowerUser() {
    this.hideAll();
    document.getElementById("onboarding-power-user").style.display = "block";
  }

  // ── API CALLS ──

  async savePreset(preset) {
    const url = this.apiUrl('/week13/settings');
    if (!url) return;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error("Failed to save preset:", err);
    }
  }

  async setPrivacyToggle(key, enabled) {
    const url = this.apiUrl(`/week13/privacy/toggles/${key}`);
    if (!url) return;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error(`Failed to set privacy toggle ${key}:`, err);
    }
  }

  async saveSettings(settings) {
    const url = this.apiUrl('/week13/settings');
    if (!url) return;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error("Failed to save settings:", err);
    }
  }

  async completeOnboarding() {
    const url = this.apiUrl('/week13/onboarding/complete');
    if (!url) return;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Hide onboarding and navigate to dashboard
      document.getElementById("onboarding-container").style.display = "none";
      window.location.hash = "#/dashboard";
    } catch (err) {
      console.error("Failed to complete onboarding:", err);
    }
  }
}

function _initOnboarding() {
  const controller = new OnboardingController();
  window.OmniOnboarding = {
    show: () => controller.show(),
    showLicenseScreen: () => controller.showLicenseScreen(),
  };
  // Drain pending license flag (shell.js resolved license check before this script loaded).
  if (window.__pendingLicenseShow) {
    window.__pendingLicenseShow = false;
    controller.showLicenseScreen();
  } else if (window.__pendingOnboardingShow) {
    // Drain onboarding flag only if no license gate is pending.
    window.__pendingOnboardingShow = false;
    controller.show();
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", _initOnboarding);
} else {
  _initOnboarding();
}

// Test hook for Vitest; keeps this browser-compatible without changing production module/script loading.
globalThis.__onboardingExports = { OnboardingController, _initOnboarding };
