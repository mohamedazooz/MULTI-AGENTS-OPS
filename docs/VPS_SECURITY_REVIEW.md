# VPS Security Review — Phase 2 / Phase C

**Status:** `RECON COMPLETE — NO CHANGES MADE — NETWORK PLAN REQUIRES REVIEW`
**Date:** 2026-11-21 (UTC)
**Host:** `Mohamedibrahemazooz-1928` / `102.206.132.212` (Azure VM)
**Raw evidence:** `C:\Users\azoozz\AppData\Local\Temp\opencode\phaseC\remote_batch_01..04.txt`, `local_tailscale_status.txt`, `local_tailscale_detail.txt`, `local_tnc_tailnet_22.txt`, `local_ssh_tailnet_test.txt`, `local_public_port_probes.txt`, `local_caddy_http_tls.txt`

> No firewall, SSH, Docker, Tailscale or systemd configuration was modified. No services
> were restarted. Environment values were never printed — only variable names.

---

## 1. Executive summary

- **Public SSH is the only verified administrative path.** Tailscale SSH is **not functional**.
  **Do not close port 22.**
- The host has **no host-level firewall policy**: UFW is inactive; `iptables INPUT ACCEPT`;
  Docker-published ports are exposed by DNAT rules; `DOCKER-USER` is empty.
- `machsol` is effectively root through three independent mechanisms: full `NOPASSWD: ALL`
  sudo, membership in `docker`, and membership in `lxd`.
- Azure NSG rules could **not** be read (no `az` CLI; IMDS unreachable). Port `8080` was
  **publicly reachable** during probing — do not assume an NSG protects it.
- The Tailscale container holds the excessive capability `CAP_SYS_MODULE`.

---

## 2. Tailscale / Tailnet SSH (critical finding)

### Container inspection

```text
image: tailscale/tailscale:latest
status: running, restart=unless-stopped
NetworkMode: sovereign-cloud-pc_default        <-- bridge, NOT host
Privileged: false
CapAdd: [CAP_NET_ADMIN CAP_SYS_MODULE]         <-- CAP_SYS_MODULE excessive
Binds: /home/machsol/sovereign-cloud-pc/tailscale_state:/var/lib/tailscale
       /home/machsol/sovereign-cloud-pc/tailscale_config:/config
       /dev/net/tun:/dev/net/tun
PortBindings: map[]                            <-- no published ports
ENV names: TS_USERSPACE, TS_HOSTNAME, TS_AUTHKEY, TS_STATE_DIR, TS_SERVE_CONFIG, PATH
```

`tailscale status --json` (inside container): `BackendState=Running`, `TUN=true`,
`TailscaleIPs=100.90.28.70`, `Online=true`, `Health=[]`,
cert domain `sovereign-pc.tail78ac09.ts.net`. Netmap contains an `SSHPolicy` and the node
advertises `https://tailscale.com/cap/ssh`.

**But the SSH server is not running:**

```text
tailscale debug prefs -> "RunSSH": false, "AdvertiseServices": null, "ShieldsUp": false
container: NO_SSHD_IN_CONTAINER, /etc/ssh: No such file or directory
container listeners: tailscaled on 100.90.28.70:52108 (PeerAPI) and :443 (Serve)
                     NOTHING on port 22; ts-input has no tcp/22 rule
```

### Local Tailnet verification (Windows client)

```text
tailscale status -> BackendState: "Stopped", Health: ["Tailscale is stopped."], TUN up=false
Test-NetConnection 100.90.28.70 -Port 22 -> TcpTestSucceeded=False
ssh -i <key> ... machsol@100.90.28.70 true -> connect ... port 22: Connection timed out (exit 255)
```

**Conclusion:** Host SSH is **not reachable over Tailnet**. Two independent blockers:
(a) `RunSSH:false` and no port-22 listener/rule inside the bridge-networked container;
(b) the local Windows Tailscale backend is stopped, so no client-side test was possible.
Additionally, `sshd` lives in the host netns while `tailscaled` lives in a container netns —
Tailscale SSH would have no local server to proxy to.

**Risk: HIGH.** The preferred administrative path does not exist yet. Any migration must
first fix the topology (host-network tailscaled or in-container sshd), set `RunSSH:true`,
tighten `SSHPolicy`, and verify from a **second online tailnet node** before touching port 22.

---

## 3. SSH daemon configuration

```text
sshd -t -> exit 0 (valid)
port 22; addressfamily any; listenaddress [::]:22; listenaddress 0.0.0.0:22
passwordauthentication yes; pubkeyauthentication yes; permitrootlogin without-password
kbdinteractiveauthentication no; maxauthtries 6; usepam yes; permitemptypasswords no
allowtcpforwarding yes; permitopen any; permitlisten any; x11forwarding yes
authenticationmethods any
No AllowUsers / AllowGroups / DenyUsers / DenyGroups (unrestricted)
sshd_config.d/50-cloud-init.conf -> PasswordAuthentication yes
```

