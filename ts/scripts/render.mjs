// Dev helper (contract §5.4.1, not a product surface): render scene files through the built port.
//   node ts/scripts/render.mjs scene.json [more.json ...] outdir
// writes <outdir>/<name>.svg (scene layers) and <outdir>/<name>.json (dumps + newline) per scene.
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
for (const path of args.slice(0, -1)) {
  const name = basename(path).replace(/\.json$/, "");
  const scene = load_scene_text(readFileSync(path, "utf-8"));
  const out = render(scene);
  writeFileSync(join(outdir, `${name}.svg`), out.svg, "utf-8");
  writeFileSync(join(outdir, `${name}.json`), dumps(out.geometry) + "\n", "utf-8");
}
