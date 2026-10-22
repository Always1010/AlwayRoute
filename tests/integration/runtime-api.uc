'use strict';
// Run with the pinned OpenWrt host ucode. Uses only its own temporary directory.
import * as fs from 'fs';
import { sha256 } from 'digest';

function check(value, message) { if (!value) die(message); }
let dir = fs.mkdtemp('/tmp/alwayroute-runtime-audit-XXXXXX');
check(dir, 'cannot create isolated test directory');
let a = null, b = null, failed = false;
try {
 check(sha256('abc') == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', 'digest ABI mismatch');
 a = fs.open(dir + '/lock', 'ae', 0600);
 b = fs.open(dir + '/lock', 'ae', 0600);
 check(a && b && a.lock('xn'), 'exclusive nonblocking lock unavailable');
 check(!b.lock('xn'), 'second descriptor unexpectedly acquired lock');
 check(a.lock('u') && b.lock('xn'), 'lock does not release correctly');
 a.close(); a = null; b.close(); b = null;
 let f = fs.open(dir + '/candidate', 'wxe', 0600);
 check(f && f.write('abcdef') == 6 && f.flush() && f.close(), 'atomic-write prerequisites unavailable');
 check(fs.rename(dir + '/candidate', dir + '/current'), 'rename unavailable');
 check(fs.readfile(dir + '/current', 3) == 'abc', 'bounded readfile unavailable');
 check(fs.stat(dir + '/current').perm.user_read && !fs.stat(dir + '/current').perm.group_read, 'private file permissions failed');
 let error = null;
 try { die(sprintf('%J', {code:'AUDIT_SENTINEL',message:'controlled failure'})); }
 catch (e) { error = json(e.message); }
 check(error?.code == 'AUDIT_SENTINEL', 'structured failure encoding unavailable');
 print('PASS pinned ucode fs/digest/lock/error compatibility\n');
}
catch (e) { warn('FAIL runtime compatibility: ', e.message, '\n'); failed = true; }
a?.close(); b?.close();
fs.unlink(dir + '/lock'); fs.unlink(dir + '/candidate'); fs.unlink(dir + '/current'); fs.rmdir(dir);
if (failed) exit(1);
