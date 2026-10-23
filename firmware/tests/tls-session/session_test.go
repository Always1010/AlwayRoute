package tls

import (
	"context"
	"crypto/tls"
	"encoding/pem"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/sagernet/sing-box/option"
	"github.com/sagernet/sing/common/logger"
)

func sessionFixture(tb testing.TB, version uint16) (*httptest.Server, *STDClientConfig) {
	tb.Helper()
	s := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))
	s.TLS = &tls.Config{MinVersion: version, MaxVersion: version}
	s.StartTLS()
	tb.Cleanup(s.Close)
	return s, sessionConfig(tb, s)
}

func sessionConfig(tb testing.TB, s *httptest.Server) *STDClientConfig {
	tb.Helper()
	cert := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: s.Certificate().Raw})
	c, err := NewSTDClient(context.Background(), logger.NOP(), "", option.OutboundTLSOptions{
		Enabled: true, ServerName: s.Certificate().DNSNames[0], Certificate: []string{string(cert)},
	})
	if err != nil {
		tb.Fatal(err)
	}
	return c.(*STDClientConfig)
}

func sessionRequest(tb testing.TB, s *httptest.Server, c *STDClientConfig) (bool, error) {
	tb.Helper()
	// A fresh HTTP transport forces a fresh TCP/TLS connection for every request.
	tr := &http.Transport{TLSClientConfig: c.config, DisableKeepAlives: true}
	defer tr.CloseIdleConnections()
	response, err := (&http.Client{Transport: tr}).Get(s.URL)
	if err != nil {
		return false, err
	}
	defer response.Body.Close()
	_, err = io.Copy(io.Discard, response.Body)
	return response.TLS.DidResume, err
}

func TestOutboundSessionResumption(t *testing.T) {
	for _, version := range []uint16{tls.VersionTLS12, tls.VersionTLS13} {
		t.Run(tls.VersionName(version), func(t *testing.T) {
			s, c := sessionFixture(t, version)
			first, err := sessionRequest(t, s, c)
			if err != nil || first {
				t.Fatalf("first handshake: resumed=%v err=%v", first, err)
			}
			again, err := sessionRequest(t, s, c)
			if err != nil || !again {
				t.Fatalf("repeat handshake: resumed=%v err=%v", again, err)
			}
			// A separate outbound must not inherit another outbound's tickets.
			isolated := sessionConfig(t, s)
			resumed, err := sessionRequest(t, s, isolated)
			if err != nil || resumed {
				t.Fatalf("isolated handshake: resumed=%v err=%v", resumed, err)
			}
			// Even a populated cache must not bypass hostname verification.
			invalid := c.Clone().(*STDClientConfig)
			invalid.SetServerName("wrong.invalid")
			if _, err := sessionRequest(t, s, invalid); err == nil {
				t.Fatal("accepted a certificate for the wrong hostname")
			}
		})
	}
}

func BenchmarkOutboundSessionHandshake(b *testing.B) {
	for _, cache := range []bool{false, true} {
		name := "full"
		if cache {
			name = "resumed"
		}
		b.Run(name, func(b *testing.B) {
			s, c := sessionFixture(b, tls.VersionTLS13)
			if !cache {
				c.config.ClientSessionCache = nil
			}
			if _, err := sessionRequest(b, s, c); err != nil {
				b.Fatal(err)
			}
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				resumed, err := sessionRequest(b, s, c)
				if err != nil || resumed != cache {
					b.Fatalf("resumed=%v want=%v err=%v", resumed, cache, err)
				}
			}
		})
	}
}
