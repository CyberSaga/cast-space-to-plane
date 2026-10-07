// Dev helper (contract §5.4.1, not a product surface): render scene files through the built port.
//   node ts/scripts/render.mjs scene.json [more.json ...] outdir
// writes <outdir>/<name>.svg (scene layers) and <outdir>/<name>.json (dumps + newline) per scene. A scene the port
// cannot load or render (SceneError, or a phase-2 part that has not landed yet) gets <outdir>/<name>.error (the
// message) instead, the remaining scenes are still rendered, and the exit status is 1.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";

const here = new URL(".", import.meta.url);
const { load_scene_text } = await import(new URL("../build/src/scene.js", here).href);
const { render } = await import(new URL("../build/src/pipeline.js", here).href);
const { dumps } = await import(new URL("../build/src/output/geometry_json.js", here).href);

const args = process.argv.slice(2);
if (args.length < 2) {
  console.error("usage: node ts/scripts/render.mjs scene.json [more.json ...] outdir");
  process.exit(2);
}
const outdir = args[args.length - 1];
mkdirSync(outdir, { recursive: true });
let failed = 0;
for (const path of args.slice(0, -1)) {
  const name = basename(path).replace(/\.json$/, "");
  let out;
  try {
    out = render(load_scene_text(readFileSync(path, "utf-8")));
  } catch (e) {
    const message = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
    writeFileSync(join(outdir, `${name}.error`), message + "\n", "utf-8");
    console.error(`${path}: ${message}`);
    failed += 1;
    continue;
  }
  writeFileSync(join(outdir, `${name}.svg`), out.svg, "utf-8");
  writeFileSync(join(outdir, `${name}.json`), dumps(out.geometry) + "\n", "utf-8");
}
if (failed > 0) process.exit(1);
