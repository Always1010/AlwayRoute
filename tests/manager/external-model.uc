'use strict';
import { emptyExternal, validateExternal, validateExternalPeer } from 'alwayroute.external-model';
let checks=0;
function check(value,message) {checks++;assert(value,message);}
function rejects(callback) {let rejected=false;try{callback();}catch(e){rejected=true;}check(rejected,'unsafe external input must fail');}
let initial=emptyExternal();check(validateExternal(initial).enabled===false,'missing configuration starts disabled');
let config={schema:1,revision:2,enabled:true,family:'ipv4',faultPolicy:'block',link:{interface:'br-lan',routerAddress:'192.0.2.1',gatewayAddress:'192.0.2.2',gatewayMac:'02:00:00:00:00:02'},clients:[{address:'192.0.2.3',mac:'02:00:00:00:00:03'}],dns:{gatewayPort:1053,listenPort:1053,localDomains:['lan']},bypass4:['198.51.100.0/24']};
check(validateExternal(config).revision==2,'valid synthetic scope accepted');
for(let key,value in {enabled:'true',faultPolicy:'direct',revision:-1,family:'dual',unexpected:true}) {let bad=json(sprintf('%J',config));bad[key]=value;rejects(()=>validateExternal(bad));}
for(let value in ['br-lan;reboot','-bad',"bad\nname"]) {let bad=json(sprintf('%J',config));bad.link.interface=value;rejects(()=>validateExternal(bad));}
for(let value in ['0.0.0.0/0','198.51.100.1/24','198.51.100.0/024','not-a-cidr']) {let bad=json(sprintf('%J',config));bad.bypass4=[value];rejects(()=>validateExternal(bad));}
let bad=json(sprintf('%J',config));bad.clients[0].address=config.link.gatewayAddress;rejects(()=>validateExternal(bad));
bad=json(sprintf('%J',config));bad.clients[0].mac='01:00:00:00:00:03';rejects(()=>validateExternal(bad));
bad=json(sprintf('%J',config));bad.dns.listenPort=53;rejects(()=>validateExternal(bad));
bad=json(sprintf('%J',config));bad.dns.localDomains=['lan\nserver=bad'];rejects(()=>validateExternal(bad));
let lan=json(sprintf('%J',config));lan.clientMode='lan';lan.clientCIDR='192.0.2.0/24';lan.clients=[];
check(validateExternal(lan).clientCIDR=='192.0.2.0/24','explicit entire LAN scope permits DHCP clients without identities');
for(let value in ['192.0.2.1/24','192.0.3.0/24','192.0.2.0/32','192.0.2.0/31','192.0.2.0/024','0.0.0.0/0']) {let bad=json(sprintf('%J',lan));bad.clientCIDR=value;rejects(()=>validateExternal(bad));}
bad=json(sprintf('%J',lan));bad.clients=config.clients;rejects(()=>validateExternal(bad));
bad=json(sprintf('%J',lan));bad.clientMode='all';rejects(()=>validateExternal(bad));
bad=json(sprintf('%J',lan));delete bad.clientMode;rejects(()=>validateExternal(bad));
bad=json(sprintf('%J',config));bad.clients=[];rejects(()=>validateExternal(bad));
let peer={gateway:config.link.gatewayAddress,revision:2,generation:'synthetic-generation',observedAt:100,coreReady:true,captureReady:true,dnsReady:true,egressViaRouter:true,returnViaRouter:true,sourcePreserved:true};
check(validateExternalPeer(peer,config,110).method=='operator','manual observation explicitly labeled');
rejects(()=>validateExternalPeer(peer,config,131));rejects(()=>validateExternalPeer(peer,config,99));
peer.revision=1;rejects(()=>validateExternalPeer(peer,config,110));peer.revision=2;peer.captureReady=false;rejects(()=>validateExternalPeer(peer,config,110));
print(sprintf('PASS external configuration and observation: %d checks\n',checks));
