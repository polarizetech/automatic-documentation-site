# Optional: hosting several sites from one machine

**You do not need any of this to read docs.** A built site opens from its folder
(`docsite dev`, `docsite build --open`, `docsite open owner/name`). This page is for one case
only: reading private repositories' docs from *another device* (a phone, a second machine),
which means one machine has to serve them over a private network.

A private repository's site is never put on the web. Its workflow commits the built site to a
`docs-site` branch; a machine on your private network pulls those branches and serves them.

## The host

`~/.config/automatic-documentation-site/hosts.toml` (local: it lists private repositories, so
it is never committed to this public repository):

```toml
port = 8251

[[site]]
repo = "owner/private-repo"     # cloned with this machine's git credentials
path = "private-repo"           # served at /private-repo/  (default: the repository name)

[[site]]
dir = "~/Sites/other/docs-site/dist"    # or a local build, served as-is
path = "other"
```

```bash
docsite sync                    # clone or update every repo-backed site
docsite serve --sync-every 300  # serve on 127.0.0.1:8251 and re-sync every 5 minutes
```

`/` lists the sites; `/<path>/` is a site. The server binds to localhost, lists no
directories, and sends `noindex`.

## Exposing it on a private network (Tailscale shown)

Mount it on a **tailnet-only** listener:

```bash
tailscale serve --bg --https=8443 --set-path /docs http://127.0.0.1:8251
```

→ `https://<machine>.<tailnet>.ts.net:8443/docs/<path>/`

**Never mount it on a listener with Funnel on.** Funnel is the public internet.

Tailscale strips the mount path before proxying. Every link a site writes is relative, and each
page adds the trailing slash to a bare prefix, so a site works at any depth.

## Keeping it running

`docsite serve` is a foreground process. To survive a restart it needs a service manager
(launchd on macOS, systemd on Linux) running `docsite serve --sync-every 300` at login.
