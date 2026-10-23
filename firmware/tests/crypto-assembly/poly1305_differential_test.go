//go:build mipsle && gc && !purego

// Experimental CL585755 regression coverage. This adds no MAC implementation.
package poly1305

import (
	"math/rand"
	"testing"
)

// Compare assembly streaming state against the unchanged generic one-shot MAC.
// Upstream tests additionally cover RFC vectors, noncanonical accumulator states,
// unaligned inputs and Verify failures.
func TestAlwayRouteAssemblyDifferential(t *testing.T) {
	rng := rand.New(rand.NewSource(585755))
	sizes := []int{0, 1, 15, 16, 17, 31, 32, 33, 63, 64, 65, 255, 256, 257,
		1023, 1024, 1025, 4095, 4096, 4097, 16383, 16384, 16385}
	for i := 0; i < 32; i++ {
		sizes = append(sizes, rng.Intn(4097))
	}
	for caseID, size := range sizes {
		var key [32]byte
		rng.Read(key[:])
		storage := make([]byte, size+8)
		rng.Read(storage)
		for offset := 0; offset < 4; offset++ {
			src := storage[offset : offset+size]
			var want [TagSize]byte
			sumGeneric(&want, src, &key)
			for _, step := range []int{1, 15, 16, 17, 63, 64, 65, 257, 16384} {
				mac := New(&key)
				for position := 0; position < size; {
					end := position + step
					if end > size {
						end = size
					}
					if n, err := mac.Write(src[position:end]); err != nil || n != end-position {
						t.Fatalf("Write failed: %d, %v", n, err)
					}
					position = end
				}
				mac.Write(nil)
				var got [TagSize]byte
				mac.Sum(got[:0])
				if got != want {
					t.Fatalf("case=%d size=%d offset=%d step=%d: assembly differs from generic", caseID, size, offset, step)
				}
			}
		}
	}
}
