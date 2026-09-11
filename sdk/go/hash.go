package experimentation

import (
	"crypto/md5" //nolint:gosec // MD5 used for consistent hashing, not cryptographic security
	"encoding/binary"
)

// hashDivisor is 2^32 (0x100000000), used to normalize the MD5-derived
// uint32 to a float64 in [0.0, 1.0). It matches every other platform SDK and
// the backend's consistent_hash module.
const hashDivisor = float64(0x100000000)

// ConsistentHash returns a deterministic float64 in [0.0, 1.0) for the given
// user ID and key (flag or experiment key).
//
// Algorithm (byte-for-byte compatible with the other platform SDKs and the
// golden vectors in tests/sdk-contract/golden-vectors.json):
//  1. Concatenate userID + ":" + key as UTF-8.
//  2. Compute the MD5 digest.
//  3. Interpret the first 4 bytes as a little-endian unsigned 32-bit integer.
//  4. Divide by 2^32.
//
// The SDK does not use this to decide variants any more (the server does);
// it is exported so integrations can verify cross-SDK parity.
func ConsistentHash(userID, key string) float64 {
	input := userID + ":" + key
	digest := md5.Sum([]byte(input)) //nolint:gosec
	v := binary.LittleEndian.Uint32(digest[:4])
	return float64(v) / hashDivisor
}
