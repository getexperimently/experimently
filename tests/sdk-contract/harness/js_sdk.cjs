// Harness: the JS SDK's own consistentHash and md5Hex, from the package's
// entry point (package.json "main": dist/index.js, built by `npm run build`).
// Reads {"inputs": [[userId, flagKey], ...]} on stdin and prints
// {"hashes": [...], "md5_hex": [...]}; hash_contract.py does the comparing.
const fs = require("fs");
const path = require("path");

const sdkRoot = path.resolve(__dirname, "../../../sdk/js");
const main = require(path.join(sdkRoot, "package.json")).main;
const sdk = require(path.join(sdkRoot, main));

const { inputs } = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(
  JSON.stringify({
    hashes: inputs.map(([u, f]) => sdk.consistentHash(u, f)),
    md5_hex: inputs.map(([u, f]) => sdk.md5Hex(`${u}:${f}`)),
  })
);
