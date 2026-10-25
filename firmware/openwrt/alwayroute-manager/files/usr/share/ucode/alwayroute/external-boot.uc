'use strict';
import { validateExternal } from 'alwayroute.external-model';

// No live interface/address lookup: this guard must also work before netifd.
// The caller atomically persists it before durable enabled intent is written.
export function externalBootRules(candidate) {
 let c=validateExternal(candidate),l=c.link,lan=c.clientMode=='lan';
 let source=lan?'ether saddr != '+l.gatewayMac+' ip saddr != { '+l.routerAddress+', '+l.gatewayAddress+' } ip saddr '+c.clientCIDR:'ether saddr '+c.clients[0].mac+' ip saddr '+c.clients[0].address;
 let identity=lan?'ether saddr != '+l.gatewayMac:'ether saddr '+c.clients[0].mac;
 let bypass=join(', ',['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','224.0.0.0/4','240.0.0.0/4',...c.bypass4]);
 return 'table inet alwayroute_external_boot\ndelete table inet alwayroute_external_boot\ntable inet alwayroute_external_boot {\n comment "alwayroute-external-boot v1"\n set bypass4 { type ipv4_addr; flags interval; auto-merge; elements = { '+bypass+' }; }\n'+
 ' chain public_guard { type filter hook prerouting priority -153; policy accept;\n iifname != "'+l.interface+'" return\n '+source+' meta l4proto { tcp, udp } th dport 53 drop\n '+source+' ip daddr @bypass4 return\n '+source+' fib daddr type local return\n '+source+' drop\n }\n'+
 ' chain ipv6_guard { type filter hook forward priority -7; policy accept;\n iifname "'+l.interface+'" '+identity+' meta nfproto ipv6 ip6 daddr { fc00::/7, fe80::/10, ff00::/8 } return\n iifname "'+l.interface+'" '+identity+' meta nfproto ipv6 drop\n }\n'+
 ' chain dns_guard { type filter hook input priority -7; policy accept;\n iifname "'+l.interface+'" '+identity+' meta l4proto { tcp, udp } th dport { 53, '+c.dns.listenPort+' } drop\n }\n}\n';
};