Also present: `nft inet f2b-table` with `tcp dport 22 … reject` for 6 source IPs
(fail2ban-style, not UFW).

**Risk: HIGH.** Password authentication is enabled globally and root login is permitted
(without password). No user allow-list. Proposed hardening (not applied): remove the
cloud-init override, `PasswordAuthentication no`, `PermitRootLogin no`, `AllowUsers machsol
deployctl`, reduce `MaxAuthTries`, disable forwarding/X11, keep `PubkeyAuthentication yes`.
Always `sshd -t` before reload and keep an out-of-band path.

---

## 4. Host ports, firewall and Docker

### Listeners (`ss -lntup`)

```text
0.0.0.0:22    sshd + systemd        (public)
0.0.0.0:80    docker-proxy          (public)
0.0.0.0:443   docker-proxy          (public)
0.0.0.0:8080  nginx                 (public - see probes)
127.0.0.1:8765 docker-proxy         (loopback only)
127.0.0.1:5432 postgres, 127.0.0.1:6379 redis, 127.0.0.1:35107 containerd
```

### Firewall state

```text
ufw status verbose -> Status: inactive
iptables: INPUT ACCEPT, FORWARD DROP, OUTPUT ACCEPT
iptables nat: DNAT 0.0.0.0:80  -> 172.19.0.10:80  (Caddy, ! -i br-af33394fbfac)
              DNAT 0.0.0.0:443 -> 172.19.0.10:443 (Caddy)
              DNAT 127.0.0.1:8765 -> 172.21.0.5:8765 (kilo ACP, loopback only)
DOCKER-USER chain is EMPTY; FORWARD -> DOCKER-USER then DOCKER-FORWARD (accepts bridge traffic)
```

**Why not enable UFW blindly:** with UFW inactive there is no host policy at all. Even when
UFW is enabled, Docker owns `nat PREROUTING` DNAT and installs accept rules in `FORWARD`
ahead of host policy; `DOCKER-USER` is the intended override point and is empty. Published
`0.0.0.0` ports remain exposed unless an external control (NSG) or `DOCKER-USER` rules
restrict them. Any UFW work must start with saved rule snapshots, `ufw --dry-run`, explicit
allows, and console/serial access.

### Public reachability probes (from 192.168.1.4)

```text
22=True  80=True  443=True  8080=True
8765=False  2375=False  3000=False  5432=False  6379=False
```

Port `8080` (nginx → `https://127.0.0.1:443` with sslip.io SNI) is publicly reachable and
needs an explicit decision: restrict via NSG or `DOCKER-USER`, or confirm intentional exposure.

---

## 5. Azure NSG

```text
systemd-detect-virt -> microsoft
DMI vendor "Microsoft Corporation", product "Virtual Machine", Hyper-V UEFI
linux-azure / linux-image-*-azure / linux-cloud-tools-azure installed
az -> NOT_FOUND
az account show / az network nsg list -> "az: command not found"
IMDS 169.254.169.254 -> curl: (28) Connection timed out after 5002 ms
```

**Could not verify:** NSG name, resource group, subscription, inbound rules, effective
security rules. These require Azure portal or authenticated `az` CLI with Network Reader
RBAC. Because `8080` answered from the Internet, **do not assume NSG blocks anything**.

---

## 6. Caddy / HTTPS exposure

```text
image: caddy:2.10-alpine@sha256:4c6e91c6…
network: roomote_default
ports: 0.0.0.0:80, 0.0.0.0:443, 443/udp (no host 2019)
ENV names: ROOMOTE_CADDY_LOCAL_CERTS, ROOMOTE_CADDY_WILDCARD_TLS_SNIPPET,
           S3_BUCKET_ARTIFACTS, ROOMOTE_APP_DOMAIN, ROOMOTE_PREVIEW_DOMAIN
```

Local probes:

```text
http://102.206.132.212 -> HTTP/1.1 308 -> https://102.206.132.212/, Server: Caddy
https://102.206.132.212 (default SNI) -> curl (35) schannel error (no matching cert)
https://102.206.132.212.sslip.io/ --resolve -> HTTP/1.1 200 OK, <title>Roomote</title>
```

Valid Let's Encrypt cert for `102.206.132.212.sslip.io` through `2027-02-01` (Phase 0).
Public endpoints: `80/tcp` (redirect) and `443/tcp` served by Caddy `172.19.0.10`.
Tailnet-internal: tailscaled Serve listener on `100.90.28.70:443`.

---

## 7. Privileges

```text
getent group sudo docker lxd -> sudo:x:27:machsol / docker:x:115:machsol / lxd:x:101:machsol
id machsol -> uid=1000 groups=adm,sudo,lxd,docker,systemd-journal,...
sudo -n -l -> (ALL : ALL) ALL ; (ALL) NOPASSWD: ALL ;
              (ALL) NOPASSWD: /bin/systemctl reload nginx, /bin/systemctl restart nginx
sudoers.d/machsol_nopasswd -> "machsol ALL=(ALL) NOPASSWD: ALL"
```

