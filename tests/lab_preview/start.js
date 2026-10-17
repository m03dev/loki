"use strict";
Promise.all([loadLab(), loadUserTools()]).then(() => { window.previewReady = true; })
  .catch((e) => { window.previewError = String(e); window.previewReady = true; });
