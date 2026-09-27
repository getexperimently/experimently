// Harness: the React Native SDK's own hashUser.
//
// The package ships TypeScript source (package.json "main": src/index.ts) and
// no build, so this loads that source with node's type stripping. It imports
// src/hash.ts rather than src/index.ts because the index also pulls in the
// client, AsyncStorage and React Native, none of which load under node; the
// check below makes sure the index still re-exports this very hashUser.
//
// Reads {"inputs": [[userId, flagKey], ...]} on stdin and prints
// {"hashes": [...], "md5_hex": null}; hash_contract.py does the comparing.
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const sdkRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../sdk/react-native");
const pkg = JSON.parse(readFileSync(join(sdkRoot, "package.json"), "utf8"));
const index = readFileSync(join(sdkRoot, pkg.main), "utf8");
if (!/^export \{ hashUser \} from '\.\/hash';$/m.test(index)) {
  console.error(`${pkg.main} no longer re-exports hashUser from './hash'; update this harness`);
  process.exit(1);
}
const { hashUser } = await import(pathToFileURL(join(sdkRoot, "src/hash.ts")).href);

const { inputs } = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(
  JSON.stringify({ hashes: inputs.map(([u, f]) => hashUser(u, f)), md5_hex: null })
);
