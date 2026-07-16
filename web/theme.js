"use strict";

(() => {
  const allowed = new Set(["workshop", "editorial", "night"]);
  let selected = "workshop";
  try {
    const saved = window.localStorage.getItem("comfy-anima-theme");
    if (allowed.has(saved)) selected = saved;
  } catch (_error) {
    // Storage can be disabled; the default theme remains fully usable.
  }
  document.documentElement.dataset.theme = selected;
})();
