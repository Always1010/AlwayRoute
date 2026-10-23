//go:build mipsle && gc && !purego

// Experimental CL585755 regression coverage. This adds no cipher implementation.
package chacha20

import (
	"bytes"
	"math/rand"
	"syscall"
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

// Guard both ends of the accessible page: an assembly overread or overwrite
// crossing a page boundary faults, while canaries catch writes inside the page.
func TestAlwayRouteAssemblyGuardedBuffers(t *testing.T) {
	page := syscall.Getpagesize()
	guarded := func() []byte {
		mapping, err := syscall.Mmap(-1, 0, 3*page, syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_PRIVATE|syscall.MAP_ANON)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() {
			if err := syscall.Munmap(mapping); err != nil {
				t.Error(err)
			}
		})
		for _, guard := range [][]byte{mapping[:page], mapping[2*page:]} {
			if err := syscall.Mprotect(guard, syscall.PROT_NONE); err != nil {
				t.Fatal(err)
			}
		}
		return mapping[page : 2*page : 2*page]
	}
	source, destination := guarded(), guarded()
	for _, size := range []int{0, 1, 15, 16, 17, 63, 64, 65, 127, 128, 129, page - 1, page} {
		padded := (size + 63) &^ 63
		payload := make([]byte, padded)
		for i := 0; i < size; i++ {
			payload[i] = byte(i*17 + size)
		}
		counter := ^uint32(0)
		if padded > 0 {
			counter -= uint32(padded/64 - 1)
		}
		newCipher := func() *Cipher {
			c, err := NewUnauthenticatedCipher(make([]byte, KeySize), make([]byte, NonceSize))
			if err != nil {
				t.Fatal(err)
			}
			c.SetCounter(counter)
			return c
		}
		want := make([]byte, padded)
		if padded > 0 {
			newCipher().xorKeyStreamBlocksGeneric(want, payload)
		}
		positions := []int{0, 1, 3, page - size, page - size - 1, page - size - 3}
		for _, srcStart := range positions {
			if srcStart < 0 || srcStart+size > page {
				continue
			}
			for i := range source {
				source[i] = 0xa5
			}
			copy(source[srcStart:srcStart+size], payload[:size])
			before := append([]byte(nil), source...)
			for _, dstStart := range positions {
				if dstStart < 0 || dstStart+size > page {
					continue
				}
				for i := range destination {
					destination[i] = 0xa5
				}
				newCipher().XORKeyStream(destination[dstStart:dstStart+size], source[srcStart:srcStart+size])
				if !bytes.Equal(destination[dstStart:dstStart+size], want[:size]) || !bytes.Equal(source, before) {
					t.Fatalf("size=%d src=%d dst=%d: wrong output or modified source", size, srcStart, dstStart)
				}
				for i, b := range destination {
					if (i < dstStart || i >= dstStart+size) && b != 0xa5 {
						t.Fatalf("size=%d dst=%d: overwritten canary at %d", size, dstStart, i)
					}
				}
			}
			newCipher().XORKeyStream(source[srcStart:srcStart+size], source[srcStart:srcStart+size])
			if !bytes.Equal(source[srcStart:srcStart+size], want[:size]) {
				t.Fatalf("size=%d src=%d: wrong in-place output", size, srcStart)
			}
			for i, b := range source {
				if (i < srcStart || i >= srcStart+size) && b != 0xa5 {
					t.Fatalf("size=%d src=%d: overwritten in-place canary at %d", size, srcStart, i)
				}
			}
		}
	}
}
