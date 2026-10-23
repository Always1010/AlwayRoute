//go:build mipsle && gc && !purego

// Experimental CL585755 regression coverage. This adds no cipher implementation.
package chacha20

import (
	"bytes"
	"math/rand"
	"testing"
)

// Compare the original generic core with assembly through the public buffering
// API, including unaligned data, partial calls and state/counter transitions.
// Upstream TestLastBlock separately checks exhaustion, panic and overflow.
func TestAlwayRouteAssemblyDifferential(t *testing.T) {
	rng := rand.New(rand.NewSource(585755))
	sizes := []int{0, 1, 15, 16, 17, 31, 32, 63, 64, 65, 127, 128, 129,
		255, 256, 257, 1023, 1024, 1025, 4095, 4096, 4097, 16383, 16384, 16385}
	for i := 0; i < 32; i++ {
		sizes = append(sizes, rng.Intn(4097))
	}
	for caseID, size := range sizes {
		key, nonce := make([]byte, KeySize), make([]byte, NonceSize)
		rng.Read(key)
		rng.Read(nonce)
		counter := uint32(rng.Int31())
		padded := (size + 63) &^ 63
		source := make([]byte, padded+8)
		rng.Read(source)
		for offset := 0; offset < 4; offset++ {
			src := source[offset : offset+padded]
			reference, _ := NewUnauthenticatedCipher(key, nonce)
			reference.SetCounter(counter)
			want := make([]byte, padded)
			if padded > 0 {
				reference.xorKeyStreamBlocksGeneric(want, src)
			}
			inPlace := append([]byte(nil), src...)
			cipher, _ := NewUnauthenticatedCipher(key, nonce)
			cipher.SetCounter(counter)
			cipher.XORKeyStream(inPlace, inPlace)
			if !bytes.Equal(inPlace, want) {
				t.Fatalf("case=%d size=%d: in-place full blocks differ from generic", caseID, size)
			}
			for dstOffset := 0; dstOffset < 4; dstOffset++ {
				for _, step := range []int{1, 16, 63, 64, 65, 257, 16384} {
					cipher, _ := NewUnauthenticatedCipher(key, nonce)
					cipher.SetCounter(counter)
					storage := make([]byte, size+8)
					got := storage[dstOffset : dstOffset+size]
					for position := 0; position < size; {
						end := position + step
						if end > size {
							end = size
						}
						cipher.XORKeyStream(got[position:end], src[position:end])
						position = end
					}
					cipher.XORKeyStream(got[:0], src[:0])
					if !bytes.Equal(got, want[:size]) {
						t.Fatalf("case=%d size=%d srcOffset=%d dstOffset=%d step=%d: assembly differs from generic", caseID, size, offset, dstOffset, step)
					}
				}
			}
		}
	}
}
