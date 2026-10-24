package redirect

import (
	"errors"
	"net"
	"os"
	"testing"
	"time"

	"github.com/sagernet/sing-box/common/listener"
	"github.com/sagernet/sing/common/buf"
	M "github.com/sagernet/sing/common/metadata"
)

// Use ordinary loopback sockets: no TProxy capability or router is needed.
// An expired deadline causes a real write failure while leaving the socket open,
// so this catches dropping w.conn without releasing its file descriptor.
func TestTProxyReusedSocketWriteErrorCloses(t *testing.T) {
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.Close() })
	if err = conn.SetWriteDeadline(time.Now().Add(-time.Second)); err != nil {
		t.Fatal(err)
	}
	destination := M.SocksaddrFromNet(conn.LocalAddr())
	writer := &tproxyPacketWriter{
		listener: listener.New(listener.Options{}), destination: destination,
		source: conn.LocalAddr().(*net.UDPAddr).AddrPort(), conn: conn,
	}
	err = writer.WritePacket(buf.As([]byte("deadline")), destination)
	if !errors.Is(err, os.ErrDeadlineExceeded) {
		t.Fatalf("expected write timeout, got %v", err)
	}
	if writer.conn != nil {
		t.Fatal("failed socket remains reusable")
	}
	if err = conn.SetWriteDeadline(time.Time{}); !errors.Is(err, net.ErrClosed) {
		t.Fatalf("failed socket was discarded without being closed: %v", err)
	}
}

func TestTProxyReusedSocketSuccessRetains(t *testing.T) {
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.Close() })
	destination := M.SocksaddrFromNet(conn.LocalAddr())
	writer := &tproxyPacketWriter{
		listener: listener.New(listener.Options{}), destination: destination,
		source: conn.LocalAddr().(*net.UDPAddr).AddrPort(), conn: conn,
	}
	if err = writer.WritePacket(buf.As([]byte("retained")), destination); err != nil {
		t.Fatal(err)
	}
	if writer.conn != conn {
		t.Fatal("successful cached socket was discarded")
	}
	if err = conn.SetReadDeadline(time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	var packet [32]byte
	n, _, err := conn.ReadFromUDPAddrPort(packet[:])
	if err != nil || string(packet[:n]) != "retained" {
		t.Fatalf("cached socket did not transmit payload: %q, %v", packet[:n], err)
	}
}
