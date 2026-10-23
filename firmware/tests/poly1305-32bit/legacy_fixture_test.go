//go:build mipsle && gc && !purego

package poly1305

import "testing"

// Test-only representation of the existing three nonzero accumulator fixtures.
// Keep the original integer, including its high noncanonical bits. Unknown new
// fixtures fail closed; no vector or boundary assertion is removed or skipped.
// No state conversion or arithmetic adapter is included in production code.
func alwayRouteSetLegacyInitialState(h *MAC, state [3]uint64) {
	switch state {
	case [3]uint64{0xfffffffffffffff5, 0xffffffffffffffff, 7}:
		h.macGeneric32.h = [5]uint32{0x3fffff5, 0x3ffffff, 0x3ffffff, 0x3ffffff, 0x7ffffff}
	case [3]uint64{0, 0, 7}:
		h.macGeneric32.h = [5]uint32{0, 0, 0, 0, 0x7000000}
	case [3]uint64{1, 0, 7}:
		h.macGeneric32.h = [5]uint32{1, 0, 0, 0, 0x7000000}
	default:
		panic("unrecognized upstream accumulator fixture")
	}
}

func TestAlwayRouteLegacyMACLifecycle(t *testing.T) {
	key := [32]byte{0x85, 0xd6, 0xbe, 0x78, 0x57, 0x55, 0x6d, 0x33}
	message := []byte("0123456789abcdef")
	var want [TagSize]byte
	sumGeneric(&want, message, &key)
	mac := New(&key)
	mac.Write(message[:1])
	mac.Write(message[1:]) // exactly fills a partial block: offset must not be 16
	var got, again [TagSize]byte
	mac.Sum(got[:0])
	mac.Sum(again[:0])
	if got != want || again != want {
		t.Fatal("split-block or repeated Sum differs from current generic reference")
	}
	expectPanic := func(write func()) {
		t.Helper()
		defer func() {
			if recover() == nil {
				t.Error("Write after finalization did not panic")
			}
		}()
		write()
	}
	expectPanic(func() { mac.Write(nil) })
	for _, valid := range []bool{true, false} {
		mac = New(&key)
		mac.Write(message)
		tag := want
		if !valid {
			tag[0] ^= 1
		}
		if mac.Verify(tag[:]) != valid {
			t.Fatal("Verify acceptance changed")
		}
		expectPanic(func() { mac.Write(nil) })
	}
}
