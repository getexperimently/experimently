// Harness: the edge SDK's own hashUser and md5Hex, from the package's "."
// export (dist/index.js, built by `npm run build`).
// Reads {"inputs": [[userId, flagKey], ...]} on stdin and prints
// {"hashes": [...], "md5_hex": [...]}; hash_contract.py does the comparing.
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const sdkRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../sdk/edge");
const pkg = JSON.parse(readFileSync(join(sdkRoot, "package.json"), "utf8"));
const sdk = await import(pathToFileURL(join(sdkRoot, pkg.exports["."].default)).href);

const { inputs } = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(
  JSON.stringify({
    hashes: inputs.map(([u, f]) => sdk.hashUser(u, f)),
    md5_hex: inputs.map(([u, f]) => sdk.md5Hex(`${u}:${f}`)),
  })
);