**Risk: CRITICAL.** `machsol` is root-equivalent three times over. The `docker` group allows
mounting the host filesystem via a container; `lxd` similarly provides host escape. The
Tailscale container's `CAP_SYS_MODULE` permits kernel-module loading.

**Proposed restricted deployment user (design only):**

- `deployctl` service identity, shell `/usr/sbin/nologin`, **no** `sudo`/`docker`/`lxd`.
- Dedicated ed25519 key; `Match User deployctl` sshd block: password/Kbd off, no forwarding,
  no X11, `PermitRootLogin no`.
- Replace blanket `NOPASSWD: ALL` with a root-owned wrapper allowing only the specific
  `systemctl` operations needed, with `env_reset`, `secure_path`, `use_pty`, no `SETENV`.
- Never grant the raw Docker socket to deployment identities.
- Tailscale ACL: restrict SSH principals to named tailnet node IPs, map `sshUsers` to
  `deployctl` only, no root mapping, disable agent/port forwarding, short rule expiry.
- Keep `machsol` as sole break-glass admin until a tested Admin/SSH path exists.

---

## 8. Proposed firewall policy (conceptual, not applied)

1. **Azure NSG is the primary external control.** Allow `80`/`443` from Internet only if
   intentional; allow `22` only from a named management source; **deny `8080` from Internet**;
   deny all other inbound; enable rule logging.
2. **Do not enable UFW blindly.** First export `iptables -S`, `iptables -t nat -S`,
   `nft list ruleset`, `ufw status`, `sshd -T`, NSG. Stage with `ufw --dry-run`, pre-add
   explicit allows and Docker allowances, and keep console/serial access.
3. Use `DOCKER-USER` for source-IP restrictions on published container ports (survives
   Docker restarts), never ad-hoc `iptables -D` on Docker chains.
4. Harden `sshd` only after NSG export and with a tested recovery path.

---

## 9. Access migration with rollback (gated, not executed)

- **Gate 0** — Snapshot all rules/config; export NSG; verify out-of-band access.
- **Gate 1** — Fix Tailscale first (host networking or in-container sshd; `RunSSH:true`;
  confirm port-22 target and `ts-input` rule; tighten `SSHPolicy`).
- **Gate 2** — Independently verify Tailnet SSH from a **second online tailnet node**
  (not the stopped local client) with final ACL. Only then proceed.
- **Gate 3** — Apply NSG rule denying public `22` from Internet (keep management source);
  re-verify public SSH closed and Tailnet SSH working from two nodes.
- **Gate 4** — Apply sshd hardening (`sshd -t` first); verify from both paths.
- **Gate 5** — Restrict/deny public `8080`; verify `80`/`443` unaffected.

**Rollback:** revert NSG to exported rules first; restore saved `iptables`/`nft`/`sshd_config`
files and UFW state; `sshd -t && systemctl reload ssh`; re-open public `22` temporarily if
locked out. Never remove the last working administrative path in a single step.

---

## 10. Risk register

| Finding | Risk | Remediation |
|---|---|---|
| Tailnet SSH non-functional (`RunSSH:false`, bridge netns) | HIGH | Fix topology, enable, verify from second node |
| Password SSH enabled globally; root login permitted | HIGH | Disable password/root, allow-list users |
| UFW inactive; `INPUT ACCEPT`; empty `DOCKER-USER` | HIGH | NSG primary control + `DOCKER-USER`, staged UFW only if needed |
| Port `8080` publicly reachable | MED–HIGH | NSG deny or restrict source; confirm intent |
| `machsol` NOPASSWD ALL + docker + lxd | CRITICAL | Restricted `deployctl`; remove blanket sudo after migration |
| `CAP_SYS_MODULE` on Tailscale container | MED–HIGH | Drop capability in compose (change PR) |
| Azure NSG unreadable | MED | Obtain portal/CLI Network Reader access |
| Fail2ban nft rules only on :22 | LOW | Document; extend to other exposed services if needed |

---

## 11. Could not verify

1. Tailnet SSH end-to-end — local backend stopped; no successful SSH to `100.90.28.70:22`.
2. Azure NSG rules/effective security — `az` absent, IMDS unreachable.
3. Values of `TS_AUTHKEY`, `TS_SERVE_CONFIG`, `serve.json`, Caddy env — deliberately not read.
4. In-container `/dev/tcp` port test inconclusive (no `/dev/tcp`); conclusion based on
   `RunSSH:false`, absent listener, and absent netfilter rule.
5. Certificate chain details beyond the known valid Let's Encrypt record from Phase 0.

**Final gate:** public SSH must remain open until Gate 2 passes. No firewall modification is
authorized in this phase.
