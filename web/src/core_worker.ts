/**
 * The core worker of the web UI (contract §5.4.11): `core_engine.ts` on the worker's global scope. Started by `main.ts`
 * as `new Worker(new URL("./core_worker.ts", import.meta.url), { type: "module" })`; the messages are in
 * `core_client.ts`. It imports no DOM code, no three.js and no CSS.
 */

import type { FromWorker, ToWorker } from "./core_client.js";
import { CoreEngine } from "./core_engine.js";

const engine = new CoreEngine(
  (m: FromWorker, transfer: ArrayBuffer[] = []) => self.postMessage(m, { transfer }),
  (fn) => {
    const id = setTimeout(fn, 0);
    return () => clearTimeout(id);
  },
);

self.onmessage = (ev: MessageEvent) => engine.handle(ev.data as ToWorker);
