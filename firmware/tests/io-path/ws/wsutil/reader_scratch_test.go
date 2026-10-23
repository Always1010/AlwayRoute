package wsutil

import (
	"bytes"
	"errors"
	"io"
	"testing"

	"github.com/sagernet/ws"
)

func TestAlwayRouteReaderFragmentControl(t *testing.T) {
	var wire bytes.Buffer
	frames := []ws.Frame{
		ws.NewFrame(ws.OpBinary, false, []byte("first")),
		ws.NewFrame(ws.OpPing, true, []byte("ping")),
		ws.NewFrame(ws.OpContinuation, true, []byte("second")),
		ws.NewFrame(ws.OpBinary, true, bytes.Repeat([]byte{7}, 65536)),
		ws.NewFrame(ws.OpBinary, true, []byte("last")),
	}
	for _, frame := range frames {
		if err := ws.WriteFrame(&wire, frame); err != nil {
			t.Fatal(err)
		}
	}
	r := NewClientSideReader(&wire)
	controls := 0
	r.OnIntermediate = func(h ws.Header, body io.Reader) error {
		data, err := io.ReadAll(body)
		if h.OpCode != ws.OpPing || string(data) != "ping" {
			t.Fatalf("unexpected control: %v %q", h, data)
		}
		controls++
		return err
	}
	for _, want := range [][]byte{[]byte("firstsecond"), bytes.Repeat([]byte{7}, 65536), []byte("last")} {
		if _, err := r.NextFrame(); err != nil {
			t.Fatal(err)
		}
		got, err := io.ReadAll(r)
		if err != nil || !bytes.Equal(got, want) {
			t.Fatalf("payload=%d/%d error=%v", len(got), len(want), err)
		}
	}
	if controls != 1 {
		t.Fatalf("control callbacks=%d", controls)
	}
	if _, err := r.NextFrame(); err != io.EOF {
		t.Fatalf("terminal error: %v", err)
	}
}

func TestAlwayRouteReaderMaskAndValidation(t *testing.T) {
	var wire bytes.Buffer
	frame := ws.MaskFrame(ws.NewFrame(ws.OpBinary, true, []byte("masked payload")))
	if err := ws.WriteFrame(&wire, frame); err != nil {
		t.Fatal(err)
	}
	r := NewServerSideReader(bytes.NewReader(wire.Bytes()))
	if _, err := r.NextFrame(); err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(r)
	if err != nil || string(got) != "masked payload" {
		t.Fatalf("payload=%q error=%v", got, err)
	}
	client := NewClientSideReader(bytes.NewReader(wire.Bytes()))
	if _, err := client.NextFrame(); err == nil {
		t.Fatal("client accepted a masked server frame")
	}
	limited := NewServerSideReader(bytes.NewReader(wire.Bytes()))
	limited.MaxFrameSize = 1
	if _, err := limited.NextFrame(); !errors.Is(err, ErrFrameTooLarge) {
		t.Fatalf("size limit: %v", err)
	}
}

func TestAlwayRouteReaderTruncation(t *testing.T) {
	for _, wire := range [][]byte{{0x82, 3, 'a'}, {0x02, 1, 'a'}} {
		r := NewClientSideReader(bytes.NewReader(wire))
		if _, err := r.NextFrame(); err != nil {
			t.Fatal(err)
		}
		if _, err := io.ReadAll(r); !errors.Is(err, io.ErrUnexpectedEOF) {
			t.Fatalf("wire=%x error=%v", wire, err)
		}
	}
}
