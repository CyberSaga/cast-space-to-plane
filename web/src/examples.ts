/**
 * The bundled examples (contract §5.4.10): `examples/*.json` of the repository, embedded at build time by vite
 * (no copying, no fetch, no server).
 */

const modules = import.meta.glob("../../examples/*.json", { eager: true, import: "default" }) as Record<string, unknown>;

export interface Example {
  name: string;
  data: unknown;
}

export const EXAMPLES: readonly Example[] = Object.entries(modules)
  .map(([path, data]) => ({ name: path.slice(path.lastIndexOf("/") + 1).replace(/\.json$/, ""), data }))
  .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
