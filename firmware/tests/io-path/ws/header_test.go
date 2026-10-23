package ws

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"testing"
)

type fragmentHeaderReader struct {
	data             []byte
	pos, step, calls int
	terminal         error
}

func (r *fragmentHeaderReader) Read(p []byte) (int, error) {
	r.calls++
	if r.pos == len(r.data) {
		return 0, r.terminal
	}
	if len(p) > r.step {
		p = p[:r.step]
	}
	n := copy(p, r.data[r.pos:])
	r.pos += n
	return n, nil
}

func TestAlwayRouteHeaderDifferential(t *testing.T) {
	for _, length := range []uint64{0, 1, 125, 126, 65535, 65536, 1<<63 - 1, 1 << 63} {
		for _, masked := range []bool{false, true} {
			for _, first := range []byte{0, 0x82, 0x02, 0x89, 0x88, 0xff} {
				wire := []byte{first, 0}
				switch {
				case length < 126:
					wire[1] = byte(length)
				case length < 65536:
					wire[1] = 126
					wire = binary.BigEndian.AppendUint16(wire, uint16(length))
				default:
					wire[1] = 127
					wire = binary.BigEndian.AppendUint64(wire, length)
				}
				if masked {
					wire[1] |= 0x80
					wire = append(wire, 1, 2, 3, 4)
				}
				for cut := 0; cut <= len(wire); cut++ {
					for _, step := range []int{1, 3, 16} {
						for _, terminal := range []error{io.EOF, errors.New("injected")} {
							a := &fragmentHeaderReader{data: wire[:cut], step: step, terminal: terminal}
							b := &fragmentHeaderReader{data: wire[:cut], step: step, terminal: terminal}
							var scratch [MaxHeaderSize - 2]byte
							for i := range scratch {
								scratch[i] = 0xff
							}
							h1, e1 := ReadHeaderBuffer(a, &scratch)
							h2, e2 := legacyReadHeader(b)
							if h1 != h2 || fmt.Sprint(e1) != fmt.Sprint(e2) || a.pos != b.pos || a.calls != b.calls {
								t.Fatalf("length=%d masked=%v first=%x cut=%d step=%d: header %v/%v error %v/%v reads %d/%d bytes %d/%d", length, masked, first, cut, step, h1, h2, e1, e2, a.calls, b.calls, a.pos, b.pos)
							}
						}
					}
				}
			}
		}
	}
}

func TestAlwayRouteHeaderScratchReuse(t *testing.T) {
	// A long masked frame leaves bytes behind; a following short unmasked
	// frame must not inherit length or mask bits from that scratch storage.
	wire := []byte{0x82, 0xff, 0, 0, 0, 0, 0, 1, 0, 0, 1, 2, 3, 4, 0x89, 0, 0x82, 126, 0, 126}
	a, b := bytes.NewReader(wire), bytes.NewReader(wire)
	var scratch [MaxHeaderSize - 2]byte
	for i := 0; i < 4; i++ {
		h1, e1 := ReadHeaderBuffer(a, &scratch)
		h2, e2 := legacyReadHeader(b)
		if h1 != h2 || fmt.Sprint(e1) != fmt.Sprint(e2) || a.Len() != b.Len() {
			t.Fatalf("header %d: %v/%v %v/%v", i, h1, h2, e1, e2)
		}
	}
}

func BenchmarkAlwayRouteHeader(b *testing.B) {
	wire := []byte{0x82, 126, 0x3a, 0x98}
	for _, legacy := range []bool{true, false} {
		b.Run(fmt.Sprintf("legacy=%v", legacy), func(b *testing.B) {
			r := bytes.NewReader(wire)
			var scratch [MaxHeaderSize - 2]byte
			b.ReportAllocs()
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				r.Reset(wire)
				var h Header
				var err error
				if legacy {
					h, err = legacyReadHeader(r)
				} else {
					h, err = ReadHeaderBuffer(r, &scratch)
				}
				if err != nil || h.Length != 15000 {
					b.Fatal(h, err)
				}
			}
		})
	}
}
