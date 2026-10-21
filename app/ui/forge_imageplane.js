// Create > Free Image Plane (owner 2026-10-21: "add free imagine plaine so we can improt png or jpeg"). A PNG,
// JPEG or WebP picture becomes a plane in the scene - imagePlane1, imagePlane2 ... - sized to the picture's own
// proportions, standing up facing the view you are looking through (front / persp: the XY plane, side: YZ, top:
// lying flat). It is an ordinary scene node: move / rotate / scale it, hide it, put it on a display layer with R so
// you can model over it without clicking it, change its Alpha Gain in the Channel Box. Drop a picture straight
// onto the viewport to do the same. Nothing leaves the computer: the picture is read in the window.
"use strict";

const FORGE_IMAGE_TYPES = /^image\/(png|jpe?g|webp)$/i;
const FORGE_IMAGE_EXT = /\.(png|jpe?g|webp)$/i;

function forgeImagePlaneIsImage(file) {
  return !!(file && (FORGE_IMAGE_TYPES.test(file.type || "") || FORGE_IMAGE_EXT.test(file.name || "")));
}

// pick a file, then make the plane (File > Import picture, Create > Free Image Plane)
function forgeImagePlanePick() {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = "image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp";
  inp.addEventListener("change", () => { const f = inp.files && inp.files[0]; if (f) forgeImagePlaneFromFile(f); });
  inp.click();
  return "Pick a PNG or JPEG for the image plane.";
}

function forgeImagePlaneFromFile(file) {
  if (!forgeImagePlaneIsImage(file)) { if (typeof forgeSay === "function") forgeSay("An image plane takes a PNG, JPEG or WebP picture.", true); return Promise.resolve(null); }
  return new Promise((resolve) => {
    const rd = new FileReader();
    rd.onload = () => resolve(forgeImagePlaneAdd(String(rd.result), (file.name || "").replace(/\.[^.]+$/, "")));
    rd.onerror = () => { if (typeof forgeSay === "function") forgeSay("Could not read " + (file.name || "the picture") + ".", true); resolve(null); };
    rd.readAsDataURL(file);
  });
}

// url: a data: or blob: URL (or any same-origin picture). Resolves to the new node.
function forgeImagePlaneAdd(url, label) {
  const v = typeof forge !== "undefined" && forge.view;
  if (!v || !v.THREE || !v.tree || !v.tree.api) return Promise.resolve(null);
  const THREE = v.THREE, api = v.tree.api;
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth || 1, h = img.naturalHeight || 1;
      const tex = new THREE.Texture(img);
      tex.needsUpdate = true;
      if ("colorSpace" in tex && THREE.SRGBColorSpace) tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = 4;
      // the plane: as tall as the scene's size (at least 2 grid units), as wide as the picture's proportions
      const size = Math.max(2, (v.size || 1) * 1.5);
      const geo = new THREE.PlaneGeometry(size * (w / h), size);
      const mat = new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide, toneMapped: false });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.renderOrder = -1;                                // drawn first: models in front of it stay crisp
      const make = () => {
        const n = api.addImagePlane("imagePlane", mesh, { w, h, label: label || "" });
        // face the view you are in (the pro free image plane is made in the view you work in)
        if (v.cam === "top") n.grp.rotation.set(-Math.PI / 2, 0, 0);
        else if (v.cam === "side") n.grp.rotation.set(0, Math.PI / 2, 0);
        n.grp.updateMatrixWorld(true);
        return n;
      };
      const n = api.undoChunk ? (api.undoChunk("free image plane", make) || null) : make();
      const made = n || api.list().filter((x) => x.kind === "imagePlane").pop();
      api.build ? api.build() : (v.tree.build && v.tree.build());
      v.dirty = true;
      if (typeof forgeSay === "function") forgeSay((made ? made.name : "Image plane") + ": " + w + " x " + h + " px. Put it on a layer with R to model over it without clicking it.");
      resolve(made);
    };
    img.onerror = () => { if (typeof forgeSay === "function") forgeSay("That picture could not be opened.", true); resolve(null); };
    img.src = url;
  });
}

// drop a picture on the viewport = a free image plane where you look
document.addEventListener("dragover", (e) => {
  const stage = document.getElementById("forge-stage");
  if (!stage || !stage.contains(e.target) || !e.dataTransfer || ![...(e.dataTransfer.types || [])].includes("Files")) return;
  e.preventDefault(); e.dataTransfer.dropEffect = "copy"; stage.classList.add("forge-drop-image");
});
document.addEventListener("dragleave", (e) => {
  const stage = document.getElementById("forge-stage");
  if (stage && (!e.relatedTarget || !stage.contains(e.relatedTarget))) stage.classList.remove("forge-drop-image");
});
document.addEventListener("drop", (e) => {
  const stage = document.getElementById("forge-stage");
  if (!stage || !stage.contains(e.target) || !e.dataTransfer) return;
  stage.classList.remove("forge-drop-image");
  const files = [...(e.dataTransfer.files || [])].filter(forgeImagePlaneIsImage);
  if (!files.length) return;
  e.preventDefault(); e.stopPropagation();
  (async () => { for (const f of files) await forgeImagePlaneFromFile(f); })();
});

// the command (menus, hotbox, command line): imagePlane
if (typeof FORGE_PRO_CMDS !== "undefined" && !FORGE_PRO_CMDS.imagePlane) {
  FORGE_PRO_CMDS.imagePlane = ["Free Image Plane", () => forgeImagePlanePick()];
}
