#!/bin/sh

# Configure only the evaluation image during its own first boot.
# No proxy core, DNS interception or forwarding rules are started here.
uci -q batch <<'EOF'
set network.lan.ipaddr='192.0.2.1'
set network.lan.netmask='255.255.255.0'
set dropbear.@dropbear[0].Port='2222'
set dropbear.@dropbear[0].Interface='lan'
set dropbear.@dropbear[0].PasswordAuth='off'
set dropbear.@dropbear[0].RootPasswordAuth='off'
delete uhttpd.main.listen_http
add_list uhttpd.main.listen_http='127.0.0.1:80'
delete uhttpd.main.listen_https
commit network
commit dropbear
commit uhttpd
EOF

exit 0
