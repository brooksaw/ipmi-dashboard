/**
 * fan_control.js — fan preset buttons (including Auto) and manual zone sliders.
 */

const FanControl = (() => {

  function _apiPost(serverId, body) {
    return fetch(`/api/fans/${serverId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function initServer(serverId) {
    const card = document.querySelector(`[data-server="${serverId}"]`);
    if (!card) return;

    const presetBtns = card.querySelectorAll(".btn-preset");
    const sliders    = card.querySelectorAll("input[data-zone]");
    const applyBtn   = card.querySelector(".btn-apply-fan");

    // Highlight Auto by default on load
    const autoBtn = card.querySelector('[data-preset="auto"]');
    if (autoBtn) autoBtn.classList.add("active");

    presetBtns.forEach(btn => {
      btn.addEventListener("click", async () => {
        const preset = btn.dataset.preset;
        presetBtns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        try {
          const res = await _apiPost(serverId, { preset });
          if (!res.ok) throw new Error(await res.text());
          const data = await res.json();
          if (preset === "auto") {
            Dashboard.toast(`${serverId}: auto fan control enabled`, "ok");
          } else {
            _setSlider(card, 0, data.settings.zone0);
            const z1 = card.querySelector("input[data-zone='1']");
            if (z1) _setSlider(card, 1, data.settings.zone1);
            Dashboard.toast(`${serverId}: fan preset "${preset}" applied`, "ok");
          }
        } catch (err) {
          Dashboard.toast(`Fan error: ${err.message}`, "err");
        }
      });
    });

    sliders.forEach(slider => {
      const zone = slider.dataset.zone;
      const display = card.querySelector(`.zone-value[data-zone-display="${zone}"]`);
      if (display) slider.addEventListener("input", () => { display.textContent = slider.value + "%"; });
    });

    if (applyBtn) {
      applyBtn.addEventListener("click", async () => {
        presetBtns.forEach(b => b.classList.remove("active"));
        const zone0 = card.querySelector("input[data-zone='0']");
        const zone1 = card.querySelector("input[data-zone='1']");

        try {
          if (zone0) {
            const r0 = await _apiPost(serverId, { zone: 0, duty: parseInt(zone0.value) });
            if (!r0.ok) throw new Error(await r0.text());
          }
          if (zone1) {
            const r1 = await _apiPost(serverId, { zone: 1, duty: parseInt(zone1.value) });
            if (!r1.ok) throw new Error(await r1.text());
          }
          Dashboard.toast(`${serverId}: manual fan zones applied (auto disabled)`, "ok");
        } catch (err) {
          Dashboard.toast(`Fan error: ${err.message}`, "err");
        }
      });
    }
  }

  function _setSlider(card, zone, value) {
    const slider  = card.querySelector(`input[data-zone="${zone}"]`);
    const display = card.querySelector(`.zone-value[data-zone-display="${zone}"]`);
    if (slider) slider.value = value;
    if (display) display.textContent = value + "%";
  }

  return { initServer };
})();
